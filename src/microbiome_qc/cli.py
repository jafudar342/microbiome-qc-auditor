"""Command-line interface for Microbiome QC Auditor."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import __version__
from .audit import AuditOptions, run_audit
from .errors import DemoError, MicrobiomeQCError
from .selftest import run_self_test
from .synthetic import generate_demo_dataset

EXIT_SUCCESS = 0
EXIT_AUDIT_FAILURE = 1
EXIT_USAGE = 2
EXIT_WARN_GATE = 3

EXIT_CODES_HELP = (
    "exit codes: 0 = completed without QC failures; 1 = at least one FAIL sample; "
    "2 = usage/input/output error; 3 = --fail-on-warn triggered by WARN samples"
)


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected an integer, got '{value}'") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _add_verbosity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="increase logging verbosity (-v for INFO, -vv for DEBUG)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="microbiome-qc",
        description=(
            "Offline audit of paired-end FASTQ integrity and FastQC module statuses. "
            "This is a quality-control tool, not a biological or clinical interpretation."
        ),
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="run built-in checks in a temporary directory and exit",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="{audit,demo,self-test}")

    audit = subparsers.add_parser(
        "audit",
        help="audit paired FASTQ files and optional FastQC ZIP reports",
        description="Discover paired FASTQ files, validate them, and write four QC reports.",
        epilog=EXIT_CODES_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    audit.add_argument(
        "--fastq-dir",
        required=True,
        type=Path,
        help="directory that directly contains .fastq/.fq/.fastq.gz/.fq.gz files",
    )
    audit.add_argument(
        "--fastqc-dir",
        type=Path,
        default=None,
        help="optional directory containing FastQC *_fastqc.zip archives",
    )
    audit.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="directory for sample_summary.csv, fastqc_modules.csv, summary.json, report.html",
    )
    audit.add_argument(
        "--max-errors",
        type=_positive_int,
        default=5,
        metavar="N",
        help="maximum detailed pairing mismatches/fastqc row errors to retain (default: 5)",
    )
    audit.add_argument(
        "--overwrite",
        action="store_true",
        help="explicitly allow replacing existing report files in --output-dir",
    )
    audit.add_argument(
        "--fail-on-warn",
        action="store_true",
        help="exit 3 when the audit completes with WARN samples (FAIL still exits 1)",
    )
    _add_verbosity(audit)

    demo = subparsers.add_parser(
        "demo",
        help="generate a synthetic demo dataset without downloading anything",
        description="Write synthetic FASTQ pairs and FastQC archives for a local demonstration.",
    )
    demo.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="directory to receive the synthetic FASTQ, FastQC, and README.md files",
    )
    demo.add_argument(
        "--overwrite",
        action="store_true",
        help="allow writing into a non-empty demo directory",
    )
    _add_verbosity(demo)

    subparsers.add_parser(
        "self-test",
        help="run built-in checks in a temporary directory and exit",
    )
    return parser


def _configure_logging(verbosity: int) -> None:
    if verbosity <= 0:
        level = logging.WARNING
    elif verbosity == 1:
        level = logging.INFO
    else:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


def _print_audit_summary(result, fail_on_warn: bool) -> int:
    print(
        f"Audit completed: {result.sample_count} sample(s) - "
        f"PASS={result.pass_count} WARN={result.warn_count} FAIL={result.fail_count}"
    )
    print(f"Reports written to {result.output_dir}:")
    for path in result.outputs:
        print(f"  {path}")

    if result.fail_count:
        failed = [s for s in result.samples if s.classification.status == "FAIL"]
        shown = ", ".join(sample.sample_id for sample in failed[:10])
        suffix = "" if len(failed) <= 10 else f", and {len(failed) - 10} more"
        print(f"FAIL samples: {shown}{suffix}", file=sys.stderr)
        print(
            "At least one sample failed structural or pairing integrity checks. "
            "Review report.html before downstream analysis.",
            file=sys.stderr,
        )
        return EXIT_AUDIT_FAILURE
    if fail_on_warn and result.warn_count:
        print(
            f"--fail-on-warn is set and {result.warn_count} sample(s) were classified WARN.",
            file=sys.stderr,
        )
        return EXIT_WARN_GATE
    return EXIT_SUCCESS


def _run_audit(args: argparse.Namespace) -> int:
    warn_limit = args.max_errors
    options = AuditOptions(
        fastq_dir=args.fastq_dir,
        fastqc_dir=args.fastqc_dir,
        output_dir=args.output_dir,
        max_errors=args.max_errors,
        overwrite=args.overwrite,
        fail_on_warn=args.fail_on_warn,
    )
    try:
        result = run_audit(options)
    except MicrobiomeQCError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    for warning in result.warnings[:warn_limit]:
        print(f"warning: {warning}", file=sys.stderr)
    remaining = len(result.warnings) - warn_limit
    if remaining > 0:
        print(
            f"warning: {remaining} additional warning(s) not shown "
            "(raise --max-errors or inspect report.html).",
            file=sys.stderr,
        )
    return _print_audit_summary(result, fail_on_warn=args.fail_on_warn)


def _run_demo(args: argparse.Namespace) -> int:
    try:
        details = generate_demo_dataset(args.output_dir, overwrite=args.overwrite)
    except (DemoError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(f"Synthetic demo dataset created in {details['directory']}")
    print("It contains 7 synthetic samples (expected: 1 PASS, 3 WARN, 3 FAIL).")
    print("Run an audit with:")
    print(
        "  microbiome-qc audit "
        f"--fastq-dir {details['fastq_dir']} "
        f"--fastqc-dir {details['fastqc_dir']} "
        f"--output-dir {Path(details['directory']) / 'QC_Report'}"
    )
    print("Exit code 1 is expected because the demo includes three failing samples.")
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.self_test:
        if args.command is not None:
            parser.error("--self-test cannot be combined with a subcommand")
        _configure_logging(0)
        return run_self_test()

    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_USAGE

    _configure_logging(getattr(args, "verbose", 0))
    if args.command == "audit":
        return _run_audit(args)
    if args.command == "demo":
        return _run_demo(args)
    if args.command == "self-test":
        return run_self_test()
    parser.error(f"unknown command: {args.command}")
    return EXIT_USAGE


__all__ = [
    "EXIT_SUCCESS",
    "EXIT_AUDIT_FAILURE",
    "EXIT_USAGE",
    "EXIT_WARN_GATE",
    "build_parser",
    "main",
]
