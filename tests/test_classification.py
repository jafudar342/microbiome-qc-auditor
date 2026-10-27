from __future__ import annotations

import unittest

from microbiome_qc.classification import classify_sample
from microbiome_qc.models import FAIL, PASS, WARN


class ClassificationTests(unittest.TestCase):
    def test_clean_sample_passes(self) -> None:
        decision = classify_sample()
        self.assertEqual(decision.status, PASS)
        self.assertEqual(decision.reasons, ())

    def test_fastqc_warn_makes_sample_warn(self) -> None:
        decision = classify_sample(
            fastqc_module_findings=(("R1: Per base sequence quality", WARN),)
        )
        self.assertEqual(decision.status, WARN)
        self.assertTrue(any("WARN" in reason for reason in decision.reasons))

    def test_fastqc_fail_is_sample_warn_not_structural_fail(self) -> None:
        decision = classify_sample(
            fastqc_module_findings=(("R2: Adapter Content", FAIL),)
        )
        self.assertEqual(decision.status, WARN)
        self.assertIn("R2: Adapter Content", decision.reasons[0])

    def test_missing_report_concern_makes_sample_warn(self) -> None:
        decision = classify_sample(
            fastqc_issues=("FastQC report missing for sample 'S' (R1).",)
        )
        self.assertEqual(decision.status, WARN)

    def test_structural_error_always_fails_even_with_fastqc_pass(self) -> None:
        decision = classify_sample(
            structural_errors=("R2 record 4 is truncated.",),
            fastqc_module_findings=(
                ("R1: Basic Statistics", PASS),
                ("R2: Adapter Content", PASS),
            ),
        )
        self.assertEqual(decision.status, FAIL)
        self.assertIn("truncated", decision.reasons[0])

    def test_structural_error_outranks_fastqc_warn(self) -> None:
        decision = classify_sample(
            structural_errors=("R1 and R2 read counts differ.",),
            fastqc_issues=("FastQC report missing.",),
            fastqc_module_findings=(("R1: Adapter Content", WARN),),
        )
        self.assertEqual(decision.status, FAIL)
        self.assertEqual(len(decision.reasons), 3)

    def test_no_fastqc_evidence_is_pass_without_issues(self) -> None:
        decision = classify_sample()
        self.assertEqual(decision.status, PASS)

    def test_reasons_are_deduplicated_in_order(self) -> None:
        decision = classify_sample(
            fastqc_issues=("same issue", "same issue"),
            fastqc_module_findings=(
                ("R1: Adapter Content", FAIL),
                ("R1: Adapter Content", FAIL),
            ),
        )
        self.assertEqual(decision.status, WARN)
        self.assertEqual(decision.reasons, ("same issue", "FastQC module (R1: Adapter Content) reported FAIL."))

    def test_pass_module_statuses_do_not_create_concerns(self) -> None:
        decision = classify_sample(
            fastqc_module_findings=(("R1: Basic Statistics", PASS),)
        )
        self.assertEqual(decision.status, PASS)


if __name__ == "__main__":
    unittest.main()
