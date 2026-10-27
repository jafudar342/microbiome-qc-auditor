"""Independent fixture writers used by the unittest suite."""

from __future__ import annotations

import gzip
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from microbiome_qc.discovery import split_supported_extension

STANDARD_MODULES = (
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


def statuses(**overrides: str) -> dict[str, str]:
    result = {module: "PASS" for module in STANDARD_MODULES}
    for module, status in overrides.items():
        result[module.replace("_", " ")] = status
    return result


def write_raw(path: Path, data: bytes, compressed: bool | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if compressed is None:
        compressed = path.name.lower().endswith(".gz")
    if compressed:
        with gzip.open(path, "wb") as handle:
            handle.write(data)
    else:
        path.write_bytes(data)


def fastq_bytes(records: Sequence[tuple[str, str, str]], separator: str = "+") -> bytes:
    chunks: list[bytes] = []
    for header, sequence, quality in records:
        chunks.extend(
            [
                header.encode("utf-8"),
                b"\n",
                sequence.encode("ascii"),
                b"\n",
                separator.encode("ascii"),
                b"\n",
                quality.encode("ascii"),
                b"\n",
            ]
        )
    return b"".join(chunks)


def write_fastq(
    path: Path,
    records: Sequence[tuple[str, str, str]],
    compressed: bool | None = None,
    separator: str = "+",
    trailing: bytes = b"",
) -> None:
    write_raw(path, fastq_bytes(records, separator=separator) + trailing, compressed)


def write_fastqc_zip(
    path: Path,
    *,
    status_rows: Sequence[tuple[str, str, str]] | None = None,
    summary_text: str | None = None,
    data_text: str | None = None,
    include_summary: bool = True,
    include_data: bool = True,
    input_filename: str | None = None,
    total_sequences: int | None = None,
    folder: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if summary_text is None:
        rows = status_rows or tuple(
            ("PASS", module, input_filename or "reads_R1.fastq.gz")
            for module in STANDARD_MODULES
        )
        summary_text = "\n".join("\t".join(row) for row in rows) + "\n"
    if data_text is None:
        lines = [
            "##FastQC\t0.12.1",
            ">>Basic Statistics\tpass",
            "#Measure\tValue",
            f"Filename\t{input_filename or 'reads_R1.fastq.gz'}",
            "File type\tConventional base calls",
            "Encoding\tSanger / Illumina 1.9",
        ]
        if total_sequences is not None:
            lines.append(f"Total Sequences\t{total_sequences}")
        lines.extend(["Sequence length\t4", "%GC\t50", ">>END_MODULE", ""])
        data_text = "\n".join(lines)

    inner = folder or (path.name[:-4] if path.name.lower().endswith(".zip") else path.stem)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if include_summary:
            archive.writestr(f"{inner}/summary.txt", summary_text)
        if include_data:
            archive.writestr(f"{inner}/fastqc_data.txt", data_text)


def write_fastqc_for_fastq(
    fastqc_dir: Path,
    fastq_filename: str,
    *,
    status_map: Mapping[str, str] | None = None,
    total_sequences: int | None = None,
    report_name: str | None = None,
    **kwargs,
) -> Path:
    split = split_supported_extension(fastq_filename)
    if split is None:
        raise ValueError(f"unsupported fixture FASTQ name: {fastq_filename}")
    stem = split[0]
    name = report_name or f"{stem}_fastqc.zip"
    status_map = status_map or statuses()
    path = fastqc_dir / name
    write_fastqc_zip(
        path,
        input_filename=fastq_filename,
        status_rows=tuple(
            (status, module, fastq_filename) for module, status in status_map.items()
        ),
        total_sequences=total_sequences,
        **kwargs,
    )
    return path


def simple_pair(
    directory: Path,
    sample: str = "SAMPLE",
    count: int = 3,
    *,
    compress: bool = False,
    sequence: str = "ACGT",
) -> tuple[Path, Path]:
    suffix = ".fastq.gz" if compress else ".fastq"
    r1 = directory / f"{sample}_R1{suffix}"
    r2 = directory / f"{sample}_R2{suffix}"
    r1_records = [
        (f"@read{index}/1", sequence, "I" * len(sequence))
        for index in range(1, count + 1)
    ]
    r2_records = [
        (f"@read{index}/2", sequence, "I" * len(sequence))
        for index in range(1, count + 1)
    ]
    write_fastq(r1, r1_records)
    write_fastq(r2, r2_records)
    return r1, r2
