"""Atomic CSV/JSON/self-contained HTML report generation."""

from __future__ import annotations

import csv
import io
import json
import os
import tempfile
from pathlib import Path

from . import TOOL_NAME, __version__
from .errors import OutputError
from .html_template import HTML_TEMPLATE
from .models import (
    AuditResult,
    FastQCSideResult,
    SampleAudit,
)

REPORT_FILENAMES = (
    "sample_summary.csv",
    "fastqc_modules.csv",
    "summary.json",
    "report.html",
)

SAMPLE_SUMMARY_COLUMNS = (
    "sample_id",
    "r1_filename",
    "r2_filename",
    "r1_file_valid",
    "r2_file_valid",
    "r1_reads",
    "r2_reads",
    "r1_total_bases",
    "r2_total_bases",
    "r1_mean_read_length",
    "r2_mean_read_length",
    "r1_gc_percent",
    "r2_gc_percent",
    "pairing_result",
    "pairing_details",
    "fastqc_r1_available",
    "fastqc_r2_available",
    "fastqc_r1_pass",
    "fastqc_r1_warn",
    "fastqc_r1_fail",
    "fastqc_r2_pass",
    "fastqc_r2_warn",
    "fastqc_r2_fail",
    "qc_classification",
    "problems",
)

FASTQC_MODULE_COLUMNS = (
    "sample_id",
    "read_direction",
    "fastqc_report",
    "fastqc_path",
    "module",
    "status",
)


def validate_output_targets(output_dir: Path, overwrite: bool) -> None:
    """Refuse to clobber existing reports unless explicitly permitted."""
    output_dir = Path(output_dir)
    if output_dir.exists() and not output_dir.is_dir():
        raise OutputError(
            f"Output path exists but is not a directory: {output_dir}. "
            "Choose another --output-dir."
        )
    if not output_dir.exists():
        return

    existing = [output_dir / name for name in REPORT_FILENAMES if (output_dir / name).exists()]
    directories = [path for path in existing if path.is_dir()]
    if directories:
        raise OutputError(
            "Cannot write report files because these paths are directories: "
            + ", ".join(str(path) for path in directories)
            + ". Remove or rename them and retry."
        )
    if existing and not overwrite:
        names = ", ".join(path.name for path in existing)
        raise OutputError(
            f"Refusing to overwrite existing report file(s) in {output_dir}: {names}. "
            "Use --overwrite to replace them explicitly."
        )


