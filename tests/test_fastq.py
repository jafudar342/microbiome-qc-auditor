from __future__ import annotations

import gzip
import tempfile
import unittest
from pathlib import Path

from microbiome_qc.fastq import scan_fastq
from tests.helpers import fastq_bytes, write_fastq, write_raw


class FastqScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_valid_statistics_plain_and_gzip(self) -> None:
        records = [
            ("@r1", "ACGTN", "IIIII"),
            ("@r2", "ggcc", "IIII"),
        ]
        plain = self.root / "valid.fastq"
        compressed = self.root / "valid.fastq.gz"
        write_fastq(plain, records)
        write_fastq(compressed, records, compressed=True)

        for path in (plain, compressed):
            with self.subTest(path=path.name):
                result = scan_fastq(path)
                self.assertTrue(result.valid, result.errors)
                self.assertEqual(result.errors, ())
                self.assertEqual(result.stats.total_reads, 2)
                self.assertEqual(result.stats.total_bases, 9)
                self.assertEqual(result.stats.min_length, 4)
                self.assertEqual(result.stats.max_length, 5)
                self.assertEqual(result.stats.mean_length, 4.5)
                self.assertEqual(result.stats.acgt_bases, 8)
                self.assertEqual(result.stats.gc_percent, 75.0)

    def test_mean_length_rounding(self) -> None:
        records = [
            ("@r1", "A", "I"),
            ("@r2", "AC", "II"),
            ("@r3", "AC", "II"),
        ]
        path = self.root / "rounding.fastq"
        write_fastq(path, records)
        result = scan_fastq(path)
        self.assertTrue(result.valid)
        self.assertEqual(result.stats.mean_length, 1.67)
        self.assertEqual(result.stats.total_bases, 5)

    def test_gc_denominator_excludes_n_and_other_symbols(self) -> None:
        records = [("@r1", "GCGC-NN.", "IIIIIIII")]
        path = self.root / "gc.fastq"
        write_fastq(path, records)
        result = scan_fastq(path)
        self.assertTrue(result.valid)
        self.assertEqual(result.stats.acgt_bases, 4)
        self.assertEqual(result.stats.gc_percent, 100.0)

    def test_gc_is_zero_when_no_acgt_bases(self) -> None:
        records = [("@r1", "NNNN", "IIII")]
        path = self.root / "alln.fastq"
        write_fastq(path, records)
        result = scan_fastq(path)
        self.assertTrue(result.valid)
        self.assertEqual(result.stats.gc_percent, 0.0)
        self.assertEqual(result.stats.acgt_bases, 0)

    def test_crlf_and_missing_final_newline_are_accepted(self) -> None:
        path = self.root / "crlf.fastq"
        path.write_bytes(b"@r1\r\nACGT\r\n+\r\nIIII")
        result = scan_fastq(path)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.stats.total_reads, 1)

    def test_plus_separator_may_repeat_identifier(self) -> None:
        path = self.root / "plus.fastq"
        write_fastq(path, [("@r1", "ACGT", "IIII")], separator="+r1")
        result = scan_fastq(path)
        self.assertTrue(result.valid, result.errors)

    def test_printable_quality_boundaries_are_accepted(self) -> None:
        path = self.root / "quality.fastq"
        write_fastq(path, [("@r1", "ACGT", "!~!~")])
        result = scan_fastq(path)
        self.assertTrue(result.valid, result.errors)

    def test_empty_file_is_invalid(self) -> None:
        path = self.root / "empty.fastq"
        path.write_bytes(b"")
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertEqual(result.stats.total_reads, 0)
        self.assertIn("contains no FASTQ records", result.errors[0])

    def test_invalid_header_is_rejected(self) -> None:
        path = self.root / "bad-header.fastq"
        path.write_bytes(b">r1\nACGT\n+\nIIII\n")
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("header must start with '@'", result.errors[0])

    def test_header_without_identifier_is_rejected(self) -> None:
        path = self.root / "blank-header.fastq"
        path.write_bytes(b"@\nACGT\n+\nIIII\n")
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("no read identifier", result.errors[0])

    def test_invalid_separator_is_rejected(self) -> None:
        path = self.root / "bad-separator.fastq"
        path.write_bytes(b"@r1\nACGT\n-\nIIII\n")
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("separator line must start with '+'", result.errors[0])

    def test_truncated_record_is_rejected(self) -> None:
        path = self.root / "truncated.fastq"
        path.write_bytes(b"@r1\nACGT\n+\n")
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("truncated", result.errors[0])
        self.assertIn("quality line", result.errors[0])

    def test_header_only_truncation_is_rejected(self) -> None:
        path = self.root / "header-only.fastq"
        path.write_bytes(b"@r1\n")
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("truncated", result.errors[0])

    def test_sequence_quality_length_mismatch_is_rejected(self) -> None:
        path = self.root / "length-mismatch.fastq"
        write_fastq(path, [("@r1", "ACGT", "III")])
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("lengths differ", result.errors[0])

    def test_empty_sequence_is_rejected(self) -> None:
        path = self.root / "empty-seq.fastq"
        write_fastq(path, [("@r1", "", "")])
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("sequence line is empty", result.errors[0])

    def test_invalid_quality_character_is_rejected(self) -> None:
        path = self.root / "bad-quality.fastq"
        write_fastq(path, [("@r1", "ACGT", "III ")])
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("invalid byte 0x20", result.errors[0])

    def test_invalid_gzip_is_rejected(self) -> None:
        path = self.root / "fake.fastq.gz"
        write_raw(path, b"this is not gzip data", compressed=False)
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("gzip", result.errors[0].lower())

    def test_truncated_gzip_is_rejected(self) -> None:
        path = self.root / "truncated.fastq.gz"
        payload = gzip.compress(fastq_bytes([("@r1", "ACGT", "IIII")]))
        write_raw(path, payload[:-8], compressed=False)
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertIn("gzip", result.errors[0].lower())

    def test_missing_path_reports_actionable_error(self) -> None:
        result = scan_fastq(self.root / "missing.fastq")
        self.assertFalse(result.valid)
        self.assertIn("could not be read", result.errors[0])

    def test_scan_stops_after_first_structural_error(self) -> None:
        records = [
            ("@ok", "ACGT", "IIII"),
            ("not-a-header", "ACGT", "IIII"),
            ("@after", "ACGT", "IIII"),
        ]
        path = self.root / "stop.fastq"
        write_fastq(path, records)
        result = scan_fastq(path)
        self.assertFalse(result.valid)
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.stats.total_reads, 1)


if __name__ == "__main__":
    unittest.main()
