"""Immutable data structures used by the audit pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

PASS = "PASS"
WARN = "WARN"
FAIL = "FAIL"

NOT_CHECKED = "NOT_CHECKED"
MISSING_MATE = "MISSING_MATE"
AMBIGUOUS = "AMBIGUOUS"

# FastQC side availability values.  They intentionally separate "we were not
# asked to look" and "the file is absent" from "the report passed".
FASTQC_AVAILABLE = "available"
FASTQC_MISSING = "missing"
FASTQC_INVALID = "invalid"
FASTQC_AMBIGUOUS = "ambiguous"
FASTQC_NOT_REQUESTED = "not_requested"
FASTQC_NOT_APPLICABLE = "not_applicable"
FASTQC_NOT_ASSESSED = "not_assessed"


class ReadSide(str, Enum):
    """A paired-end read direction."""

    R1 = "R1"
    R2 = "R2"


@dataclass(frozen=True)
class FilenameMatch:
    """A sample identifier and read side parsed from a file name."""

    sample_id: str
    side: ReadSide


@dataclass(frozen=True)
class OrphanRead:
    """A discovered FASTQ file whose mate is absent."""

    sample_id: str
    side: ReadSide
    filename: str


@dataclass(frozen=True)
class DiscoveryIssue:
    """A file in the FASTQ directory that was not audited."""

    filename: str
    kind: str
    message: str


@dataclass(frozen=True)
class SampleFiles:
    """All candidate input files that normalise to one sample identifier."""

    sample_id: str
    r1_files: tuple[Path, ...] = ()
    r2_files: tuple[Path, ...] = ()

    @property
    def r1(self) -> Path | None:
        """The unique R1 path, or ``None`` when absent or ambiguous."""
        return self.r1_files[0] if len(self.r1_files) == 1 else None

    @property
    def r2(self) -> Path | None:
        """The unique R2 path, or ``None`` when absent or ambiguous."""
        return self.r2_files[0] if len(self.r2_files) == 1 else None

    @property
    def is_ambiguous(self) -> bool:
        """True when more than one candidate exists for either read side."""
        return len(self.r1_files) > 1 or len(self.r2_files) > 1

    @property
    def is_complete(self) -> bool:
        """True when exactly one R1 and one R2 file are present."""
        return len(self.r1_files) == 1 and len(self.r2_files) == 1

    @property
    def is_orphan(self) -> bool:
        """True when exactly one read side is absent and pairing is unambiguous."""
        if self.is_ambiguous:
            return False
        return (len(self.r1_files) == 0) != (len(self.r2_files) == 0)

    @property
    def all_files(self) -> tuple[Path, ...]:
        """Every candidate file in deterministic order."""
        return tuple(sorted(self.r1_files + self.r2_files, key=lambda item: item.name))

    @property
    def r1_display(self) -> str:
        """Semicolon-joined R1 file names for tabular reports."""
        return "; ".join(path.name for path in sorted(self.r1_files, key=lambda p: p.name))

    @property
    def r2_display(self) -> str:
        """Semicolon-joined R2 file names for tabular reports."""
        return "; ".join(path.name for path in sorted(self.r2_files, key=lambda p: p.name))


@dataclass(frozen=True)
class DiscoveryResult:
    """Outcome of scanning and normalising a FASTQ directory."""

    samples: tuple[SampleFiles, ...]
    orphans: tuple[OrphanRead, ...]
    issues: tuple[DiscoveryIssue, ...]

    @property
    def ambiguous_samples(self) -> tuple[SampleFiles, ...]:
        """Samples with duplicate candidate files for one or both read sides."""
        return tuple(sample for sample in self.samples if sample.is_ambiguous)


@dataclass(frozen=True)
class FastqStats:
    """Streaming statistics for one FASTQ file.

    GC percentage is ``(G + C) / (A + C + G + T) * 100``.  Bases other than
    A, C, G, and T (for example ``N``) are excluded from the denominator.
    """

    total_reads: int = 0
    total_bases: int = 0
    min_length: int = 0
    max_length: int = 0
    mean_length: float = 0.0
    gc_percent: float = 0.0
    acgt_bases: int = 0


@dataclass(frozen=True)
class FastqScanResult:
    """Validation result for one FASTQ file.

    Statistics can be partial when ``valid`` is false: only records read before
    the first structural failure are counted.
    """

    path: Path
    stats: FastqStats
    errors: tuple[str, ...] = ()
    valid: bool = True


@dataclass(frozen=True)
class PairingMismatch:
    """One positional R1/R2 identifier disagreement."""

    record_number: int
    r1_id: str
    r2_id: str
    reason: str


@dataclass(frozen=True)
class PairingResult:
    """Result of comparing two FASTQ mates."""

    checked: bool
    passed: bool
    r1_reads: int = 0
    r2_reads: int = 0
    mismatch_count: int = 0
    mismatches: tuple[PairingMismatch, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Compact status used in CSV output and the HTML report."""
        if not self.checked:
            return NOT_CHECKED
        return PASS if self.passed else FAIL


