from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from microbiome_qc.pairing import normalize_read_id, validate_pairing
from tests.helpers import write_fastq


class ReadIdNormalizationTests(unittest.TestCase):
    def test_slash_suffixes_normalize_to_same_core(self) -> None:
        self.assertEqual(normalize_read_id("@read1/1"), ("read1", "1"))
        self.assertEqual(normalize_read_id("@read1/2"), ("read1", "2"))
        self.assertEqual(normalize_read_id("@read1"), ("read1", None))

    def test_illumina_comment_direction_is_extracted(self) -> None:
        core, direction = normalize_read_id("@M00176:17:1:2:3 2:N:0:1")
        self.assertEqual(core, "M00176:17:1:2:3")
        self.assertEqual(direction, "2")

    def test_only_first_whitespace_token_is_compared(self) -> None:
        core, direction = normalize_read_id("@abc def ghi 1:N:0:1")
        self.assertEqual(core, "abc")
        self.assertIsNone(direction)

    def test_empty_header_is_safe(self) -> None:
        self.assertEqual(normalize_read_id("@"), ("", None))


class PairingValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.r1 = self.root / "S_R1.fastq"
        self.r2 = self.root / "S_R2.fastq"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def write_pair(
        self,
        r1_headers: list[str],
        r2_headers: list[str],
        sequence: str = "ACGT",
    ) -> None:
        write_fastq(self.r1, [(header, sequence, "I" * len(sequence)) for header in r1_headers])
        write_fastq(self.r2, [(header, sequence, "I" * len(sequence)) for header in r2_headers])

    def test_matching_slash_headers_pass(self) -> None:
        self.write_pair(
            ["@read1/1", "@read2/1"],
            ["@read1/2", "@read2/2"],
        )
        result = validate_pairing(self.r1, self.r2, 2, 2)
        self.assertTrue(result.checked)
        self.assertTrue(result.passed, result.errors)
        self.assertEqual(result.mismatch_count, 0)
        self.assertEqual(result.label, "PASS")

    def test_matching_illumina_headers_pass(self) -> None:
        self.write_pair(
            ["@M001:1:1:1:1 1:N:0:1", "@M001:1:1:1:2 1:N:0:1"],
            ["@M001:1:1:1:1 2:N:0:1", "@M001:1:1:1:2 2:N:0:1"],
        )
        result = validate_pairing(self.r1, self.r2, 2, 2)
        self.assertTrue(result.passed, result.errors)

    def test_read_count_difference_fails(self) -> None:
        self.write_pair(["@read1/1"], ["@read1/2", "@read2/2"])
        result = validate_pairing(self.r1, self.r2, 1, 2)
        self.assertFalse(result.passed)
        self.assertIn("R1 has 1 reads but R2 has 2", " ".join(result.errors))

    def test_identifier_mismatch_reports_record_number(self) -> None:
        self.write_pair(
            ["@read1/1", "@read2/1", "@read3/1"],
            ["@read1/2", "@other/2", "@read3/2"],
        )
        result = validate_pairing(self.r1, self.r2, 3, 3)
        self.assertFalse(result.passed)
        self.assertEqual(result.mismatch_count, 1)
        mismatch = result.mismatches[0]
        self.assertEqual(mismatch.record_number, 2)
        self.assertIn("read2", mismatch.r1_id)
        self.assertIn("other", mismatch.r2_id)
        self.assertIn("record 2", " ".join(result.errors))

    def test_mismatch_examples_are_bounded_but_totals_are_not(self) -> None:
        r1_headers = [f"@r{index}/1" for index in range(1, 7)]
        r2_headers = [f"@x{index}/2" for index in range(1, 7)]
        self.write_pair(r1_headers, r2_headers)
        result = validate_pairing(self.r1, self.r2, 6, 6, max_errors=2)
        self.assertEqual(result.mismatch_count, 6)
        self.assertEqual(len(result.mismatches), 2)
        self.assertIn("6 of 6", " ".join(result.errors))
        self.assertIn("record 1", " ".join(result.errors))

    def test_max_errors_zero_retains_no_examples(self) -> None:
        self.write_pair(["@a/1"], ["@b/2"])
        result = validate_pairing(self.r1, self.r2, 1, 1, max_errors=0)
        self.assertEqual(result.mismatch_count, 1)
        self.assertEqual(result.mismatches, ())

    def test_swapped_illumina_direction_fails(self) -> None:
        self.write_pair(
            ["@M001:1:1:1:1 2:N:0:1"],
            ["@M001:1:1:1:1 1:N:0:1"],
        )
        result = validate_pairing(self.r1, self.r2, 1, 1)
        self.assertFalse(result.passed)
        self.assertIn("swapped", " ".join(result.errors))
        self.assertIn("direction", result.mismatches[0].reason.lower())

    def test_swapped_slash_directions_fail(self) -> None:
        self.write_pair(["@read1/2"], ["@read1/1"])
        result = validate_pairing(self.r1, self.r2, 1, 1)
        self.assertFalse(result.passed)
        self.assertEqual(result.mismatch_count, 1)
        self.assertIn("swapped", result.mismatches[0].reason)
        self.assertIn("direction", result.mismatches[0].reason.lower())

    def test_direction_mismatch_on_only_one_mate_fails(self) -> None:
        self.write_pair(
            ["@read1 1:N:0:1"],
            ["@read1 1:N:0:1"],
        )
        result = validate_pairing(self.r1, self.r2, 1, 1)
        self.assertFalse(result.passed)
        self.assertIn("R2 header indicates read 1", result.mismatches[0].reason)

    def test_comments_do_not_break_core_comparison(self) -> None:
        self.write_pair(
            ["@read1 foo bar 1:N:0:1"],
            ["@read1 baz qux 2:N:0:1"],
        )
        result = validate_pairing(self.r1, self.r2, 1, 1)
        self.assertTrue(result.passed, result.errors)


if __name__ == "__main__":
    unittest.main()
