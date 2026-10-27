"""Streaming FASTQ validation and composition statistics.

Files are always read as binary streams one record at a time.  Compressed
files are opened with :mod:`gzip`; no sequence data is retained in memory.
A structural failure invalidates the whole file and stops the scan because
four-line record boundaries cannot be trusted after desynchronisation.
"""

from __future__ import annotations

import gzip
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from .models import FastqScanResult, FastqStats


@dataclass(frozen=True)
class RawRecord:
    """Four raw, newline-stripped lines from a FASTQ file."""

    number: int
    header: bytes
    sequence: bytes
    separator: bytes
    quality: bytes


class FastqFormatError(Exception):
    """A structural FASTQ problem with an associated record number."""

    def __init__(self, record_number: int, message: str) -> None:
        super().__init__(f"record {record_number}: {message}")
        self.record_number = record_number
        self.message = message


def _strip_eol(line: bytes) -> bytes:
    if line.endswith(b"\n"):
        line = line[:-1]
    if line.endswith(b"\r"):
        line = line[:-1]
    return line


def _short(value: bytes, limit: int = 48) -> str:
    text = value.decode("utf-8", errors="backslashreplace")
    if len(text) > limit:
        return text[:limit] + "..."
    return text


def _open_binary(path: Path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rb")
    return open(path, "rb")


def iter_raw_records(path: Path) -> Iterator[RawRecord]:
    """Yield four-line records without validating their contents.

    This is the shared low-level reader for scanning and pairing.  It raises
    :class:`FastqFormatError` when the final record is incomplete and lets
    decompression or OS errors propagate to the caller.
    """
    with _open_binary(path) as handle:
        number = 1
        while True:
            header = handle.readline()
            if header == b"":
                return
            sequence = handle.readline()
            if sequence == b"":
                raise FastqFormatError(
                    number,
                    "file ends after the header line; the record is truncated. "
                    "Restore or regenerate the file.",
                )
            separator = handle.readline()
            if separator == b"":
                raise FastqFormatError(
                    number,
                    "file ends before the '+' separator; the record is truncated. "
                    "Restore or regenerate the file.",
                )
            quality = handle.readline()
            if quality == b"":
                raise FastqFormatError(
                    number,
                    "file ends before the quality line; the record is truncated. "
                    "Restore or regenerate the file.",
                )
            yield RawRecord(
                number=number,
                header=_strip_eol(header),
                sequence=_strip_eol(sequence),
                separator=_strip_eol(separator),
                quality=_strip_eol(quality),
            )
            number += 1


def _invalid_quality_byte(quality: bytes) -> tuple[int, int] | None:
    for index, byte in enumerate(quality):
        if byte < 33 or byte > 126:
            return index, byte
    return None


def _validate_record(record: RawRecord) -> None:
    if not record.header.startswith(b"@"):
        raise FastqFormatError(
            record.number,
            f"header must start with '@' but starts with '{_short(record.header)}'. "
            "Repair or regenerate the FASTQ file.",
        )
    if not record.header[1:].strip():
        raise FastqFormatError(
            record.number,
            "header line has no read identifier after '@'. "
            "Regenerate the FASTQ file with valid headers.",
        )
    if not record.separator.startswith(b"+"):
        raise FastqFormatError(
            record.number,
            f"separator line must start with '+' but is '{_short(record.separator)}'. "
            "Repair or regenerate the FASTQ file.",
        )
    if not record.sequence:
        raise FastqFormatError(
            record.number,
            "sequence line is empty. Empty reads are not valid FASTQ records.",
        )
    if len(record.sequence) != len(record.quality):
        raise FastqFormatError(
            record.number,
            "sequence and quality lengths differ "
            f"({len(record.sequence)} vs {len(record.quality)}). "
            "The record is malformed; repair or regenerate the FASTQ file.",
        )
    invalid = _invalid_quality_byte(record.quality)
    if invalid is not None:
        position, byte = invalid
        raise FastqFormatError(
            record.number,
            f"quality contains invalid byte 0x{byte:02x} at position {position + 1}; "
            "FASTQ quality characters must be printable ASCII from '!' to '~'.",
        )


def describe_read_failure(path: Path, exc: BaseException) -> str:
    if isinstance(exc, EOFError) or isinstance(exc, gzip.BadGzipFile):
        detail = str(exc) or exc.__class__.__name__
        return (
            f"{path.name}: invalid or truncated gzip data ({detail}). "
            "Regenerate or decompress the file."
        )
    if isinstance(exc, zlib.error):
        return (
            f"{path.name}: gzip decompression failed ({exc}). "
            "Regenerate or decompress the file."
        )
    if isinstance(exc, OSError):
        return f"{path.name}: could not be read ({exc}). Check permissions and the file path."
    return f"{path.name}: could not be read ({exc})."


def scan_fastq(path: Path) -> FastqScanResult:
    """Validate one FASTQ file and compute streaming statistics.

    A single structural error is retained and scanning stops.  This avoids
    floods of downstream, misaligned error messages.  Statistics on an invalid
    file are partial and the sample is never classified as PASS.
    """
    path = Path(path)
    total_reads = 0
    total_bases = 0
    min_length: int | None = None
    max_length = 0
    acgt_bases = 0
    gc_bases = 0
    errors: list[str] = []

    try:
        for record in iter_raw_records(path):
            _validate_record(record)
            length = len(record.sequence)
            upper = record.sequence.upper()
            a_count = upper.count(b"A")
            c_count = upper.count(b"C")
            g_count = upper.count(b"G")
            t_count = upper.count(b"T")

            total_reads += 1
            total_bases += length
            min_length = length if min_length is None else min(min_length, length)
            max_length = max(max_length, length)
            acgt_bases += a_count + c_count + g_count + t_count
            gc_bases += g_count + c_count
    except FastqFormatError as exc:
        errors.append(f"{path.name}: {exc}")
    except (OSError, EOFError, zlib.error, gzip.BadGzipFile) as exc:
        errors.append(describe_read_failure(path, exc))

    if not errors and total_reads == 0:
        errors.append(
            f"{path.name}: contains no FASTQ records. "
            "An empty file cannot be audited; regenerate it or remove it from the dataset."
        )

    mean_length = round(total_bases / total_reads, 2) if total_reads else 0.0
    gc_percent = round((gc_bases / acgt_bases) * 100, 2) if acgt_bases else 0.0
    stats = FastqStats(
        total_reads=total_reads,
        total_bases=total_bases,
        min_length=min_length or 0,
        max_length=max_length,
        mean_length=mean_length,
        gc_percent=gc_percent,
        acgt_bases=acgt_bases,
    )
    return FastqScanResult(
        path=path,
        stats=stats,
        errors=tuple(errors),
        valid=not errors,
    )
