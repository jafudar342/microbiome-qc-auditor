from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from microbiome_qc.discovery import discover_fastq_files
from microbiome_qc.errors import DiscoveryError
from microbiome_qc.models import ReadSide


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.fastq = self.root / "FASTQ"
        self.fastq.mkdir()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def touch(self, name: str, data: bytes = b"") -> Path:
        path = self.fastq / name
        path.write_bytes(data)
        return path

    def test_common_pairing_patterns(self) -> None:
        patterns = [
            ("SRR123456_1.fastq.gz", "SRR123456_2.fastq.gz"),
            ("SRR654321_R1.fastq.gz", "SRR654321_R2.fastq.gz"),
            ("LANE_R1_001.fastq.gz", "LANE_R2_001.fastq.gz"),
        ]
        for r1, r2 in patterns:
            with self.subTest(pattern=r1):
                self.touch(r1)
                self.touch(r2)

        result = discover_fastq_files(self.fastq)
        by_id = {sample.sample_id: sample for sample in result.samples}
        self.assertEqual(set(by_id), {"SRR123456", "SRR654321", "LANE"})
        self.assertEqual(by_id["SRR123456"].r1.name, "SRR123456_1.fastq.gz")
        self.assertEqual(by_id["SRR123456"].r2.name, "SRR123456_2.fastq.gz")
        self.assertEqual(by_id["LANE"].r1.name, "LANE_R1_001.fastq.gz")
        self.assertFalse(result.issues)
        self.assertFalse(result.orphans)

    def test_all_supported_extensions(self) -> None:
        for index, extension in enumerate((".fastq", ".fq", ".fastq.gz", ".fq.gz")):
            with self.subTest(extension=extension):
                self.touch(f"EXT{index}_R1{extension}")
                self.touch(f"EXT{index}_R2{extension}")
        result = discover_fastq_files(self.fastq)
        self.assertEqual(len(result.samples), 4)
        self.assertTrue(all(sample.is_complete for sample in result.samples))

    def test_read_markers_and_extensions_are_case_insensitive(self) -> None:
        self.touch("CaseExt_r1.FASTQ.GZ")
        self.touch("CaseExt_r2.Fq.Gz")
        result = discover_fastq_files(self.fastq)
        self.assertEqual(len(result.samples), 1)
        self.assertEqual(result.samples[0].sample_id, "CaseExt")
        self.assertTrue(result.samples[0].is_complete)

    def test_sample_ids_remain_case_sensitive(self) -> None:
        self.touch("SampleA_R1.fastq.gz")
        self.touch("samplea_R2.fastq.gz")
        result = discover_fastq_files(self.fastq)
        self.assertEqual([sample.sample_id for sample in result.samples], ["SampleA", "samplea"])
        self.assertEqual(len(result.orphans), 2)
        self.assertTrue(all(sample.is_orphan for sample in result.samples))

    def test_orphan_is_detected_and_retained(self) -> None:
        self.touch("LONELY_R1.fastq.gz")
        result = discover_fastq_files(self.fastq)
        self.assertEqual(len(result.samples), 1)
        sample = result.samples[0]
        self.assertTrue(sample.is_orphan)
        self.assertEqual(sample.r1.name, "LONELY_R1.fastq.gz")
        self.assertIsNone(sample.r2)
        self.assertEqual(len(result.orphans), 1)
        orphan = result.orphans[0]
        self.assertEqual(orphan.sample_id, "LONELY")
        self.assertEqual(orphan.side, ReadSide.R1)
        self.assertEqual(orphan.filename, "LONELY_R1.fastq.gz")

    def test_duplicate_candidates_are_ambiguous_not_discarded(self) -> None:
        self.touch("DUP_R1.fastq.gz")
        self.touch("DUP_1.fastq.gz")
        self.touch("DUP_R2.fastq.gz")
        result = discover_fastq_files(self.fastq)
        self.assertEqual(len(result.samples), 1)
        sample = result.samples[0]
        self.assertTrue(sample.is_ambiguous)
        self.assertIsNone(sample.r1)
        self.assertEqual(len(sample.r1_files), 2)
        self.assertEqual(len(result.ambiguous_samples), 1)
        self.assertFalse(result.orphans)

    def test_ambiguous_sample_with_missing_side_is_not_orphan(self) -> None:
        self.touch("MULTI_R1.fastq.gz")
        self.touch("MULTI_1.fastq.gz")
        result = discover_fastq_files(self.fastq)
        sample = result.samples[0]
        self.assertTrue(sample.is_ambiguous)
        self.assertFalse(sample.is_orphan)
        self.assertFalse(result.orphans)

    def test_unrecognized_supported_file_is_reported(self) -> None:
        self.touch("single_end.fastq.gz")
        result = discover_fastq_files(self.fastq)
        self.assertFalse(result.samples)
        self.assertEqual(len(result.issues), 1)
        issue = result.issues[0]
        self.assertEqual(issue.kind, "unrecognized")
        self.assertIn("single_end.fastq.gz", issue.message)
        self.assertIn("_R1", issue.message)

    def test_unsupported_file_is_reported(self) -> None:
        self.touch("NOTES.txt", b"hello")
        self.touch("SIGNAL.bam", b"not really bam")
        result = discover_fastq_files(self.fastq)
        self.assertEqual(len(result.issues), 2)
        self.assertTrue(all(issue.kind == "unsupported" for issue in result.issues))
        self.assertIn("NOTES.txt", result.issues[0].message + result.issues[1].message)

    def test_subdirectory_is_reported_as_not_scanned(self) -> None:
        (self.fastq / "nested").mkdir()
        (self.fastq / "nested" / "X_R1.fastq.gz").write_bytes(b"")
        result = discover_fastq_files(self.fastq)
        self.assertFalse(result.samples)
        self.assertEqual(result.issues[0].kind, "directory")
        self.assertIn("non-recursive", result.issues[0].message)

    def test_filenames_with_spaces_and_special_characters(self) -> None:
        sample = "Gut sample #1 (test) [run=2]"
        self.touch(f"{sample}_R1.fastq.gz")
        self.touch(f"{sample}_R2.fastq.gz")
        result = discover_fastq_files(self.fastq)
        self.assertEqual(len(result.samples), 1)
        self.assertEqual(result.samples[0].sample_id, sample)
        self.assertTrue(result.samples[0].is_complete)

    def test_sample_order_is_deterministic(self) -> None:
        for name in ("zeta", "Alpha", "beta"):
            self.touch(f"{name}_R1.fastq.gz")
            self.touch(f"{name}_R2.fastq.gz")
        first = discover_fastq_files(self.fastq)
        second = discover_fastq_files(self.fastq)
        self.assertEqual(
            [sample.sample_id for sample in first.samples], ["Alpha", "beta", "zeta"]
        )
        self.assertEqual(first.samples, second.samples)

    def test_missing_directory_raises_actionable_error(self) -> None:
        with self.assertRaises(DiscoveryError) as caught:
            discover_fastq_files(self.root / "does-not-exist")
        self.assertIn("does not exist", str(caught.exception))

    def test_file_instead_of_directory_raises(self) -> None:
        path = self.root / "not-a-dir"
        path.write_text("x", encoding="utf-8")
        with self.assertRaises(DiscoveryError) as caught:
            discover_fastq_files(path)
        self.assertIn("not a directory", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