@dataclass(frozen=True)
class FastQCModule:
    """One module status extracted from a FastQC ``summary.txt``."""

    module: str
    status: str


@dataclass(frozen=True)
class FastQCReport:
    """Parsed representation of one FastQC ZIP archive."""

    path: Path
    report_name: str
    sample_id: str | None
    side: ReadSide | None
    modules: tuple[FastQCModule, ...] = ()
    total_sequences: int | None = None
    available: bool = False
    issues: tuple[str, ...] = ()

    @property
    def pass_count(self) -> int:
        return sum(1 for module in self.modules if module.status == PASS)

    @property
    def warn_count(self) -> int:
        return sum(1 for module in self.modules if module.status == WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for module in self.modules if module.status == FAIL)


@dataclass(frozen=True)
class FastQCSideResult:
    """Association of one sample read side with FastQC evidence."""

    side: ReadSide
    availability: str
    report: FastQCReport | None = None
    issues: tuple[str, ...] = ()

    @property
    def has_module_counts(self) -> bool:
        return self.availability == FASTQC_AVAILABLE and self.report is not None

    @property
    def pass_count(self) -> int | None:
        return self.report.pass_count if self.has_module_counts else None

    @property
    def warn_count(self) -> int | None:
        return self.report.warn_count if self.has_module_counts else None

    @property
    def fail_count(self) -> int | None:
        return self.report.fail_count if self.has_module_counts else None


@dataclass(frozen=True)
class ClassificationDecision:
    """Deterministic sample-level classification and its evidence."""

    status: str
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SampleAudit:
    """Everything the auditor learned about one sample."""

    sample_id: str
    r1_files: tuple[Path, ...]
    r2_files: tuple[Path, ...]
    classification: ClassificationDecision
    r1_scan: FastqScanResult | None = None
    r2_scan: FastqScanResult | None = None
    pairing: PairingResult | None = None
    pairing_result: str = NOT_CHECKED
    pairing_details: str = ""
    fastqc_r1: FastQCSideResult | None = None
    fastqc_r2: FastQCSideResult | None = None

    @property
    def problems(self) -> tuple[str, ...]:
        """Concise, user-facing reasons behind the classification."""
        return self.classification.reasons

    @property
    def r1_display(self) -> str:
        return "; ".join(path.name for path in sorted(self.r1_files, key=lambda p: p.name))

    @property
    def r2_display(self) -> str:
        return "; ".join(path.name for path in sorted(self.r2_files, key=lambda p: p.name))


@dataclass(frozen=True)
class MissingFastQCReport:
    """A FastQC report that was expected because a FastQC directory was supplied."""

    sample_id: str
    read_direction: str
    reason: str


@dataclass(frozen=True)
class AuditResult:
    """Complete, presentation-independent result of an audit."""

    fastq_dir: Path
    fastqc_dir: Path | None
    output_dir: Path
    timestamp: str
    config: dict[str, object]
    samples: tuple[SampleAudit, ...]
    discovery: DiscoveryResult
    fastqc_requested: bool
    missing_reports: tuple[MissingFastQCReport, ...] = ()
    warnings: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    outputs: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def pass_count(self) -> int:
        return sum(1 for sample in self.samples if sample.classification.status == PASS)

    @property
    def warn_count(self) -> int:
        return sum(1 for sample in self.samples if sample.classification.status == WARN)

    @property
    def fail_count(self) -> int:
        return sum(1 for sample in self.samples if sample.classification.status == FAIL)
