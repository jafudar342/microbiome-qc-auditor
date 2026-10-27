"""Built-in --self-test checks that never touch research data."""

from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path

from .audit import AuditOptions, run_audit
from .classification import classify_sample
from .fastq import scan_fastq
from .fastqc import parse_fastqc_report
from .models import PASS, FAIL
from .pairing import normalize_read_id
from .synthetic import (
    FASTQC_STANDARD_MODULES,
    paired_records,
    write_fastq,
    write_fastqc_zip,
)


def _write_pass_fixture(fastq_dir: Path, fastqc_dir: Path, sample: str = "SELFTEST") -> None:
    fastq_dir.mkdir(parents=True, exist_ok=True)
    fastqc_dir.mkdir(parents=True, exist_ok=True)
    r1_records, r2_records = paired_records(sample, 4, length=50, gc_percent=50)
    r1_name = f"{sample}_R1.fastq.gz"
    r2_name = f"{sample}_R2.fastq.gz"
    write_fastq(fastq_dir / r1_name, r1_records)
    write_fastq(fastq_dir / r2_name, r2_records)
    statuses = {module: PASS for module in FASTQC_STANDARD_MODULES}
    write_fastqc_zip(
        fastqc_dir / f"{sample}_R1_fastqc.zip",
        input_filename=r1_name,
        module_statuses=statuses,
        total_sequences=len(r1_records),
    )
    write_fastqc_zip(
        fastqc_dir / f"{sample}_R2_fastqc.zip",
        input_filename=r2_name,
        module_statuses=statuses,
        total_sequences=len(r2_records),
    )


def run_self_test() -> int:
    """Run small in-memory/temp-directory checks and return an exit code."""
    results: list[tuple[str, bool, str]] = []

    def record(name: str, success: bool, detail: str = "") -> None:
        results.append((name, success, detail))

    with tempfile.TemporaryDirectory(prefix="microbiome-qc-selftest-") as temporary:
        root = Path(temporary)
        fastq_dir = root / "FASTQ"
        fastqc_dir = root / "FastQC"
        try:
            _write_pass_fixture(fastq_dir, fastqc_dir)
            check_stats = scan_fastq(fastq_dir / "SELFTEST_R1.fastq.gz")
            record(
                "FASTQ stream and statistics",
                check_stats.valid
                and check_stats.stats.total_reads == 4
                and check_stats.stats.total_bases == 200
                and check_stats.stats.gc_percent == 50.0,
                str(check_stats.errors) if not check_stats.valid else "4 reads, 200 bases, 50% GC",
            )
        except Exception as exc:  # Self-test must report rather than crash.
            record("FASTQ stream and statistics", False, f"{exc.__class__.__name__}: {exc}")

        try:
            core_slash_1, _ = normalize_read_id("@read/1")
            core_slash_2, _ = normalize_read_id("@read/2")
            _, illumina_direction = normalize_read_id("@M00176:1:1:1:1 2:N:0:1")
            record(
                "Paired identifier normalization",
                core_slash_1 == core_slash_2 == "read" and illumina_direction == "2",
                "slash suffixes and Illumina direction normalized",
            )
        except Exception as exc:
            record("Paired identifier normalization", False, f"{exc.__class__.__name__}: {exc}")

        try:
            bad_fastq = root / "bad.fastq"
            bad_fastq.write_text("@r1\nACGT\n-\nIIII\n", encoding="utf-8")
            bad_scan = scan_fastq(bad_fastq)
            record(
                "Structural corruption detection",
                (not bad_scan.valid) and any("separator" in error for error in bad_scan.errors),
                bad_scan.errors[0] if bad_scan.errors else "no error produced",
            )
        except Exception as exc:
            record("Structural corruption detection", False, f"{exc.__class__.__name__}: {exc}")

        try:
            report = parse_fastqc_report(fastqc_dir / "SELFTEST_R1_fastqc.zip")
            record(
                "FastQC archive parsing",
                report.available
                and len(report.modules) == len(FASTQC_STANDARD_MODULES)
                and report.fail_count == 0
                and report.total_sequences == 4,
                f"{len(report.modules)} modules parsed",
            )
        except Exception as exc:
            record("FastQC archive parsing", False, f"{exc.__class__.__name__}: {exc}")

        try:
            decision = classify_sample(
                structural_errors=("simulated invalid FASTQ record",),
                fastqc_module_findings=(("R1: Adapter Content", PASS),),
            )
            record(
                "Classification precedence",
                decision.status == FAIL,
                f"structural error plus FastQC PASS -> {decision.status}",
            )
        except Exception as exc:
            record("Classification precedence", False, f"{exc.__class__.__name__}: {exc}")

        try:
            output_dir = root / "QC_Report"
            result = run_audit(
                AuditOptions(
                    fastq_dir=fastq_dir,
                    fastqc_dir=fastqc_dir,
                    output_dir=output_dir,
                )
            )
            with (output_dir / "sample_summary.csv").open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
            expected_files = {
                "sample_summary.csv",
                "fastqc_modules.csv",
                "summary.json",
                "report.html",
            }
            written = {path.name for path in output_dir.iterdir()}
            record(
                "End-to-end audit and report writing",
                result.pass_count == 1
                and len(rows) == 1
                and rows[0]["qc_classification"] == PASS
                and payload["counts"]["pass"] == 1
                and expected_files <= written,
                "one PASS sample; CSV, JSON, and HTML written",
            )
        except Exception as exc:
            record("End-to-end audit and report writing", False, f"{exc.__class__.__name__}: {exc}")

    failures = 0
    for name, success, detail in results:
        prefix = "PASS" if success else "FAIL"
        print(f"[{prefix}] {name}" + (f" - {detail}" if detail else ""))
        if not success:
            failures += 1
    print(f"\nSelf-test: {len(results) - failures}/{len(results)} checks passed.")
    return 0 if failures == 0 else 1


__all__ = ["run_self_test"]
