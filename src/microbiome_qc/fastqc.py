"""FastQC ZIP report parsing and sample/read-direction association.

Only archives named ``*_fastqc.zip`` are considered.  Archives are read in
place with :mod:`zipfile`; nothing is extracted or executed.  Module statuses
come from the real ``summary.txt`` rows.  A missing module is never invented
as PASS, and a missing report is kept distinct from a report that passed.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .discovery import parse_sequence_stem, parse_sequencing_filename
from .errors import FastQCError
from .models import (
    FAIL,
    FASTQC_AMBIGUOUS,
    FASTQC_AVAILABLE,
    FASTQC_INVALID,
    FASTQC_MISSING,
    FASTQC_NOT_APPLICABLE,
    FASTQC_NOT_REQUESTED,
    PASS,
    WARN,
    FastQCModule,
    FastQCReport,
    FastQCSideResult,
    ReadSide,
)

SUMMARY_MAX_BYTES = 5 * 1024 * 1024
VALID_STATUSES = frozenset({PASS, WARN, FAIL})


@dataclass(frozen=True)
class FastQCCollection:
    """Parsed reports indexed by ``(sample_id, read side)``."""

    reports: tuple[FastQCReport, ...]
    by_key: dict[tuple[str, ReadSide], tuple[FastQCReport, ...]]
    issues: tuple[str, ...]


def fastqc_report_stem(path: Path) -> str | None:
    """Return the original input stem for an archive such as ``x_fastqc.zip``.

    Returns ``None`` when the archive name does not end in ``_fastqc.zip``.
    """
    name = Path(path).name
    suffix = "_fastqc.zip"
    if len(name) <= len(suffix) or not name.lower().endswith(suffix):
        return None
    return name[: -len(suffix)]


def _identity_from_stem(stem: str | None):
    if not stem:
        return None
    match = parse_sequence_stem(stem)
    if match is None:
        match = parse_sequencing_filename(Path(stem).name)
    return match


def _identity_from_internal(filename: str | None):
    if not filename:
        return None
    basename = Path(filename.replace("\\", "/")).name
    return parse_sequencing_filename(basename)


def _find_entries(archive: zipfile.ZipFile, basename: str) -> list[zipfile.ZipInfo]:
    matches = [
        info
        for info in archive.infolist()
        if not info.is_dir()
        and Path(info.filename.replace("\\", "/")).name == basename
    ]
    return sorted(matches, key=lambda info: info.filename)


def _parse_summary(
    text: str,
    report_name: str,
    max_errors: int,
) -> tuple[list[FastQCModule], list[str], str | None]:
    modules: list[FastQCModule] = []
    issues: list[str] = []
    seen: set[str] = set()
    internal_filename: str | None = None
    malformed = 0
    reported = 0
    limit = max(0, max_errors)

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        fields = line.split("\t")
        problem = ""
        if len(fields) != 3:
            problem = f"expected 3 tab-separated fields, found {len(fields)}"
        else:
            status, module, filename = (field.strip() for field in fields)
            if status.upper() not in VALID_STATUSES:
                problem = f"unrecognized status '{status}'"
            elif not module:
                problem = "module name is empty"
            elif not filename:
                problem = "input filename is empty"
            else:
                normalized_status = status.upper()
                if internal_filename is None:
                    internal_filename = filename
                if module in seen:
                    problem = f"duplicate module row for '{module}'"
                else:
                    seen.add(module)
                    modules.append(FastQCModule(module=module, status=normalized_status))
                    continue

        malformed += 1
        if reported < limit:
            issues.append(
                f"{report_name}: malformed summary.txt row {line_number}: {problem}. "
                "Re-run FastQC to regenerate a complete report."
            )
            reported += 1

    if malformed > reported:
        issues.append(
            f"{report_name}: {malformed - reported} additional malformed summary.txt "
            "row(s) were omitted. Re-run FastQC to regenerate the report."
        )
    if not modules:
        issues.append(
            f"{report_name}: summary.txt contains no valid FastQC module rows. "
            "The report cannot be used for classification."
        )
    return modules, issues, internal_filename


def _parse_basic_statistics(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    report_name: str,
) -> tuple[int | None, str | None, list[str]]:
    issues: list[str] = []
    total_sequences: int | None = None
    input_filename: str | None = None
    in_section = False
    saw_section = False

    try:
        with archive.open(entry) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
            for line in text:
                stripped = line.rstrip("\r\n")
                if stripped.startswith(">>Basic Statistics"):
                    in_section = True
                    saw_section = True
                    continue
                if not in_section:
                    if stripped.startswith(">>") and saw_section:
                        break
                    continue
                if stripped.startswith(">>END_MODULE"):
                    break
                if "\t" not in stripped:
                    continue
                key, value = stripped.split("\t", 1)
                key = key.strip()
                value = value.strip()
                if key == "Filename" and value:
                    input_filename = value
                elif key == "Total Sequences" and value:
                    try:
                        total_sequences = int(value)
                    except ValueError:
                        issues.append(
                            f"{report_name}: fastqc_data.txt has a non-integer "
                            f"'Total Sequences' value '{value}'."
                        )
    except (KeyError, OSError, RuntimeError, zipfile.BadZipFile, EOFError) as exc:
        issues.append(
            f"{report_name}: could not read fastqc_data.txt ({exc}). "
            "Re-run FastQC to regenerate the archive."
        )

    if not saw_section:
        issues.append(
            f"{report_name}: fastqc_data.txt has no Basic Statistics section; "
            "FastQC read counts are unavailable."
        )
    elif total_sequences is None and not any("Total Sequences" in issue for issue in issues):
        issues.append(
            f"{report_name}: Basic Statistics does not report a numeric read count."
        )
    return total_sequences, input_filename, issues


def parse_fastqc_report(path: Path, max_errors: int = 5) -> FastQCReport:
    """Parse one FastQC ZIP archive without extracting it.

    The report is marked unavailable when the ZIP, ``summary.txt``, or all
    valid summary rows are unusable.  Individual report defects are retained
    as issues so the sample can be warned about without being called a
    structural FASTQ failure.
    """
    path = Path(path)
    report_name = path.name
    stem = fastqc_report_stem(path)
    archive_identity = _identity_from_stem(stem)
    modules: list[FastQCModule] = []
    issues: list[str] = []
    total_sequences: int | None = None
    summary_filename: str | None = None
    basic_filename: str | None = None
    zip_readable = False

    try:
        with zipfile.ZipFile(path) as archive:
            zip_readable = True
            summary_entries = _find_entries(archive, "summary.txt")
            if not summary_entries:
                issues.append(
                    f"{report_name}: archive is missing summary.txt. "
                    "Re-run FastQC to regenerate the report."
                )
            else:
                if len(summary_entries) > 1:
                    issues.append(
                        f"{report_name}: archive contains multiple summary.txt files; "
                        f"using '{summary_entries[0].filename}'."
                    )
                entry = summary_entries[0]
                try:
                    with archive.open(entry) as raw:
                        data = raw.read(SUMMARY_MAX_BYTES + 1)
                    if len(data) > SUMMARY_MAX_BYTES:
                        issues.append(
                            f"{report_name}: summary.txt is unexpectedly large and "
                            "was not parsed. Re-run FastQC."
                        )
                    else:
                        text = data.decode("utf-8-sig", errors="replace")
                        parsed_modules, parse_issues, summary_filename = _parse_summary(
                            text, report_name, max_errors
                        )
                        modules.extend(parsed_modules)
                        issues.extend(parse_issues)
                except (KeyError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    issues.append(
                        f"{report_name}: could not read summary.txt ({exc}). "
                        "Re-run FastQC to regenerate the archive."
                    )

            data_entries = _find_entries(archive, "fastqc_data.txt")
            if not data_entries:
                issues.append(
                    f"{report_name}: archive is missing fastqc_data.txt; "
                    "FastQC read counts are unavailable."
                )
            else:
                if len(data_entries) > 1:
                    issues.append(
                        f"{report_name}: archive contains multiple fastqc_data.txt files; "
                        f"using '{data_entries[0].filename}'."
                    )
                total_sequences, basic_filename, basic_issues = _parse_basic_statistics(
                    archive, data_entries[0], report_name
                )
                issues.extend(basic_issues)
    except (zipfile.BadZipFile, OSError, RuntimeError) as exc:
        issues.append(
            f"{report_name}: not a readable FastQC ZIP archive ({exc}). "
            "Re-run FastQC or remove this file from the FastQC directory."
        )

    if summary_filename and basic_filename:
        summary_base = Path(summary_filename.replace("\\", "/")).name
        basic_base = Path(basic_filename.replace("\\", "/")).name
        if summary_base != basic_base:
            issues.append(
                f"{report_name}: summary.txt and fastqc_data.txt reference different "
                f"input files ('{summary_base}' vs '{basic_base}')."
            )

    internal_filename = summary_filename or basic_filename
    internal_identity = _identity_from_internal(internal_filename)
    identity = archive_identity or internal_identity
    if archive_identity and internal_identity:
        if (
            archive_identity.sample_id != internal_identity.sample_id
            or archive_identity.side != internal_identity.side
        ):
            issues.append(
                f"{report_name}: archive name suggests sample "
                f"'{archive_identity.sample_id}' ({archive_identity.side.value}) but "
                f"the report references '{internal_identity.sample_id}' "
                f"({internal_identity.side.value}); using the archive name for association."
            )

    if identity is None:
        issues.append(
            f"{report_name}: could not determine the sample and read direction. "
            "Rename the archive to include _R1/_R2 (for example sample_R1_fastqc.zip) "
            "or ensure summary.txt names the original FASTQ file."
        )

    if not zip_readable:
        modules = []

    modules.sort(key=lambda module: (module.module.casefold(), module.module))
    available = zip_readable and bool(modules)
    return FastQCReport(
        path=path,
        report_name=report_name,
        sample_id=identity.sample_id if identity else None,
        side=identity.side if identity else None,
        modules=tuple(modules),
        total_sequences=total_sequences,
        available=available,
        issues=tuple(issues),
    )


def load_fastqc_reports(
    fastqc_dir: Path,
    max_errors: int = 5,
    known_sample_ids: set[str] | None = None,
) -> FastQCCollection:
    """Load all ``*_fastqc.zip`` archives in one directory.

    Uncompressed FastQC output folders and non-ZIP files are ignored; only
    ZIP archives are supported.  Archives whose names cannot be associated,
    or whose sample does not occur in the FASTQ discovery result, are reported
    as global issues rather than guessed into a sample.
    """
    fastqc_dir = Path(fastqc_dir)
    if not fastqc_dir.exists():
        raise FastQCError(
            f"FastQC directory does not exist: {fastqc_dir}. "
            "Create it, omit --fastqc-dir, or correct the path."
        )
    if not fastqc_dir.is_dir():
        raise FastQCError(
            f"FastQC path is not a directory: {fastqc_dir}. "
            "Pass the directory that contains *_fastqc.zip archives."
        )

    try:
        zip_paths = sorted(
            (
                path
                for path in fastqc_dir.iterdir()
                if path.is_file() and path.name.lower().endswith(".zip")
            ),
            key=lambda item: item.name,
        )
    except OSError as exc:
        raise FastQCError(f"Could not list FastQC directory {fastqc_dir}: {exc}") from exc

    reports: list[FastQCReport] = []
    issues: list[str] = []
    by_key: dict[tuple[str, ReadSide], list[FastQCReport]] = {}

    for path in zip_paths:
        if fastqc_report_stem(path) is None:
            issues.append(
                f"Unrecognized FastQC archive name '{path.name}': expected a name "
                "ending in _fastqc.zip. Rename it or move it out of the FastQC directory."
            )
            continue

        report = parse_fastqc_report(path, max_errors=max_errors)
        reports.append(report)

        if report.sample_id is None or report.side is None:
            issues.extend(report.issues)
            continue
        if known_sample_ids is not None and report.sample_id not in known_sample_ids:
            issues.append(
                f"FastQC report '{report.report_name}' refers to sample "
                f"'{report.sample_id}' ({report.side.value}), but no matching FASTQ "
                "pair was discovered. Check the sample naming in both directories."
            )
            issues.extend(
                issue
                for issue in report.issues
                if issue not in issues
            )
            continue

        by_key.setdefault((report.sample_id, report.side), []).append(report)

    frozen_by_key = {
        key: tuple(sorted(value, key=lambda report: report.report_name))
        for key, value in by_key.items()
    }
    return FastQCCollection(
        reports=tuple(reports),
        by_key=frozen_by_key,
        issues=tuple(issues),
    )


def associate_side(
    collection: FastQCCollection,
    sample_id: str,
    side: ReadSide,
    *,
    fastqc_requested: bool,
    fastq_exists: bool,
) -> FastQCSideResult:
    """Associate one sample read side with its FastQC archive.

    Missing evidence is never converted into a PASS.  Duplicate matching
    archives are reported as ambiguous instead of choosing arbitrarily.
    """
    if not fastqc_requested:
        return FastQCSideResult(
            side=side, availability=FASTQC_NOT_REQUESTED, report=None
        )

    reports = collection.by_key.get((sample_id, side), ())
    if not fastq_exists:
        issues: tuple[str, ...] = ()
        if reports:
            names = ", ".join(report.report_name for report in reports)
            issues = (
                f"FastQC report(s) exist for sample '{sample_id}' ({side.value}) but "
                f"the matching FASTQ file is missing: {names}. Restore the mate or "
                "remove the stale report(s).",
            )
        return FastQCSideResult(
            side=side,
            availability=FASTQC_NOT_APPLICABLE,
            report=None,
            issues=issues,
        )

    if not reports:
        expected = f"{sample_id}_{side.value}_fastqc.zip"
        return FastQCSideResult(
            side=side,
            availability=FASTQC_MISSING,
            report=None,
            issues=(
                f"FastQC report missing for sample '{sample_id}' ({side.value}). "
                f"Expected an archive such as '{expected}' in the FastQC directory. "
                "Re-run FastQC for this file or omit --fastqc-dir.",
            ),
        )
    if len(reports) > 1:
        names = ", ".join(report.report_name for report in reports)
        return FastQCSideResult(
            side=side,
            availability=FASTQC_AMBIGUOUS,
            report=None,
            issues=(
                f"Multiple FastQC reports match sample '{sample_id}' ({side.value}): "
                f"{names}. Keep exactly one archive per FASTQ file so statuses are "
                "not guessed.",
            ),
        )

    report = reports[0]
    availability = FASTQC_AVAILABLE if report.available else FASTQC_INVALID
    return FastQCSideResult(
        side=side,
        availability=availability,
        report=report,
        issues=report.issues,
    )
