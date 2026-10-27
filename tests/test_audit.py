from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from microbiome_qc.audit import AuditOptions, build_audit
from microbiome_qc.errors import AuditError, DiscoveryError
from microbiome_qc.models import (
    AMBIGUOUS,
    FAIL,
    FASTQC_AMBIGUOUS,
    FASTQC_AVAILABLE,
    FASTQC_INVALID,
    FASTQC_MISSING,
    FASTQC_NOT_APPLICABLE,
    FASTQC_NOT_REQUESTED,
    PASS,
    WARN,
)
from tests.helpers import (
    simple_pair,
    statuses,
    write_fastq,
    write_fastqc_for_fastq,
)


class AuditIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.fastq_dir = self.root / "FASTQ"
        self.fastqc_dir = self.root / "FastQC"
        self.output_dir = self.root / "QC_Report"
        self.fastq_dir.mkdir()
        self.fastqc_dir.mkdir()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def options(self, **overrides) -> AuditOptions:
        values = {
            "fastq_dir": self.fastq_dir,
            "fastqc_dir": None,
            "output_dir": self.output_dir,
        }
        values.update(overrides)
        return AuditOptions(**values)

    def make_clean_pair(
        self,
        sample: str = "SAMPLE",
        count: int = 3,
        *,
        with_fastqc: bool = True,
        r1_statuses: dict[str, str] | None = None,
        r2_statuses: dict[str, str] | None = None,
    ) -> tuple[Path, Path]:
        r1, r2 = simple_pair(self.fastq_dir, sample=sample, count=count)
        if with_fastqc:
            write_fastqc_for_fastq(
                self.fastqc_dir,
                r1.name,
                status_map=r1_statuses,
                total_sequences=count,
            )
            write_fastqc_for_fastq(
                self.fastqc_dir,
                r2.name,
                status_map=r2_statuses,
                total_sequences=count,
            )
        return r1, r2

    def test_clean_sample_with_complete_fastqc_passes(self) -> None:
        self.make_clean_pair()
        result = build_audit(
            self.options(fastqc_dir=self.fastqc_dir)
        )
        self.assertEqual(result.sample_count, 1)
        self.assertEqual((result.pass_count, result.warn_count, result.fail_count), (1, 0, 0))
        self.assertEqual(result.missing_reports, ())
        self.assertEqual(result.warnings, ())
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, PASS)
        self.assertEqual(sample.pairing_result, PASS)
        self.assertTrue(sample.r1_scan is not None and sample.r1_scan.valid)
        self.assertTrue(sample.r2_scan is not None and sample.r2_scan.valid)
        self.assertEqual(sample.r1_scan.stats.total_reads, 3)
        self.assertEqual(sample.r2_scan.stats.total_bases, 12)
        self.assertIsNotNone(sample.fastqc_r1)
        self.assertIsNotNone(sample.fastqc_r2)
        self.assertEqual(sample.fastqc_r1.availability, FASTQC_AVAILABLE)
        self.assertEqual(sample.fastqc_r2.availability, FASTQC_AVAILABLE)
        self.assertEqual(sample.fastqc_r1.pass_count, 11)
        self.assertEqual(sample.fastqc_r1.warn_count, 0)
        self.assertEqual(sample.fastqc_r1.fail_count, 0)
        self.assertTrue(result.timestamp.endswith("+00:00"))
        self.assertTrue(result.config["fastqc_requested"])

    def test_build_audit_does_not_write_reports(self) -> None:
        self.make_clean_pair()
        build_audit(self.options(fastqc_dir=self.fastqc_dir))
        self.assertFalse(self.output_dir.exists())

    def test_no_fastqc_directory_passes_but_is_not_fully_validated(self) -> None:
        self.make_clean_pair(with_fastqc=False)
        result = build_audit(self.options(fastqc_dir=None))
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, PASS)
        self.assertFalse(result.fastqc_requested)
        self.assertEqual(result.missing_reports, ())
        self.assertIsNotNone(sample.fastqc_r1)
        self.assertEqual(sample.fastqc_r1.availability, FASTQC_NOT_REQUESTED)
        self.assertEqual(sample.fastqc_r1.issues, ())
        self.assertIsNone(sample.fastqc_r1.pass_count)
        self.assertIsNone(sample.fastqc_r1.warn_count)
        self.assertIsNone(sample.fastqc_r1.fail_count)
        limitations = " ".join(result.limitations)
        self.assertIn("FastQC was not requested", limitations)
        self.assertIn("not fully validated", limitations)

    def test_missing_fastqc_report_is_warn_and_recorded(self) -> None:
        r1, _r2 = self.make_clean_pair(with_fastqc=False)
        write_fastqc_for_fastq(
            self.fastqc_dir, r1.name, total_sequences=3
        )
        result = build_audit(self.options(fastqc_dir=self.fastqc_dir))
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, WARN)
        self.assertEqual(sample.pairing_result, PASS)
        self.assertEqual(sample.fastqc_r1.availability, FASTQC_AVAILABLE)
        self.assertEqual(sample.fastqc_r2.availability, FASTQC_MISSING)
        self.assertIsNone(sample.fastqc_r2.pass_count)
        self.assertEqual(len(result.missing_reports), 1)
        missing = result.missing_reports[0]
        self.assertEqual(missing.sample_id, "SAMPLE")
        self.assertEqual(missing.read_direction, "R2")
        self.assertIn("FastQC report missing", missing.reason)
        self.assertTrue(
            any("FastQC report missing" in reason for reason in sample.classification.reasons)
        )

    def test_fastqc_fail_is_sample_warn_and_status_is_preserved(self) -> None:
        self.make_clean_pair(r1_statuses=statuses(Adapter_Content="FAIL"))
        result = build_audit(self.options(fastqc_dir=self.fastqc_dir))
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, WARN)
        self.assertEqual(sample.fastqc_r1.fail_count, 1)
        self.assertEqual(sample.fastqc_r1.warn_count, 0)
        self.assertEqual(sample.fastqc_r1.pass_count, 10)
        adapter = [
            module
            for module in sample.fastqc_r1.report.modules
            if module.module == "Adapter Content"
        ]
        self.assertEqual(len(adapter), 1)
        self.assertEqual(adapter[0].status, FAIL)
        self.assertTrue(
            any(
                "R1: Adapter Content" in reason and "FAIL" in reason
                for reason in sample.classification.reasons
            )
        )

    def test_structural_corruption_overrides_fastqc_pass(self) -> None:
        r1, r2 = self.make_clean_pair(with_fastqc=False)
        write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=3)
        write_fastqc_for_fastq(self.fastqc_dir, r2.name, total_sequences=3)
        # Replace R2 with a valid prefix plus one truncated final record while
        # keeping FastQC completely PASS.
        write_fastq(
            r2,
            [
                ("@read1/2", "ACGT", "IIII"),
                ("@read2/2", "ACGT", "IIII"),
            ],
            trailing=b"@read3/2\nACGT\n+\n",
        )
        result = build_audit(self.options(fastqc_dir=self.fastqc_dir))
        sample = result.samples[0]
        self.assertEqual(result.fail_count, 1)
        self.assertEqual(sample.classification.status, FAIL)
        self.assertIn(sample.fastqc_r1.availability, (FASTQC_AVAILABLE,))
        self.assertIn(sample.fastqc_r2.availability, (FASTQC_AVAILABLE,))
        self.assertEqual(sample.fastqc_r2.fail_count, 0)
        self.assertTrue(any("truncated" in reason for reason in sample.classification.reasons))

    def test_pairing_identifier_mismatch_is_fail_with_record_number(self) -> None:
        r1, r2 = self.make_clean_pair(with_fastqc=False)
        write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=3)
        write_fastqc_for_fastq(self.fastqc_dir, r2.name, total_sequences=3)
        write_fastq(
            r2,
            [
                ("@read1/2", "ACGT", "IIII"),
                ("@different/2", "ACGT", "IIII"),
                ("@read3/2", "ACGT", "IIII"),
            ],
        )
        result = build_audit(self.options(fastqc_dir=self.fastqc_dir))
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, FAIL)
        self.assertEqual(sample.pairing_result, FAIL)
        self.assertIsNotNone(sample.pairing)
        self.assertEqual(sample.pairing.mismatch_count, 1)
        self.assertEqual(sample.pairing.mismatches[0].record_number, 2)
        self.assertIn("record 2", sample.pairing_details)
        self.assertEqual(sample.fastqc_r2.fail_count, 0)

    def test_read_count_difference_is_fail(self) -> None:
        write_fastq(
            self.fastq_dir / "COUNT_R1.fastq",
            [("@read1/1", "ACGT", "IIII"), ("@read2/1", "ACGT", "IIII")],
        )
        write_fastq(
            self.fastq_dir / "COUNT_R2.fastq",
            [
                ("@read1/2", "ACGT", "IIII"),
                ("@read2/2", "ACGT", "IIII"),
                ("@read3/2", "ACGT", "IIII"),
            ],
        )
        result = build_audit(self.options())
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, FAIL)
        self.assertEqual(sample.pairing_result, FAIL)
        self.assertIn("R1 has 2 reads but R2 has 3 reads", sample.pairing_details)
        self.assertEqual(result.missing_reports, ())

    def test_orphan_is_fail_and_stale_fastqc_is_surfaced(self) -> None:
        write_fastq(
            self.fastq_dir / "ORPHAN_R1.fastq",
            [("@read1/1", "ACGT", "IIII"), ("@read2/1", "ACGT", "IIII")],
        )
        # R2 FASTQ does not exist, but a stale FastQC archive does.
        write_fastqc_for_fastq(
            self.fastqc_dir,
            "ORPHAN_R2.fastq",
            total_sequences=2,
        )
        result = build_audit(self.options(fastqc_dir=self.fastqc_dir))
        self.assertEqual(len(result.discovery.orphans), 1)
        self.assertEqual(result.discovery.orphans[0].side.value, "R1")
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, FAIL)
        self.assertTrue(any("missing its R2 mate" in reason for reason in sample.classification.reasons))
        self.assertEqual(sample.fastqc_r2.availability, FASTQC_NOT_APPLICABLE)
        self.assertTrue(
            any("matching FASTQ file is missing" in issue for issue in sample.fastqc_r2.issues)
        )
        # R1 exists but has no FastQC report; only that is a "missing" report.
        self.assertEqual(sample.fastqc_r1.availability, FASTQC_MISSING)
        self.assertEqual(len(result.missing_reports), 1)
        self.assertEqual(result.missing_reports[0].read_direction, "R1")

    def test_ambiguous_pair_is_fail_and_keeps_all_candidates(self) -> None:
        r1, _r2 = simple_pair(self.fastq_dir, sample="AMB", count=2)
        shutil.copyfile(r1, self.fastq_dir / "AMB_R1_001.fastq")
        result = build_audit(self.options())
        self.assertEqual(len(result.discovery.ambiguous_samples), 1)
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, FAIL)
        self.assertEqual(sample.pairing_result, AMBIGUOUS)
        self.assertEqual(len(sample.r1_files), 2)
        self.assertIsNone(sample.r1_scan)
        self.assertTrue(any("Ambiguous pairing" in reason for reason in sample.classification.reasons))
        self.assertIn("AMB_R1.fastq", sample.r1_display)
        self.assertIn("AMB_R1_001.fastq", sample.r1_display)

    def test_invalid_fastqc_zip_is_warn_not_silently_missing(self) -> None:
        r1, r2 = self.make_clean_pair(with_fastqc=False)
        (self.fastqc_dir / f"{r1.stem}_fastqc.zip").write_bytes(b"not a zip")
        write_fastqc_for_fastq(self.fastqc_dir, r2.name, total_sequences=3)
        result = build_audit(self.options(fastqc_dir=self.fastqc_dir))
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, WARN)
        self.assertEqual(sample.fastqc_r1.availability, FASTQC_INVALID)
        self.assertIsNone(sample.fastqc_r1.pass_count)
        self.assertEqual(sample.fastqc_r2.availability, FASTQC_AVAILABLE)
        self.assertTrue(
            any("not a readable FastQC ZIP" in reason for reason in sample.classification.reasons)
        )
        self.assertEqual(result.missing_reports, ())

    def test_ambiguous_fastqc_reports_are_warn(self) -> None:
        r1, r2 = self.make_clean_pair(with_fastqc=False)
        write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=3)
        write_fastqc_for_fastq(
            self.fastqc_dir,
            r1.name,
            total_sequences=3,
            report_name="SAMPLE_R1_copy_fastqc.zip",
        )
        write_fastqc_for_fastq(self.fastqc_dir, r2.name, total_sequences=3)
        result = build_audit(self.options(fastqc_dir=self.fastqc_dir))
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, WARN)
        self.assertEqual(sample.fastqc_r1.availability, FASTQC_AMBIGUOUS)
        self.assertTrue(
            any("Multiple FastQC reports" in reason for reason in sample.classification.reasons)
        )

    def test_fastqc_read_count_disagreement_is_warn(self) -> None:
        r1, r2 = self.make_clean_pair(with_fastqc=False)
        write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=4)
        write_fastqc_for_fastq(self.fastqc_dir, r2.name, total_sequences=3)
        result = build_audit(self.options(fastqc_dir=self.fastqc_dir))
        sample = result.samples[0]
        self.assertEqual(sample.classification.status, WARN)
        self.assertEqual(sample.pairing_result, PASS)
        self.assertTrue(
            any("FastQC reports 4 total sequences" in reason for reason in sample.classification.reasons)
        )
        self.assertTrue(any("found 3 reads" in reason for reason in sample.classification.reasons))

    def test_samples_are_in_stable_alphabetical_order(self) -> None:
        simple_pair(self.fastq_dir, sample="B_SAMPLE", count=2)
        simple_pair(self.fastq_dir, sample="A_SAMPLE", count=2)
        result = build_audit(self.options())
        self.assertEqual([sample.sample_id for sample in result.samples], ["A_SAMPLE", "B_SAMPLE"])

    def test_zero_max_errors_is_rejected(self) -> None:
        self.make_clean_pair()
        with self.assertRaises(AuditError):
            build_audit(self.options(fastqc_dir=self.fastqc_dir, max_errors=0))

    def test_directory_without_samples_is_rejected(self) -> None:
        with self.assertRaises(AuditError):
            build_audit(self.options())

    def test_missing_fastq_directory_raises_discovery_error(self) -> None:
        with self.assertRaises(DiscoveryError):
            build_audit(self.options(fastq_dir=self.root / "absent"))


if __name__ == "__main__":
    unittest.main()