def _format_float(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def _format_int(value: int | None) -> str:
    return "" if value is None else str(value)


def _valid_label(scan) -> str:
    if scan is None:
        return ""
    return "yes" if scan.valid else "no"


def _fastqc_counts(result: FastQCSideResult | None) -> tuple[int | None, int | None, int | None]:
    if result is None or not result.has_module_counts:
        return None, None, None
    return result.pass_count, result.warn_count, result.fail_count


def _summary_row(sample: SampleAudit) -> dict[str, str]:
    r1_stats = sample.r1_scan.stats if sample.r1_scan is not None else None
    r2_stats = sample.r2_scan.stats if sample.r2_scan is not None else None
    r1_pass, r1_warn, r1_fail = _fastqc_counts(sample.fastqc_r1)
    r2_pass, r2_warn, r2_fail = _fastqc_counts(sample.fastqc_r2)
    return {
        "sample_id": sample.sample_id,
        "r1_filename": sample.r1_display,
        "r2_filename": sample.r2_display,
        "r1_file_valid": _valid_label(sample.r1_scan),
        "r2_file_valid": _valid_label(sample.r2_scan),
        "r1_reads": _format_int(r1_stats.total_reads if r1_stats else None),
        "r2_reads": _format_int(r2_stats.total_reads if r2_stats else None),
        "r1_total_bases": _format_int(r1_stats.total_bases if r1_stats else None),
        "r2_total_bases": _format_int(r2_stats.total_bases if r2_stats else None),
        "r1_mean_read_length": _format_float(r1_stats.mean_length if r1_stats else None),
        "r2_mean_read_length": _format_float(r2_stats.mean_length if r2_stats else None),
        "r1_gc_percent": _format_float(r1_stats.gc_percent if r1_stats else None),
        "r2_gc_percent": _format_float(r2_stats.gc_percent if r2_stats else None),
        "pairing_result": sample.pairing_result,
        "pairing_details": sample.pairing_details,
        "fastqc_r1_available": (
            sample.fastqc_r1.availability if sample.fastqc_r1 is not None else ""
        ),
        "fastqc_r2_available": (
            sample.fastqc_r2.availability if sample.fastqc_r2 is not None else ""
        ),
        "fastqc_r1_pass": _format_int(r1_pass),
        "fastqc_r1_warn": _format_int(r1_warn),
        "fastqc_r1_fail": _format_int(r1_fail),
        "fastqc_r2_pass": _format_int(r2_pass),
        "fastqc_r2_warn": _format_int(r2_warn),
        "fastqc_r2_fail": _format_int(r2_fail),
        "qc_classification": sample.classification.status,
        "problems": " | ".join(sample.problems),
    }


def _csv_text(columns: tuple[str, ...], rows: list[dict[str, str]]) -> str:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


def render_sample_summary_csv(result: AuditResult) -> str:
    return _csv_text(SAMPLE_SUMMARY_COLUMNS, [_summary_row(sample) for sample in result.samples])


def render_fastqc_modules_csv(result: AuditResult) -> str:
    rows: list[dict[str, str]] = []
    for sample in result.samples:
        for side_result in (sample.fastqc_r1, sample.fastqc_r2):
            if (
                side_result is None
                or not side_result.has_module_counts
                or side_result.report is None
            ):
                continue
            for module in side_result.report.modules:
                rows.append(
                    {
                        "sample_id": sample.sample_id,
                        "read_direction": side_result.side.value,
                        "fastqc_report": side_result.report.report_name,
                        "fastqc_path": str(side_result.report.path),
                        "module": module.module,
                        "status": module.status,
                    }
                )
    return _csv_text(FASTQC_MODULE_COLUMNS, rows)


def _scan_to_dict(scan) -> dict[str, object] | None:
    if scan is None:
        return None
    return {
        "filename": scan.path.name,
        "path": str(scan.path),
        "valid": scan.valid,
        "errors": list(scan.errors),
        "stats": {
            "total_reads": scan.stats.total_reads,
            "total_bases": scan.stats.total_bases,
            "min_length": scan.stats.min_length,
            "max_length": scan.stats.max_length,
            "mean_length": scan.stats.mean_length,
            "gc_percent": scan.stats.gc_percent,
            "acgt_bases": scan.stats.acgt_bases,
        },
    }


def _fastqc_side_to_dict(side_result: FastQCSideResult | None) -> dict[str, object] | None:
    if side_result is None:
        return None
    report = side_result.report
    report_dict: dict[str, object] | None = None
    if report is not None:
        report_dict = {
            "report_name": report.report_name,
            "path": str(report.path),
            "available": report.available,
            "total_sequences": report.total_sequences,
            "modules": [
                {"module": module.module, "status": module.status}
                for module in report.modules
            ],
            "issues": list(report.issues),
        }
    return {
        "read_direction": side_result.side.value,
        "availability": side_result.availability,
        "pass_count": side_result.pass_count,
        "warn_count": side_result.warn_count,
        "fail_count": side_result.fail_count,
        "issues": list(side_result.issues),
        "report": report_dict,
    }


def _sample_to_dict(sample: SampleAudit) -> dict[str, object]:
    pairing = sample.pairing
    pairing_dict: dict[str, object] = {
        "result": sample.pairing_result,
        "details": sample.pairing_details,
        "checked": pairing.checked if pairing is not None else False,
        "passed": pairing.passed if pairing is not None else False,
        "mismatch_count": pairing.mismatch_count if pairing is not None else None,
        "mismatches": (
            [
                {
                    "record_number": mismatch.record_number,
                    "r1_id": mismatch.r1_id,
                    "r2_id": mismatch.r2_id,
                    "reason": mismatch.reason,
                }
                for mismatch in pairing.mismatches
            ]
            if pairing is not None
            else []
        ),
        "errors": list(pairing.errors) if pairing is not None else [],
    }
    return {
        "sample_id": sample.sample_id,
        "r1_filenames": [path.name for path in sample.r1_files],
        "r2_filenames": [path.name for path in sample.r2_files],
        "r1": _scan_to_dict(sample.r1_scan),
        "r2": _scan_to_dict(sample.r2_scan),
        "pairing": pairing_dict,
        "fastqc": {
            "r1": _fastqc_side_to_dict(sample.fastqc_r1),
            "r2": _fastqc_side_to_dict(sample.fastqc_r2),
        },
        "classification": {
            "status": sample.classification.status,
            "reasons": list(sample.classification.reasons),
        },
    }


def audit_payload(result: AuditResult) -> dict[str, object]:
    """Build the shared machine-readable payload for JSON and HTML."""
    orphaned_reads = [
        {
            "sample_id": orphan.sample_id,
            "read_direction": orphan.side.value,
            "filename": orphan.filename,
        }
        for orphan in result.discovery.orphans
    ]
    ambiguous_samples = [
        {
            "sample_id": sample.sample_id,
            "r1_filenames": [path.name for path in sample.r1_files],
            "r2_filenames": [path.name for path in sample.r2_files],
        }
        for sample in result.discovery.ambiguous_samples
    ]
    groups_ignored = [
        {
            "filename": issue.filename,
            "kind": issue.kind,
            "message": issue.message,
        }
        for issue in result.discovery.issues
    ]
    output_files = {
        "sample_summary_csv": str(Path(result.output_dir) / "sample_summary.csv"),
        "fastqc_modules_csv": str(Path(result.output_dir) / "fastqc_modules.csv"),
        "summary_json": str(Path(result.output_dir) / "summary.json"),
        "report_html": str(Path(result.output_dir) / "report.html"),
    }
    return {
        "schema_version": 1,
        "audit_timestamp": result.timestamp,
        "tool": {"name": TOOL_NAME, "version": __version__},
        "input_paths": {
            "fastq_dir": str(result.fastq_dir),
            "fastqc_dir": str(result.fastqc_dir) if result.fastqc_dir else None,
        },
        "output_paths": {
            "output_dir": str(result.output_dir),
            "files": output_files,
        },
        "configuration": result.config,
        "counts": {
            "discovered_samples": result.sample_count,
            "pass": result.pass_count,
            "warn": result.warn_count,
            "fail": result.fail_count,
            "missing_fastqc_reports": len(result.missing_reports),
            "orphaned_reads": len(orphaned_reads),
            "ambiguous_samples": len(ambiguous_samples),
            "ignored_or_unrecognized_files": len(groups_ignored),
        },
        "orphaned_reads": orphaned_reads,
        "ambiguous_samples": ambiguous_samples,
        "missing_fastqc_reports": [
            {
                "sample_id": missing.sample_id,
                "read_direction": missing.read_direction,
                "reason": missing.reason,
            }
            for missing in result.missing_reports
        ],
        "ignored_or_unrecognized_files": groups_ignored,
        "fastqc_requested": result.fastqc_requested,
        "warnings": list(result.warnings),
        "limitations": list(result.limitations),
        "samples": [_sample_to_dict(sample) for sample in result.samples],
    }


def render_summary_json(result: AuditResult) -> str:
    return json.dumps(audit_payload(result), ensure_ascii=False, indent=2) + "\n"


def _json_for_script(payload: dict[str, object]) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return (
        text.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render_html_report(result: AuditResult) -> str:
    data = _json_for_script(audit_payload(result))
    return HTML_TEMPLATE.replace("__AUDIT_DATA__", data)


def _stage_text(directory: Path, target_name: str, content: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target_name}.", suffix=".tmp", dir=directory
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def write_reports(result: AuditResult, output_dir: Path, overwrite: bool) -> dict[str, Path]:
    """Write all reports with per-file atomic replacement and final verification."""
    output_dir = Path(output_dir)
    validate_output_targets(output_dir, overwrite=overwrite)

    contents = {
        "sample_summary.csv": render_sample_summary_csv(result),
        "fastqc_modules.csv": render_fastqc_modules_csv(result),
        "summary.json": render_summary_json(result),
        "report.html": render_html_report(result),
    }

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise OutputError(
            f"Could not create output directory {output_dir}: {exc}. "
            "Choose a writable --output-dir."
        ) from exc
    if not output_dir.is_dir():
        raise OutputError(f"Output path is not a directory: {output_dir}.")

    staged: dict[str, Path] = {}
    targets: dict[str, Path] = {}
    try:
        for name, content in contents.items():
            staged[name] = _stage_text(output_dir, name, content)
            targets[name] = output_dir / name
        for name in contents:
            os.replace(staged[name], targets[name])
        for name, target in targets.items():
            if not target.is_file() or target.stat().st_size == 0:
                raise OutputError(
                    f"Report file {target} was not written completely. "
                    "Do not treat this audit as successful."
                )
    except OutputError:
        raise
    except OSError as exc:
        raise OutputError(
            f"Failed while writing report outputs to {output_dir}: {exc}. "
            "Some report files may be incomplete; do not treat this run as successful."
        ) from exc
    finally:
        for temporary in staged.values():
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    return dict(targets)
