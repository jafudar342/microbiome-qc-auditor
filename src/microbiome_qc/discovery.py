"""Deterministic discovery and pairing of FASTQ file names.

Naming rules
------------
Supported extensions are ``.fastq.gz``, ``.fq.gz``, ``.fastq`` and ``.fq``
(matched case-insensitively).  A read marker must be the final component of
the stem:

* ``sample_R1`` / ``sample_R2``
* ``sample_1`` / ``sample_2``
* ``sample_R1_001`` / ``sample_R2_001`` (any three-digit lane suffix)

Read markers and extensions are matched case-insensitively.  Sample IDs are
compared case-sensitively so that ``SampleA`` and ``samplea`` are never
silently merged.  Discovery is non-recursive.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .errors import DiscoveryError
from .models import (
    DiscoveryIssue,
    DiscoveryResult,
    FilenameMatch,
    OrphanRead,
    ReadSide,
    SampleFiles,
)

SUPPORTED_EXTENSIONS = (".fastq.gz", ".fq.gz", ".fastq", ".fq")

_MATE_SUFFIX = re.compile(
    r"^(?P<sample>.+)_(?P<marker>R(?P<read_r>[12])|(?P<read_p>[12]))(?:_\d{3})?$",
    re.IGNORECASE,
)


def split_supported_extension(filename: str) -> tuple[str, str] | None:
    """Split a supported FASTQ file name into ``(stem, extension)``.

    Returns ``None`` when the extension is not a supported FASTQ extension.
    The returned extension is lower case; the stem preserves original case.
    """
    lowered = filename.lower()
    for extension in SUPPORTED_EXTENSIONS:
        if lowered.endswith(extension) and len(filename) > len(extension):
            return filename[: -len(extension)], extension
    return None


def parse_sequence_stem(stem: str) -> FilenameMatch | None:
    """Parse a sample ID and read side from a file stem without an extension."""
    match = _MATE_SUFFIX.fullmatch(stem)
    if match is None:
        return None
    sample_id = match.group("sample")
    if not sample_id.strip():
        return None
    marker = match.group("marker").upper()
    read_number = "1" if marker.endswith("1") else "2"
    return FilenameMatch(sample_id=sample_id, side=ReadSide(f"R{read_number}"))


def parse_sequencing_filename(filename: str) -> FilenameMatch | None:
    """Parse a full FASTQ file name, if supported and correctly named."""
    split = split_supported_extension(filename)
    if split is None:
        return None
    stem, _extension = split
    return parse_sequence_stem(stem)


def _supported_naming_hint(filename: str) -> str:
    return (
        f"Unrecognized paired-end file name '{filename}': expected a read marker "
        "such as _R1/_R2, _1/_2, or _R1_001/_R2_001 before the extension. "
        "Rename the file to match its mate or move it out of the FASTQ directory."
    )


def discover_fastq_files(fastq_dir: Path) -> DiscoveryResult:
    """Scan one directory and return deterministic sample pairings.

    Raises:
        DiscoveryError: if ``fastq_dir`` is not an existing directory.
    """
    fastq_dir = Path(fastq_dir)
    if not fastq_dir.exists():
        raise DiscoveryError(
            f"FASTQ directory does not exist: {fastq_dir}. "
            "Provide the directory that contains the paired FASTQ files."
        )
    if not fastq_dir.is_dir():
        raise DiscoveryError(
            f"FASTQ path is not a directory: {fastq_dir}. "
            "Pass the directory that contains the sequencing files."
        )

    candidates: dict[str, dict[ReadSide, list[Path]]] = defaultdict(
        lambda: {ReadSide.R1: [], ReadSide.R2: []}
    )
    issues: list[DiscoveryIssue] = []
    orphans: list[OrphanRead] = []

    try:
        entries = sorted(fastq_dir.iterdir(), key=lambda item: item.name)
    except OSError as exc:
        raise DiscoveryError(f"Could not list FASTQ directory {fastq_dir}: {exc}") from exc

    for path in entries:
        if path.is_dir():
            issues.append(
                DiscoveryIssue(
                    filename=path.name,
                    kind="directory",
                    message=(
                        f"Subdirectory '{path.name}' was not scanned. "
                        "File discovery is non-recursive; run the audit on the "
                        "directory that directly contains the FASTQ files."
                    ),
                )
            )
            continue
        if not path.is_file():
            issues.append(
                DiscoveryIssue(
                    filename=path.name,
                    kind="not_a_file",
                    message=f"'{path.name}' is not a regular file and was not audited.",
                )
            )
            continue

        split = split_supported_extension(path.name)
        if split is None:
            issues.append(
                DiscoveryIssue(
                    filename=path.name,
                    kind="unsupported",
                    message=(
                        f"Ignored '{path.name}': unsupported file extension. "
                        f"Supported extensions are {', '.join(SUPPORTED_EXTENSIONS)}."
                    ),
                )
            )
            continue

        filename_match = parse_sequence_stem(split[0])
        if filename_match is None:
            issues.append(
                DiscoveryIssue(
                    filename=path.name,
                    kind="unrecognized",
                    message=_supported_naming_hint(path.name),
                )
            )
            continue

        candidates[filename_match.sample_id][filename_match.side].append(path)

    samples: list[SampleFiles] = []
    for sample_id in sorted(candidates):
        sides = candidates[sample_id]
        r1_files = tuple(sorted(sides[ReadSide.R1], key=lambda item: item.name))
        r2_files = tuple(sorted(sides[ReadSide.R2], key=lambda item: item.name))
        sample = SampleFiles(sample_id=sample_id, r1_files=r1_files, r2_files=r2_files)
        samples.append(sample)
        if sample.is_orphan:
            if r1_files:
                orphans.append(
                    OrphanRead(
                        sample_id=sample_id,
                        side=ReadSide.R1,
                        filename=r1_files[0].name,
                    )
                )
            else:
                orphans.append(
                    OrphanRead(
                        sample_id=sample_id,
                        side=ReadSide.R2,
                        filename=r2_files[0].name,
                    )
                )

    return DiscoveryResult(
        samples=tuple(samples),
        orphans=tuple(orphans),
        issues=tuple(sorted(issues, key=lambda issue: (issue.filename, issue.kind))),
    )
