from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from microbiome_qc.audit import AuditOptions, run_audit
from microbiome_qc.models import FAIL, PASS, WARN
from microbiome_qc.synthetic import generate_demo_dataset
from tests.helpers import simple_pair, write_fastqc_for_fastq


def snapshot(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def embedded_html_payload(html: str) -> dict[str, object]:
    marker = '<script type="application/json" id="audit-data">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


class DemoEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.demo_dir = self.root / "demo"
        generate_demo_dataset(self.demo_dir)
        self.fastq_dir = self.demo_dir / "FASTQ"
        self.fastqc_dir = self.demo_dir / "FastQC"
        self.output_dir = self.demo_dir / "QC_Report"

    def tearDown(self) -> None:
        self._temp.cleanup()

    def audit_demo(self):
        return run_audit(
            AuditOptions(
                fastq_dir=self.fastq_dir,
                fastqc_dir=self.fastqc_dir,
                output_dir=self.output_dir,
            )
        )

    def test_demo_audit_matches_documented_outcomes(self) -> None:
        inputs_before = {
            "FASTQ": snapshot(self.fastq_dir),
            "FastQC": snapshot(self.fastqc_dir),
        }
        result = self.audit_demo()

        self.assertEqual(result.sample_count, 7)
        self.assertEqual(result.pass_count, 1)
        self.assertEqual(result.warn_count, 3)
        self.assertEqual(result.fail_count, 3)
        statuses = {sample.sample_id: sample.classification.status for sample in result.samples}
        self.assertEqual(
            statuses,
            {
                "DEMO_001": PASS,
                "DEMO_002": WARN,
                "DEMO_003": WARN,
                "DEMO_004": FAIL,
                "DEMO_005": FAIL,
                "DEMO_006": FAIL,
                "DEMO_007": WARN,
            },
        )
        by_id = {sample.sample_id: sample for sample in result.samples}
        self.assertEqual(by_id["DEMO_001"].pairing_result, PASS)
        self.assertEqual(by_id["DEMO_001"].fastqc_r1.pass_count, 11)
        self.assertEqual(by_id["DEMO_002"].fastqc_r1.warn_count, 1)
        self.assertEqual(by_id["DEMO_003"].fastqc_r2.fail_count, 1)
        self.assertEqual(by_id["DEMO_003"].classification.status, WARN)
        self.assertTrue(by_id["DEMO_004"].classification.reasons[0].startswith("Sample 'DEMO_004' is missing its R2 mate"))
        self.assertEqual(by_id["DEMO_005"].pairing.mismatches[0].record_number, 2)
        self.assertFalse(by_id["DEMO_006"].r2_scan.valid)
        self.assertTrue(any("truncated" in error for error in by_id["DEMO_006"].r2_scan.errors))
        self.assertEqual(by_id["DEMO_007"].fastqc_r1.availability, "missing")
        self.assertEqual(by_id["DEMO_007"].fastqc_r2.availability, "missing")

        self.assertEqual(len(result.discovery.orphans), 1)
        self.assertEqual(len(result.discovery.ambiguous_samples), 0)
        self.assertEqual(len(result.missing_reports), 2)
        self.assertEqual(
            {(missing.sample_id, missing.read_direction) for missing in result.missing_reports},
            {("DEMO_007", "R1"), ("DEMO_007", "R2")},
        )
        self.assertFalse(result.outputs == ())

        expected_files = {
            "sample_summary.csv",
            "fastqc_modules.csv",
            "summary.json",
            "report.html",
        }
        self.assertEqual({path.name for path in self.output_dir.iterdir()}, expected_files)
        for name in expected_files:
            self.assertGreater((self.output_dir / name).stat().st_size, 0, name)

        with (self.output_dir / "sample_summary.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 7)
        csv_statuses = {row["sample_id"]: row["qc_classification"] for row in rows}
        self.assertEqual(csv_statuses, statuses)
        for row in rows:
            if row["sample_id"] == "DEMO_004":
                self.assertEqual(row["pairing_result"], "MISSING_MATE")
            if row["sample_id"] == "DEMO_005":
                self.assertEqual(row["pairing_result"], "FAIL")
            if row["sample_id"] == "DEMO_006":
                self.assertEqual(row["pairing_result"], "NOT_CHECKED")
            if row["sample_id"] == "DEMO_007":
                self.assertEqual(row["fastqc_r1_available"], "missing")
                self.assertEqual(row["fastqc_r1_pass"], "")
            if row["sample_id"] == "DEMO_006":
                self.assertEqual(row["r2_file_valid"], "no")
                self.assertIn("truncated", row["problems"])

        payload = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(payload["counts"]["discovered_samples"], 7)
        self.assertEqual(payload["counts"]["pass"], 1)
        self.assertEqual(payload["counts"]["warn"], 3)
        self.assertEqual(payload["counts"]["fail"], 3)
        self.assertEqual(payload["counts"]["missing_fastqc_reports"], 2)
        self.assertEqual(payload["counts"]["orphaned_reads"], 1)
        self.assertEqual(payload["counts"]["ambiguous_samples"], 0)
        self.assertEqual(payload["counts"]["ignored_or_unrecognized_files"], 0)
        self.assertEqual(payload["orphaned_reads"][0]["sample_id"], "DEMO_004")
        self.assertEqual(payload["orphaned_reads"][0]["read_direction"], "R1")
        self.assertTrue(payload["fastqc_requested"])
        self.assertEqual(len(payload["samples"]), 7)

        with (self.output_dir / "fastqc_modules.csv").open(encoding="utf-8", newline="") as handle:
            modules = list(csv.DictReader(handle))
        expected_module_rows = sum(
            11
            for sample in payload["samples"]
            for side in ("r1", "r2")
            if sample["fastqc"][side]["report"] is not None
        )
        self.assertEqual(len(modules), 121)
        self.assertEqual(len(modules), expected_module_rows)

        html = (self.output_dir / "report.html").read_text(encoding="utf-8")
        html_payload = embedded_html_payload(html)
        self.assertEqual(html_payload["counts"], payload["counts"])
        self.assertEqual(html_payload["samples"], payload["samples"])
        self.assertIn('id="search-input"', html)
        self.assertIn('id="sample-dialog"', html)
        self.assertNotIn("http://", html.lower())
        self.assertNotIn("https://", html.lower())

        self.assertEqual(snapshot(self.fastq_dir), inputs_before["FASTQ"])
        self.assertEqual(snapshot(self.fastqc_dir), inputs_before["FastQC"])

    def test_corrupt_gzip_is_fail_even_when_fastqc_passes(self) -> None:
        fastq_dir = self.root / "CorruptFASTQ"
        fastqc_dir = self.root / "CorruptFastQC"
        output_dir = self.root / "CorruptReport"
        r1, r2 = simple_pair(fastq_dir, sample="CORRUPT", count=3, compress=True)
        write_fastqc_for_fastq(fastqc_dir, r1.name, total_sequences=3)
        write_fastqc_for_fastq(fastqc_dir, r2.name, total_sequences=3)
        del r2
        original_bad_gzip = b"this is not a gzip stream"
        r1.write_bytes(original_bad_gzip)

        result = run_audit(
            AuditOptions(
                fastq_dir=fastq_dir,
                fastqc_dir=fastqc_dir,
                output_dir=output_dir,
            )
        )
        corrupt = next(sample for sample in result.samples if sample.sample_id == "CORRUPT")
        self.assertEqual(corrupt.classification.status, FAIL)
        self.assertEqual(corrupt.fastqc_r1.availability, "available")
        self.assertEqual(corrupt.fastqc_r1.fail_count, 0)
        self.assertTrue(any("gzip" in error for error in corrupt.r1_scan.errors))
        self.assertEqual(r1.read_bytes(), original_bad_gzip)

        with (output_dir / "sample_summary.csv").open(encoding="utf-8", newline="") as handle:
            row = next(row for row in csv.DictReader(handle) if row["sample_id"] == "CORRUPT")
        self.assertEqual(row["r1_file_valid"], "no")
        self.assertEqual(row["qc_classification"], FAIL)
        self.assertIn("gzip", row["problems"])
        payload = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
        sample = next(
            sample for sample in payload["samples"] if sample["sample_id"] == "CORRUPT"
        )
        self.assertFalse(sample["r1"]["valid"])
        self.assertEqual(sample["fastqc"]["r1"]["availability"], "available")
        self.assertEqual(sample["classification"]["status"], FAIL)
        html = (output_dir / "report.html").read_text(encoding="utf-8")
        html_payload = embedded_html_payload(html)
        self.assertEqual(
            html_payload["samples"][0]["classification"]["status"], FAIL
        )


if __name__ == "__main__":
    unittest.main()
