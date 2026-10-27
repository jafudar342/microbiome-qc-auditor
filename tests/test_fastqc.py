from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from microbiome_qc.fastqc import (
    associate_side,
    fastqc_report_stem,
    load_fastqc_reports,
    parse_fastqc_report,
)
from microbiome_qc.models import (
    FASTQC_AMBIGUOUS,
    FASTQC_AVAILABLE,
    FASTQC_INVALID,
    FASTQC_MISSING,
    FASTQC_NOT_APPLICABLE,
    FASTQC_NOT_REQUESTED,
    ReadSide,
)
from tests.helpers import STANDARD_MODULES, statuses, write_fastqc_zip


class FastQCReportParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.fastqc = self.root / "FastQC"
        self.fastqc.mkdir()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_report_stem(self) -> None:
        self.assertEqual(
            fastqc_report_stem(Path("sample_R1_fastqc.zip")), "sample_R1"
        )
        self.assertIsNone(fastqc_report_stem(Path("sample.zip")))

    def test_correct_summary_parsing_and_module_counts(self) -> None:
        status_map = statuses(Per_base_sequence_quality="WARN", Adapter_Content="FAIL")
        rows = tuple(
            (status, module, "READS_R1.fastq.gz")
            for module, status in status_map.items()
        )
        path = self.fastqc / "READS_R1_fastqc.zip"
        write_fastqc_zip(
            path,
            status_rows=rows,
            input_filename="READS_R1.fastq.gz",
            total_sequences=42,
        )
        report = parse_fastqc_report(path)
        self.assertTrue(report.available)
        self.assertEqual(report.sample_id, "READS")
        self.assertEqual(report.side, ReadSide.R1)
        self.assertEqual(report.total_sequences, 42)
        self.assertEqual(len(report.modules), len(STANDARD_MODULES))
        self.assertEqual(report.pass_count, len(STANDARD_MODULES) - 2)
        self.assertEqual(report.warn_count, 1)
        self.assertEqual(report.fail_count, 1)
        self.assertEqual(report.issues, ())
        self.assertEqual(
            [module.module for module in report.modules],
            sorted(STANDARD_MODULES, key=str.casefold),
        )

    def test_missing_modules_are_not_invented(self) -> None:
        path = self.fastqc / "SUBSET_R1_fastqc.zip"
        write_fastqc_zip(
            path,
            status_rows=(
                ("PASS", "Basic Statistics", "SUBSET_R1.fastq.gz"),
                ("WARN", "Adapter Content", "SUBSET_R1.fastq.gz"),
            ),
            input_filename="SUBSET_R1.fastq.gz",
        )
        report = parse_fastqc_report(path)
        self.assertTrue(report.available)
        self.assertEqual(
            [(module.module, module.status) for module in report.modules],
            [("Adapter Content", "WARN"), ("Basic Statistics", "PASS")],
        )
        self.assertEqual(report.pass_count, 1)
        self.assertEqual(report.warn_count, 1)
        self.assertNotIn("Per base sequence quality", {m.module for m in report.modules})

    def test_malformed_rows_are_reported_but_valid_rows_survive(self) -> None:
        summary = (
            "PASS\tBasic Statistics\tX_R1.fastq.gz\n"
            "NOT_A_STATUS\tPer base sequence quality\tX_R1.fastq.gz\n"
            "WARN\tAdapter Content\tX_R1.fastq.gz\n"
            "PASS\tToo few fields\n"
        )
        path = self.fastqc / "X_R1_fastqc.zip"
        write_fastqc_zip(
            path,
            summary_text=summary,
            input_filename="X_R1.fastq.gz",
        )
        report = parse_fastqc_report(path, max_errors=5)
        self.assertTrue(report.available)
        self.assertEqual(len(report.modules), 2)
        self.assertTrue(any("malformed" in issue for issue in report.issues))
        self.assertTrue(any("unrecognized status" in issue for issue in report.issues))

    def test_malformed_row_issue_limit(self) -> None:
        summary = "".join(f"BROKEN\tmodule {index}\tX_R1.fastq.gz\n" for index in range(5))
        path = self.fastqc / "X_R1_fastqc.zip"
        write_fastqc_zip(path, summary_text=summary)
        report = parse_fastqc_report(path, max_errors=2)
        self.assertFalse(report.available)
        row_issues = [
            issue for issue in report.issues if "malformed summary.txt row " in issue
        ]
        self.assertEqual(len(row_issues), 2)
        self.assertTrue(any("additional malformed" in issue for issue in report.issues))

    def test_missing_summary_makes_report_unavailable(self) -> None:
        path = self.fastqc / "NOSUM_R1_fastqc.zip"
        write_fastqc_zip(path, include_summary=False, input_filename="NOSUM_R1.fastq.gz")
        report = parse_fastqc_report(path)
        self.assertFalse(report.available)
        self.assertTrue(any("missing summary.txt" in issue for issue in report.issues))

    def test_missing_data_file_is_a_warning_not_a_fabricated_status(self) -> None:
        path = self.fastqc / "NODATA_R1_fastqc.zip"
        write_fastqc_zip(
            path,
            include_data=False,
            status_rows=tuple(("PASS", module, "NODATA_R1.fastq.gz") for module in STANDARD_MODULES),
            input_filename="NODATA_R1.fastq.gz",
        )
        report = parse_fastqc_report(path)
        self.assertTrue(report.available)
        self.assertIsNone(report.total_sequences)
        self.assertTrue(any("missing fastqc_data.txt" in issue for issue in report.issues))

    def test_invalid_zip_is_reported_without_crashing(self) -> None:
        path = self.fastqc / "BROKEN_R1_fastqc.zip"
        path.write_bytes(b"this is definitely not a zip archive")
        report = parse_fastqc_report(path)
        self.assertFalse(report.available)
        self.assertEqual(report.sample_id, "BROKEN")
        self.assertEqual(report.side, ReadSide.R1)
        self.assertTrue(any("not a readable FastQC ZIP" in issue for issue in report.issues))

    def test_conflicting_archive_and_internal_names_are_flagged(self) -> None:
        path = self.fastqc / "SAMPLE_R1_fastqc.zip"
        write_fastqc_zip(
            path,
            status_rows=(("PASS", "Basic Statistics", "OTHER_R2.fastq.gz"),),
            input_filename="OTHER_R2.fastq.gz",
        )
        report = parse_fastqc_report(path)
        self.assertEqual((report.sample_id, report.side), ("SAMPLE", ReadSide.R1))
        self.assertTrue(any("suggests sample" in issue for issue in report.issues))

    def test_duplicate_module_rows_use_first_status(self) -> None:
        summary = (
            "PASS\tBasic Statistics\tX_R1.fastq.gz\n"
            "FAIL\tBasic Statistics\tX_R1.fastq.gz\n"
        )
        path = self.fastqc / "X_R1_fastqc.zip"
        write_fastqc_zip(path, summary_text=summary)
        report = parse_fastqc_report(path)
        self.assertEqual(len(report.modules), 1)
        self.assertEqual(report.modules[0].status, "PASS")
        self.assertTrue(any("duplicate module" in issue for issue in report.issues))

    def test_non_integer_total_sequences_is_flagged(self) -> None:
        data_text = "\n".join(
            [
                "##FastQC\t0.12.1",
                ">>Basic Statistics\tpass",
                "#Measure\tValue",
                "Filename\tX_R1.fastq.gz",
                "Total Sequences\tlots",
                ">>END_MODULE",
            ]
        )
        path = self.fastqc / "X_R1_fastqc.zip"
        write_fastqc_zip(
            path,
            status_rows=(("PASS", "Basic Statistics", "X_R1.fastq.gz"),),
            data_text=data_text,
        )
        report = parse_fastqc_report(path)
        self.assertIsNone(report.total_sequences)
        self.assertTrue(any("non-integer" in issue for issue in report.issues))

    def test_identity_can_come_from_internal_filename(self) -> None:
        path = self.fastqc / "SAMPLE_fastqc.zip"
        write_fastqc_zip(
            path,
            status_rows=(("PASS", "Basic Statistics", "SAMPLE_R1.fastq.gz"),),
            input_filename="SAMPLE_R1.fastq.gz",
        )
        report = parse_fastqc_report(path)
        self.assertEqual(report.sample_id, "SAMPLE")
        self.assertEqual(report.side, ReadSide.R1)


class FastQCLoadingAndAssociationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.fastqc = self.root / "FastQC"
        self.fastqc.mkdir()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def write_report(self, name: str, input_name: str, status_map=None) -> Path:
        path = self.fastqc / name
        status_map = status_map or statuses()
        write_fastqc_zip(
            path,
            input_filename=input_name,
            status_rows=tuple(
                (status, module, input_name) for module, status in status_map.items()
            ),
            total_sequences=10,
        )
        return path

    def test_unrecognized_archive_name_is_reported(self) -> None:
        self.write_report("not_fastqc_named.zip", "SAMPLE_R1.fastq.gz")
        collection = load_fastqc_reports(self.fastqc, known_sample_ids={"SAMPLE"})
        self.assertEqual(collection.by_key, {})
        self.assertTrue(any("Unrecognized FastQC archive name" in issue for issue in collection.issues))

    def test_unmatched_sample_report_is_reported_as_unused(self) -> None:
        self.write_report("GHOST_R1_fastqc.zip", "GHOST_R1.fastq.gz")
        collection = load_fastqc_reports(self.fastqc, known_sample_ids={"SAMPLE"})
        self.assertTrue(any("no matching FASTQ" in issue for issue in collection.issues))

    def test_missing_report_association_is_explicit(self) -> None:
        collection = load_fastqc_reports(self.fastqc, known_sample_ids={"SAMPLE"})
        side = associate_side(
            collection,
            "SAMPLE",
            ReadSide.R1,
            fastqc_requested=True,
            fastq_exists=True,
        )
        self.assertEqual(side.availability, FASTQC_MISSING)
        self.assertIsNone(side.report)
        self.assertTrue(side.issues)
        self.assertIn("Re-run FastQC", side.issues[0])

    def test_available_report_association(self) -> None:
        self.write_report("SAMPLE_R1_fastqc.zip", "SAMPLE_R1.fastq.gz")
        collection = load_fastqc_reports(self.fastqc, known_sample_ids={"SAMPLE"})
        side = associate_side(
            collection,
            "SAMPLE",
            ReadSide.R1,
            fastqc_requested=True,
            fastq_exists=True,
        )
        self.assertEqual(side.availability, FASTQC_AVAILABLE)
        self.assertIsNotNone(side.report)
        self.assertEqual(side.pass_count, len(STANDARD_MODULES))

    def test_duplicate_reports_are_ambiguous(self) -> None:
        self.write_report("SAMPLE_R1_fastqc.zip", "SAMPLE_R1.fastq.gz")
        self.write_report("SAMPLE_R1_copy_fastqc.zip", "SAMPLE_R1.fastq.gz")
        collection = load_fastqc_reports(self.fastqc, known_sample_ids={"SAMPLE"})
        side = associate_side(
            collection,
            "SAMPLE",
            ReadSide.R1,
            fastqc_requested=True,
            fastq_exists=True,
        )
        self.assertEqual(side.availability, FASTQC_AMBIGUOUS)
        self.assertIsNone(side.report)
        self.assertTrue(any("Multiple FastQC reports" in issue for issue in side.issues))

    def test_invalid_archive_associates_as_invalid(self) -> None:
        (self.fastqc / "SAMPLE_R1_fastqc.zip").write_bytes(b"broken")
        collection = load_fastqc_reports(self.fastqc, known_sample_ids={"SAMPLE"})
        side = associate_side(
            collection,
            "SAMPLE",
            ReadSide.R1,
            fastqc_requested=True,
            fastq_exists=True,
        )
        self.assertEqual(side.availability, FASTQC_INVALID)
        self.assertIsNone(side.pass_count)
        self.assertTrue(side.issues)

    def test_stale_report_for_missing_fastq_is_surfaced(self) -> None:
        self.write_report("SAMPLE_R2_fastqc.zip", "SAMPLE_R2.fastq.gz")
        collection = load_fastqc_reports(self.fastqc, known_sample_ids={"SAMPLE"})
        side = associate_side(
            collection,
            "SAMPLE",
            ReadSide.R2,
            fastqc_requested=True,
            fastq_exists=False,
        )
        self.assertEqual(side.availability, FASTQC_NOT_APPLICABLE)
        self.assertTrue(any("matching FASTQ file is missing" in issue for issue in side.issues))

    def test_not_requested_short_circuits_without_claiming_missing(self) -> None:
        collection = load_fastqc_reports(self.fastqc, known_sample_ids={"SAMPLE"})
        side = associate_side(
            collection,
            "SAMPLE",
            ReadSide.R1,
            fastqc_requested=False,
            fastq_exists=True,
        )
        self.assertEqual(side.availability, FASTQC_NOT_REQUESTED)
        self.assertEqual(side.issues, ())

    def test_missing_fastqc_directory_raises(self) -> None:
        from microbiome_qc.errors import FastQCError

        with self.assertRaises(FastQCError):
            load_fastqc_reports(self.root / "nope")


if __name__ == "__main__":
    unittest.main()
