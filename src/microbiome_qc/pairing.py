"""Paired-end read-count and read-identifier validation."""

from __future__ import annotations

import gzip
import re
import zlib
from pathlib import Path

from .fastq import FastqFormatError, iter_raw_records
from .models import PairingMismatch, PairingResult

_TRAILING_MATE = re.compile(r"^(?P<core>.*)/(?P<read>[12])$")
_DIRECTION_PREFIX = re.compile(r"^(?P<direction>[12])(?::|$)")


def normalize_read_id(header: bytes | str) -> tuple[str, str | None]:
    """Return a comparable identifier and an optional Illumina direction.

    The leading ``@`` is removed, the first whitespace-delimited token is used,
    and a trailing ``/1`` or ``/2`` is removed.  For standard Illumina headers
    such as ``@M00176:...:1381 1:N:0:1`` the comment carries the mate direction;
    it is returned separately so both identifiers and directions can be
    compared.
    """
    if isinstance(header, bytes):
        text = header.decode("utf-8", errors="replace")
    else:
        text = header
    text = text.strip()
    if text.startswith("@"):
        text = text[1:]
    fields = text.split()
    if not fields:
        return "", None

    core = fields[0]
    direction: str | None = None
    trailing = _TRAILING_MATE.fullmatch(core)
    if trailing is not None:
        core = trailing.group("core")
        direction = trailing.group("read")

    if len(fields) > 1:
        comment = _DIRECTION_PREFIX.match(fields[1])
        if comment is not None:
            direction = comment.group("direction")
    return core, direction


def _id_display(core: str, direction: str | None) -> str:
    suffix = f" (read {direction})" if direction is not None else ""
    return f"{core or '<empty>'}{suffix}"


def validate_pairing(
    r1_path: Path,
    r2_path: Path,
    r1_reads: int,
    r2_reads: int,
    max_errors: int = 5,
) -> PairingResult:
    """Compare mate files positionally, retaining a bounded set of examples.

    Counts are supplied by the validated scans.  The walk stops when either
    iterator ends; a count difference is reported separately.  All identifier
    mismatches are counted, but only the first ``max_errors`` are retained for
    presentation.
    """
    r1_path = Path(r1_path)
    r2_path = Path(r2_path)
    retain = max(0, max_errors)
    errors: list[str] = []
    examples: list[PairingMismatch] = []
    mismatch_count = 0
    direction_problems = 0
    first_mismatch: int | None = None
    compared = 0

    if r1_reads != r2_reads:
        errors.append(
            f"R1 has {r1_reads} reads but R2 has {r2_reads} reads; "
            "paired-end mates must contain the same number of reads."
        )

    r1_iterator = iter_raw_records(r1_path)
    r2_iterator = iter_raw_records(r2_path)
    try:
        while True:
            r1_record = next(r1_iterator, None)
            r2_record = next(r2_iterator, None)
            if r1_record is None and r2_record is None:
                break
            if r1_record is None or r2_record is None:
                break

            compared += 1
            r1_core, r1_direction = normalize_read_id(r1_record.header)
            r2_core, r2_direction = normalize_read_id(r2_record.header)
            reason = ""
            if r1_core != r2_core:
                reason = "normalized read identifiers differ"
            elif r1_direction is not None and r1_direction != "1":
                reason = "R1 header indicates read 2 (direction mismatch); files may be swapped"
            elif r2_direction is not None and r2_direction != "2":
                reason = "R2 header indicates read 1 (direction mismatch); files may be swapped"

            if reason:
                mismatch_count += 1
                if reason != "normalized read identifiers differ":
                    direction_problems += 1
                if first_mismatch is None:
                    first_mismatch = r1_record.number
                if len(examples) < retain:
                    examples.append(
                        PairingMismatch(
                            record_number=r1_record.number,
                            r1_id=_id_display(r1_core, r1_direction),
                            r2_id=_id_display(r2_core, r2_direction),
                            reason=reason,
                        )
                    )
    except (FastqFormatError, OSError, EOFError, zlib.error, gzip.BadGzipFile) as exc:
        errors.append(
            f"Identifier comparison stopped after {compared} record(s): {exc}. "
            "Verify that both FASTQ files are readable and complete."
        )

    if mismatch_count:
        errors.append(
            f"R1 and R2 read identifiers or directions differ at "
            f"{mismatch_count} of {compared} compared position(s); "
            f"first mismatch at record {first_mismatch}. "
            "Verify that the files are mates in matching order."
        )
    if direction_problems:
        errors.append(
            f"{direction_problems} mismatch(es) involve read directions; the R1/R2 "
            "files may be swapped. Confirm that _R1 contains read 1 and _R2 read 2."
        )

    passed = not errors and mismatch_count == 0
    return PairingResult(
        checked=True,
        passed=passed,
        r1_reads=r1_reads,
        r2_reads=r2_reads,
        mismatch_count=mismatch_count,
        mismatches=tuple(examples),
        errors=tuple(errors),
    )
