"""Synthetic FASTQ/FastQC fixture writers and the demo dataset generator."""

from __future__ import annotations

import gzip
import zipfile
from collections.abc import Iterable, Sequence
from pathlib import Path

from .errors import DemoError

FASTQC_STANDARD_MODULES: tuple[str, ...] = (
    "Basic Statistics",
    "Per base sequence quality",
    "Per tile sequence quality",
    "Per sequence quality scores",
    "Per base sequence content",
    "Per sequence GC content",
    "Per base N content",
    "Sequence Length Distribution",
    "Sequence Duplication Levels",
    "Overrepresented sequences",
    "Adapter Content",
)


def sequence_for(index: int, length: int, gc_percent: int) -> str:
    """Build a deterministic read with approximately the requested GC share."""
    if length < 1:
        raise ValueError("length must be positive")
    gc_count = round(length * gc_percent / 100)
    gc_bases = "GC" * (gc_count // 2) + ("G" if gc_count % 2 else "")
    at_bases = "AT" * ((length - gc_count) // 2) + ("A" if (length - gc_count) % 2 else "")
    sequence = gc_bases + at_bases
    sequence = sequence[:length]
    offset = index % max(1, len(sequence))
    return sequence[offset:] + sequence[:offset]


def paired_records(
    sample_id: str,
    count: int,
    *,
    length: int = 80,
    gc_percent: int = 50,
    r2_header_override: dict[int, str] | None = None,
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """Create deterministic Illumina-style R1/R2 records for one sample."""
    r1_records: list[tuple[str, str, str]] = []
    r2_records: list[tuple[str, str, str]] = []
    overrides = r2_header_override or {}
    for index in range(1, count + 1):
        core = f"{sample_id}:1:1101:{1000 + index}:{2000 + index}"
        sequence = sequence_for(index, length, gc_percent)
        quality = "I" * length
        r1_records.append((f"{core} 1:N:0:1", sequence, quality))
        r2_core = overrides.get(index, core)
        r2_records.append((f"{r2_core} 2:N:0:1", sequence, quality))
    return r1_records, r2_records


def write_fastq(
    path: Path,
    records: Iterable[tuple[str, str, str]],
    *,
    trailing_text: str = "",
) -> None:
    """Write synthetic records, using gzip when the filename ends in ``.gz``.

    Record identifiers are supplied without the leading ``@``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    use_gzip = path.name.lower().endswith(".gz")
    opener = gzip.open if use_gzip else open
    with opener(path, "wt", encoding="ascii", newline="\n") as handle:
        for identifier, sequence, quality in records:
            handle.write(f"@{identifier}\n{sequence}\n+\n{quality}\n")
        if trailing_text:
            handle.write(trailing_text)


def write_fastqc_zip(
    path: Path,
    *,
    input_filename: str,
    module_statuses: dict[str, str],
    total_sequences: int | None = None,
    include_summary: bool = True,
    include_data: bool = True,
) -> None:
    """Write a minimal but structurally authentic FastQC ZIP archive."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    folder = path.name[:-4] if path.name.lower().endswith(".zip") else path.stem
    summary_lines = [
        f"{status.upper()}\t{module}\t{input_filename}"
        for module, status in module_statuses.items()
    ]
    status_detail = "pass" if all(
        status.upper() == "PASS" for status in module_statuses.values()
    ) else "warn"

    data_lines = [
        "##FastQC\t0.12.1",
        f">>Basic Statistics\t{status_detail}",
        "#Measure\tValue",
        f"Filename\t{input_filename}",
        "File type\tConventional base calls",
        "Encoding\tSanger / Illumina 1.9",
    ]
    if total_sequences is not None:
        data_lines.append(f"Total Sequences\t{total_sequences}")
    data_lines.extend(
        [
            "Total Bases\t0",
            "Sequences flagged as poor quality\t0",
            "Sequence length\t80",
            "%GC\t50",
            ">>END_MODULE",
            "",
        ]
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if include_summary:
            archive.writestr(f"{folder}/summary.txt", "\n".join(summary_lines) + "\n")
        if include_data:
            archive.writestr(f"{folder}/fastqc_data.txt", "\n".join(data_lines))


def _statuses(**overrides: str) -> dict[str, str]:
    statuses = {module: "PASS" for module in FASTQC_STANDARD_MODULES}
    for module, status in overrides.items():
        statuses[module.replace("_", " ")] = status
    return statuses


def _demo_readme() -> str:
    return """# Synthetic Microbiome QC Auditor demo dataset

This directory was generated locally by `microbiome-qc demo`. It contains only
synthetic reads and synthetic FastQC archives. No real subject data is present
and the expected outcomes below are fixtures, not biological findings.

## Layout

- `FASTQ/` - paired FASTQ files, with a mix of `.fastq.gz`, `.fq.gz`, and plain
  `.fq` extensions plus `_R1/_R2`, `_1/_2`, and `_R1_001/_R2_001` names.
- `FastQC/` - synthetic `*_fastqc.zip` reports consumed by the auditor.
- `QC_Report/` - created when you run the audit command below.

## Expected audit result (deterministic)

7 samples: **1 PASS, 3 WARN, 3 FAIL**. The command exits with status 1 because
three samples have structural or pairing failures.

| Sample | Files | Expected | Reason |
| --- | --- | --- | --- |
| DEMO_001 | R1/R2 | PASS | Valid pair, FastQC all PASS |
| DEMO_002 | 1/2 | WARN | Valid pair, FastQC WARN in R1 per-base quality |
| DEMO_003 | R1_001/R2_001 | WARN | Valid pair, FastQC FAIL in R2 adapter content (sample WARN) |
| DEMO_004 | R1 only | FAIL | Orphaned R1; R2 mate is missing |
| DEMO_005 | R1/R2 | FAIL | R2 read identifier differs at record 2 |
| DEMO_006 | R1/R2 | FAIL | Truncated final R2 record |
| DEMO_007 | R1/R2 | WARN | No FastQC reports supplied for this sample |

DEMO_007's two missing FastQC reports and the source of the three structural
failures are displayed explicitly in `QC_Report/report.html`, `sample_summary.csv`,
and `summary.json`.

## Run the audit

From this directory:

```bash
microbiome-qc audit --fastq-dir FASTQ --fastqc-dir FastQC --output-dir QC_Report
```

Exit code 1 is expected. To require a nonzero exit for warnings as well, add
`--fail-on-warn` (this demo still exits 1 because FAIL takes precedence over the
warning gate).
"""


def generate_demo_dataset(directory: Path, overwrite: bool = False) -> dict[str, object]:
    """Create the seven-sample demo dataset and return a summary description."""
    directory = Path(directory)
    if directory.exists():
        if not directory.is_dir():
            raise DemoError(
                f"Demo output path exists but is not a directory: {directory}. "
                "Choose a different --output-dir."
            )
        if any(directory.iterdir()) and not overwrite:
            raise DemoError(
                f"Demo output directory is not empty: {directory}. "
                "Choose an empty directory or pass --overwrite."
            )
    try:
        fastq_dir = directory / "FASTQ"
        fastqc_dir = directory / "FastQC"
        fastq_dir.mkdir(parents=True, exist_ok=True)
        fastqc_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DemoError(f"Could not create demo directories in {directory}: {exc}") from exc

    def write_pair(
        sample: str,
        count: int,
        r1_name: str,
        r2_name: str,
        *,
        gc_percent: int = 50,
        r2_header_override: dict[int, str] | None = None,
        truncate_r2: bool = False,
    ) -> tuple[int, int]:
        r1_records, r2_records = paired_records(
            sample,
            count,
            gc_percent=gc_percent,
            r2_header_override=r2_header_override,
        )
        write_fastq(fastq_dir / r1_name, r1_records)
        if truncate_r2:
            complete = r2_records[:-1]
            last_identifier = r2_records[-1][0]
            last_sequence = r2_records[-1][1]
            trailing = f"@{last_identifier}\n{last_sequence}\n+\n"
            write_fastq(fastq_dir / r2_name, complete, trailing_text=trailing)
        else:
            write_fastq(fastq_dir / r2_name, r2_records)
        return len(r1_records), len(r2_records)

    reports: list[tuple[str, str, int, dict[str, str]]] = []

    counts_001 = write_pair("DEMO_001", 120, "DEMO_001_R1.fastq.gz", "DEMO_001_R2.fq.gz", gc_percent=52)
    reports.extend(
        [
            ("DEMO_001_R1_fastqc.zip", "DEMO_001_R1.fastq.gz", counts_001[0], _statuses()),
            ("DEMO_001_R2_fastqc.zip", "DEMO_001_R2.fq.gz", counts_001[1], _statuses()),
        ]
    )

    counts_002 = write_pair("DEMO_002", 90, "DEMO_002_1.fastq.gz", "DEMO_002_2.fastq.gz", gc_percent=47)
    warn_quality = _statuses(Per_base_sequence_quality="WARN")
    reports.extend(
        [
            ("DEMO_002_1_fastqc.zip", "DEMO_002_1.fastq.gz", counts_002[0], warn_quality),
            ("DEMO_002_2_fastqc.zip", "DEMO_002_2.fastq.gz", counts_002[1], _statuses()),
        ]
    )

    counts_003 = write_pair(
        "DEMO_003",
        80,
        "DEMO_003_R1_001.fq",
        "DEMO_003_R2_001.fq",
        gc_percent=55,
    )
    fail_adapter = _statuses(Adapter_Content="FAIL")
    reports.extend(
        [
            ("DEMO_003_R1_001_fastqc.zip", "DEMO_003_R1_001.fq", counts_003[0], _statuses()),
            ("DEMO_003_R2_001_fastqc.zip", "DEMO_003_R2_001.fq", counts_003[1], fail_adapter),
        ]
    )

    counts_004 = write_pair("DEMO_004", 60, "DEMO_004_R1.fastq.gz", "DEMO_004_R2.fastq.gz", gc_percent=49)
    (fastq_dir / "DEMO_004_R2.fastq.gz").unlink()
    reports.append(
        ("DEMO_004_R1_fastqc.zip", "DEMO_004_R1.fastq.gz", counts_004[0], _statuses())
    )

    counts_005 = write_pair(
        "DEMO_005",
        75,
        "DEMO_005_R1.fastq.gz",
        "DEMO_005_R2.fastq.gz",
        gc_percent=51,
        r2_header_override={2: "DEMO_005:1:9999:9999:9999"},
    )
    reports.extend(
        [
            ("DEMO_005_R1_fastqc.zip", "DEMO_005_R1.fastq.gz", counts_005[0], _statuses()),
            ("DEMO_005_R2_fastqc.zip", "DEMO_005_R2.fastq.gz", counts_005[1], _statuses()),
        ]
    )

    counts_006 = write_pair(
        "DEMO_006",
        70,
        "DEMO_006_R1.fastq.gz",
        "DEMO_006_R2.fastq.gz",
        gc_percent=45,
        truncate_r2=True,
    )
    reports.extend(
        [
            ("DEMO_006_R1_fastqc.zip", "DEMO_006_R1.fastq.gz", counts_006[0], _statuses()),
            ("DEMO_006_R2_fastqc.zip", "DEMO_006_R2.fastq.gz", counts_006[1], _statuses()),
        ]
    )

    write_pair("DEMO_007", 50, "DEMO_007_R1.fastq.gz", "DEMO_007_R2.fastq.gz", gc_percent=53)

    for report_name, input_name, total_sequences, statuses in reports:
        write_fastqc_zip(
            fastqc_dir / report_name,
            input_filename=input_name,
            module_statuses=statuses,
            total_sequences=total_sequences,
        )

    (directory / "README.md").write_text(_demo_readme(), encoding="utf-8")

    return {
        "directory": str(directory),
        "fastq_dir": str(fastq_dir),
        "fastqc_dir": str(fastqc_dir),
        "samples": 7,
        "expected_counts": {"pass": 1, "warn": 3, "fail": 3},
    }


__all__: Sequence[str] = (
    "FASTQC_STANDARD_MODULES",
    "generate_demo_dataset",
    "paired_records",
    "sequence_for",
    "write_fastq",
    "write_fastqc_zip",
)
