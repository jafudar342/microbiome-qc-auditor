"""Deterministic sample-level PASS/WARN/FAIL classification.

Rules (in precedence order)
---------------------------
FAIL
    Any structural or pairing error: invalid/truncated FASTQ records, an empty
    or unreadable file, a missing mate, ambiguous file pairing, unequal read
    counts, or positional read-identifier mismatches.  Structural evidence
    always outranks FastQC status.

WARN
    No structural or pairing error, but at least one nonfatal QC concern:
    a FastQC module reported WARN or FAIL, a FastQC report was missing,
    invalid, ambiguous, malformed, or a FastQC-reported read count disagreed
    with the FASTQ scan.  A FastQC module FAIL does not by itself indicate
    FASTQ corruption, so it is a WARN at sample level.

PASS
    No structural/pairing errors and no FastQC concerns.  When no FastQC
    directory was supplied, FastQC is outside the audit scope and its
    availability is explicitly reported as ``not_requested``; PASS therefore
    means "no structural or pairing problem detected", not "fully validated
    by FastQC".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .models import FAIL, PASS, WARN, ClassificationDecision


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return tuple(result)


def classify_sample(
    *,
    structural_errors: Sequence[str] = (),
    fastqc_issues: Sequence[str] = (),
    fastqc_module_findings: Sequence[tuple[str, str]] = (),
) -> ClassificationDecision:
    """Classify one sample.

    Args:
        structural_errors: FASTQ and pairing failures that affect data
            integrity.  Any entry forces FAIL.
        fastqc_issues: Nonfatal FastQC evidence problems such as missing,
            invalid, or ambiguous reports, malformed summary rows, or read
            count disagreements.
        fastqc_module_findings: ``(label, status)`` pairs from actual
            FastQC modules.  Labels should include the read direction.
    """
    module_concerns = [
        f"FastQC module ({label}) reported {status}."
        for label, status in fastqc_module_findings
        if status in (WARN, FAIL)
    ]

    if structural_errors:
        reasons = _dedupe([*structural_errors, *fastqc_issues, *module_concerns])
        return ClassificationDecision(status=FAIL, reasons=reasons)

    concerns = _dedupe([*fastqc_issues, *module_concerns])
    if concerns:
        return ClassificationDecision(status=WARN, reasons=concerns)

    return ClassificationDecision(status=PASS, reasons=())
