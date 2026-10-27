"""Orchestration: discovery, scans, pairing, FastQC association, reporting."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .classification import classify_sample
from .discovery import SUPPORTED_EXTENSIONS, discover_fastq_files
from .errors import AuditError
from .fastqc import (
    FastQCCollection,
    associate_side,
    load_fastqc_reports,
)
from .models import (
    AMBIGUOUS,
    FASTQC_MISSING,
    FASTQC_NOT_APPLICABLE,
    FASTQC_NOT_ASSESSED,
    FASTQC_NOT_REQUESTED,
    MISSING_MATE,
    NOT_CHECKED,
    AuditResult,
    FastQCSideResult,
    MissingFastQCReport,
    PairingResult,
    ReadSide,
    SampleAudit,
    SampleFiles,
)
from .pairing import validate_pairing
from .fastq import scan_fastq
from .reporting import validate_output_targets, write_reports

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuditOptions:
    """Inputs and behaviour switches for one audit."""

    fastq_dir: Path
    output_dir: Path
    fastqc_dir: Path | None = None
    max_errors: int = 5
    overwrite: bool = False
    fail_on_warn: bool = False


def _dedupe(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def _ambiguous_reason(sample: SampleFiles) -> str:
    parts: list[str] = []
    for side, files in (("R1", sample.r1_files), ("R2", sample.r2_files)):
        if len(files) > 1:
            names = ", ".join(path.name for path in files)
            parts.append(f"multiple {side} candidates ({names})")
        elif not files:
            parts.append(f"no {side} candidate")
    details = "; ".join(parts)
    return (
        f"Ambiguous pairing for sample '{sample.sample_id}': {details}. "
        "Keep exactly one FASTQ file per read direction and move duplicates out "
        "of the input directory."
    )


def _orphan_reason(sample: SampleFiles) -> str:
    if sample.r1_files:
        present_side = "R1"
        missing_side = "R2"
        present_names = ", ".join(path.name for path in sample.r1_files)
    else:
        present_side = "R2"
        missing_side = "R1"
        present_names = ", ".join(path.name for path in sample.r2_files)
    return (
        f"Sample '{sample.sample_id}' is missing its {missing_side} mate "
        f"(found {present_side} file: {present_names}). Add the missing file, for "
        f"example '{sample.sample_id}_{missing_side}.fastq.gz', or move the orphan "
        "out of the FASTQ directory."
    )


def _not_assessed_sides(
    sample: SampleFiles,
    fastqc_requested: bool,
) -> tuple[FastQCSideResult, FastQCSideResult]:
    """FastQC side placeholders when FASTQ pairing itself is ambiguous."""
    results: list[FastQCSideResult] = []
    for side, files in (
        (ReadSide.R1, sample.r1_files),
        (ReadSide.R2, sample.r2_files),
    ):
        if not fastqc_requested:
            results.append(
                FastQCSideResult(side=side, availability=FASTQC_NOT_REQUESTED)
            )
        elif not files:
            results.append(
                FastQCSideResult(side=side, availability=FASTQC_NOT_APPLICABLE)
            )
        else:
            results.append(
                FastQCSideResult(
                    side=side,
                    availability=FASTQC_NOT_ASSESSED,
                    issues=(
                        f"FastQC evidence for {side.value} was not associated because "
                        f"FASTQ pairing for sample '{sample.sample_id}' is ambiguous.",
                    ),
                )
            )
    return results[0], results[1]


def _fastqc_findings(
    r1_result: FastQCSideResult,
    r2_result: FastQCSideResult,
) -> list[tuple[str, str]]:
    findings: list[tuple[str, str]] = []
    for result in (r1_result, r2_result):
        if result.has_module_counts and result.report is not None:
            for module in result.report.modules:
                findings.append((f"{result.side.value}: {module.module}", module.status))
    return findings


def _side_issues(*results: FastQCSideResult) -> list[str]:
    issues: list[str] = []
    for result in results:
        issues.extend(result.issues)
    return issues


def _read_count_concerns(
    scan,
    fastqc_result: FastQCSideResult,
) -> list[str]:
    report = fastqc_result.report
    if report is None or report.total_sequences is None:
        return []
    if scan is None or not scan.valid:
        return []
    if scan.stats.total_reads == report.total_sequences:
        return []
    return [
        f"FastQC reports {report.total_sequences} total sequences for "
        f"{fastqc_result.side.value} ({report.report_name}), but the FASTQ scan "
        f"found {scan.stats.total_reads} reads. Verify that the report belongs to "
        "the current version of this file."
    ]


def _build_sample(
    sample: SampleFiles,
    collection: FastQCCollection,
    fastqc_requested: bool,
    max_errors: int,
) -> SampleAudit:
    logger.debug("Auditing sample %s", sample.sample_id)
    structural_errors: list[str] = []
    fastqc_issues: list[str] = []
    pairing: PairingResult | None = None
    pairing_result = NOT_CHECKED
    pairing_details = ""
    r1_scan = None
    r2_scan = None

    if sample.is_ambiguous:
        reason = _ambiguous_reason(sample)
        structural_errors.append(reason)
        pairing_result = AMBIGUOUS
        pairing_details = reason
        fastqc_r1, fastqc_r2 = _not_assessed_sides(sample, fastqc_requested)
    else:
        if sample.r1 is not None:
            logger.debug("Scanning R1 %s", sample.r1)
            r1_scan = scan_fastq(sample.r1)
        if sample.r2 is not None:
            logger.debug("Scanning R2 %s", sample.r2)
            r2_scan = scan_fastq(sample.r2)

        if sample.is_orphan:
            reason = _orphan_reason(sample)
            structural_errors.append(reason)
            pairing_result = MISSING_MATE
            pairing_details = reason

        if r1_scan is not None and r1_scan.errors:
            structural_errors.extend(r1_scan.errors)
        if r2_scan is not None and r2_scan.errors:
            structural_errors.extend(r2_scan.errors)

        if sample.is_complete and r1_scan is not None and r2_scan is not None:
            if r1_scan.valid and r2_scan.valid:
                pairing = validate_pairing(
                    sample.r1,
                    sample.r2,
                    r1_scan.stats.total_reads,
                    r2_scan.stats.total_reads,
                    max_errors=max_errors,
                )
                structural_errors.extend(pairing.errors)
                pairing_result = pairing.label
                pairing_details = "; ".join(pairing.errors)
            else:
                pairing_result = NOT_CHECKED
                pairing_details = (
                    "Pairing identifier comparison was skipped because at least one "
                    "FASTQ file failed structural validation."
                )

        fastqc_r1 = associate_side(
            collection,
            sample.sample_id,
            ReadSide.R1,
            fastqc_requested=fastqc_requested,
            fastq_exists=sample.r1 is not None,
        )
        fastqc_r2 = associate_side(
            collection,
            sample.sample_id,
            ReadSide.R2,
            fastqc_requested=fastqc_requested,
            fastq_exists=sample.r2 is not None,
        )

    fastqc_issues.extend(_side_issues(fastqc_r1, fastqc_r2))
    if fastqc_requested:
        fastqc_issues.extend(_read_count_concerns(r1_scan, fastqc_r1))
        fastqc_issues.extend(_read_count_concerns(r2_scan, fastqc_r2))

    decision = classify_sample(
        structural_errors=structural_errors,
        fastqc_issues=fastqc_issues,
        fastqc_module_findings=_fastqc_findings(fastqc_r1, fastqc_r2),
    )
    return SampleAudit(
        sample_id=sample.sample_id,
        r1_files=sample.r1_files,
        r2_files=sample.r2_files,
        classification=decision,
        r1_scan=r1_scan,
        r2_scan=r2_scan,
        pairing=pairing,
        pairing_result=pairing_result,
        pairing_details=pairing_details,
        fastqc_r1=fastqc_r1,
        fastqc_r2=fastqc_r2,
    )


def _absent_side_message(sample: SampleAudit, side: ReadSide) -> str | None:
    result = sample.fastqc_r1 if side is ReadSide.R1 else sample.fastqc_r2
    if result is None or result.availability != FASTQC_MISSING:
        return None
    return "; ".join(result.issues)


def _base_limitations(fastqc_requested: bool) -> list[str]:
    limitations = [
        "FASTQ validation covers four-line structure, headers, separators, "
        "sequence/quality lengths, printable quality bytes, gzip readability, "
        "read counts, and positional paired-read identifiers. Reads are not "
        "aligned, trimmed, or subjected to contamination checks.",
        "GC percentage is (G + C) / (A + C + G + T) * 100. N and other symbols "
        "are excluded from the denominator.",
        "Discovery is non-recursive. Sample IDs are case-sensitive; read markers "
        "and file extensions are matched case-insensitively.",
        "Only *_fastqc.zip archives are parsed. Uncompressed FastQC report "
        "folders are ignored.",
        "A FastQC missing module is never converted into PASS; counts reflect "
        "only modules actually present in summary.txt.",
    ]
    if fastqc_requested:
        limitations.append(
            "FastQC evidence is limited to the supplied reports. FastQC module "
            "calculations are not recomputed, and a module FAIL is recorded as a "
            "sample-level WARN because it is not evidence of FASTQ corruption."
        )
    else:
        limitations.append(
            "FastQC was not requested. PASS classifications cover FASTQ integrity "
            "and pairing only; FastQC availability is reported as not_requested, "
            "so samples are not fully validated by FastQC."
        )
    return limitations


def build_audit(options: AuditOptions) -> AuditResult:
    """Run all analysis steps without writing report artifacts."""
    if options.max_errors < 1:
        raise AuditError("--max-errors must be at least 1.")

    discovery = discover_fastq_files(options.fastq_dir)
    if not discovery.samples:
        details = ""
        if discovery.issues:
            examples = " ".join(issue.message for issue in discovery.issues[:3])
            details = f" {examples}"
        raise AuditError(
            f"No paired-end FASTQ samples were discovered in {options.fastq_dir}. "
            "Expected names such as sample_R1.fastq.gz and sample_R2.fastq.gz. "
            "Check the directory and naming rules." + details
        )
    logger.info(
        "Discovered %d sample candidate(s) in %s",
        len(discovery.samples),
        options.fastq_dir,
    )

    fastqc_requested = options.fastqc_dir is not None
    collection = FastQCCollection(reports=(), by_key={}, issues=())
    if options.fastqc_dir is not None:
        collection = load_fastqc_reports(
            options.fastqc_dir,
            max_errors=options.max_errors,
            known_sample_ids={sample.sample_id for sample in discovery.samples},
        )
        logger.info(
            "Loaded %d FastQC archive(s) from %s",
            len(collection.reports),
            options.fastqc_dir,
        )

    samples_list: list[SampleAudit] = []
    for sample_files in discovery.samples:
        sample_audit = _build_sample(
            sample_files,
            collection,
            fastqc_requested=fastqc_requested,
            max_errors=options.max_errors,
        )
        logger.info(
            "Sample %s: %s",
            sample_audit.sample_id,
            sample_audit.classification.status,
        )
        samples_list.append(sample_audit)
    samples = tuple(samples_list)

    missing_reports: list[MissingFastQCReport] = []
    if fastqc_requested:
        for sample in samples:
            for side in (ReadSide.R1, ReadSide.R2):
                reason = _absent_side_message(sample, side)
                if reason is not None:
                    missing_reports.append(
                        MissingFastQCReport(
                            sample_id=sample.sample_id,
                            read_direction=side.value,
                            reason=reason,
                        )
                    )

    warnings: list[str] = []
    warnings.extend(issue.message for issue in discovery.issues)
    warnings.extend(collection.issues)
    if fastqc_requested and not collection.reports:
        warnings.append(
            f"No *_fastqc.zip archives were found in {options.fastqc_dir}. "
            "All samples will have missing FastQC evidence and cannot receive a "
            "FastQC-supported PASS."
        )

    limitations = _base_limitations(fastqc_requested)
    limitations.append(
        f"Detailed pairing mismatches and malformed FastQC rows are limited to "
        f"{options.max_errors} examples per file/report; totals are still counted."
    )
    issues_by_kind = ", ".join(
        sorted({issue.kind for issue in discovery.issues})
    )
    if issues_by_kind:
        limitations.append(
            "Some input files were ignored or not audited "
            f"(kinds: {issues_by_kind}). See warnings and the HTML report."
        )

    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fastq_dir = options.fastq_dir.resolve()
    fastqc_dir = options.fastqc_dir.resolve() if options.fastqc_dir is not None else None
    output_dir = options.output_dir.resolve()
    config: dict[str, object] = {
        "fastq_dir": str(fastq_dir),
        "fastqc_dir": str(fastqc_dir) if fastqc_dir is not None else None,
        "output_dir": str(output_dir),
        "fastqc_requested": fastqc_requested,
        "max_errors": options.max_errors,
        "overwrite": options.overwrite,
        "fail_on_warn": options.fail_on_warn,
        "discovery_mode": "non-recursive",
        "supported_extensions": list(SUPPORTED_EXTENSIONS),
        "gc_denominator": "A+C+G+T",
        "tool_version": __version__,
    }

    return AuditResult(
        fastq_dir=fastq_dir,
        fastqc_dir=fastqc_dir,
        output_dir=output_dir,
        timestamp=timestamp,
        config=config,
        samples=samples,
        discovery=discovery,
        fastqc_requested=fastqc_requested,
        missing_reports=tuple(missing_reports),
        warnings=_dedupe(warnings),
        limitations=tuple(limitations),
    )


def run_audit(options: AuditOptions) -> AuditResult:
    """Build an audit, atomically write all four reports, and return the result."""
    validate_output_targets(options.output_dir, overwrite=options.overwrite)
    result = build_audit(options)
    paths = write_reports(result, output_dir=options.output_dir, overwrite=options.overwrite)
    return replace(result, outputs=tuple(paths.values()))


__all__ = ["AuditOptions", "build_audit", "run_audit"]
