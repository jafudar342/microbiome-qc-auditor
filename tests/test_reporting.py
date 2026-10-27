from __future__ import annotations

import csv
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from microbiome_qc.audit import AuditOptions, run_audit
from microbiome_qc.errors import OutputError
from microbiome_qc.reporting import REPORT_FILENAMES
from tests.helpers import (
    simple_pair,
    statuses,
    write_fastq,
    write_fastqc_for_fastq,
)


class ReportingTests(unittest.TestCase):
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

    def clean_pair(self, sample: str = "SAMPLE", count: int = 3) -> tuple[Path, Path]:
        return simple_pair(self.fastq_dir, sample=sample, count=count)

    def pass_reports(self, r1: Path, r2: Path, count: int = 3) -> None:
        write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=count)
        write_fastqc_for_fastq(self.fastqc_dir, r2.name, total_sequences=count)

    def run_mixed_audit(self):
        alpha_r1, alpha_r2 = self.clean_pair("ALPHA", 3)
        self.pass_reports(alpha_r1, alpha_r2, 3)
        self.clean_pair("BETA", 2)
        gamma_r1, gamma_r2 = self.clean_pair("GAMMA", 3)
        del gamma_r1
        write_fastq(
            gamma_r2,
            [("@read1/2", "ACGT", "IIII"), ("@read2/2", "ACGT", "IIII")],
            trailing=b"@read3/2\nACGT\n+\n",
        )
        return run_audit(self.options(fastqc_dir=self.fastqc_dir))

    def test_all_reports_exist_with_content_and_no_temp_files(self) -> None:
        r1, r2 = self.clean_pair()
        self.pass_reports(r1, r2)
        result = run_audit(self.options(fastqc_dir=self.fastqc_dir))
        written = {path.name for path in self.output_dir.iterdir()}
        self.assertEqual(written, set(REPORT_FILENAMES))
        self.assertEqual({path.name for path in result.outputs}, set(REPORT_FILENAMES))
        for name in REPORT_FILENAMES:
            self.assertGreater((self.output_dir / name).stat().st_size, 0, name)
        self.assertEqual(list(self.output_dir.glob(".*.tmp")), [])

    def test_summary_csv_and_json_are_consistent(self) -> None:
        result = self.run_mixed_audit()
        with (self.output_dir / "sample_summary.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        payload = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(len(rows), 3)
        self.assertEqual({row["sample_id"] for row in rows}, {"ALPHA", "BETA", "GAMMA"})
        self.assertEqual(payload["counts"]["discovered_samples"], 3)
        self.assertEqual(payload["counts"]["pass"], 1)
        self.assertEqual(payload["counts"]["warn"], 1)
        self.assertEqual(payload["counts"]["fail"], 1)
        self.assertEqual(
            [sample["sample_id"] for sample in payload["samples"]],
            ["ALPHA", "BETA", "GAMMA"],
        )

        csv_by_id = {row["sample_id"]: row for row in rows}
        for sample in payload["samples"]:
            row = csv_by_id[sample["sample_id"]]
            self.assertEqual(row["r1_filename"], "; ".join(sample["r1_filenames"]))
            self.assertEqual(row["r2_filename"], "; ".join(sample["r2_filenames"]))
            self.assertEqual(row["qc_classification"], sample["classification"]["status"])
            self.assertEqual(row["pairing_result"], sample["pairing"]["result"])
            self.assertEqual(row["problems"], " | ".join(sample["classification"]["reasons"]))
            for side in ("r1", "r2"):
                scan = sample[side]
                fastqc = sample["fastqc"][side]
                if scan is None:
                    self.assertEqual(row[f"{side}_filename"], "")
                    self.assertEqual(row[f"{side}_reads"], "")
                    self.assertEqual(row[f"{side}_file_valid"], "")
                else:
                    self.assertEqual(row[f"{side}_file_valid"], "yes" if scan["valid"] else "no")
                    self.assertEqual(row[f"{side}_reads"], str(scan["stats"]["total_reads"]))
                    self.assertEqual(row[f"{side}_total_bases"], str(scan["stats"]["total_bases"]))
                    self.assertEqual(
                        row[f"{side}_mean_read_length"],
                        f"{scan['stats']['mean_length']:.2f}",
                    )
                    self.assertEqual(
                        row[f"{side}_gc_percent"],
                        f"{scan['stats']['gc_percent']:.2f}",
                    )
                self.assertEqual(row[f"fastqc_{side}_available"], fastqc["availability"])
                for count_name in ("pass", "warn", "fail"):
                    expected = fastqc[f"{count_name}_count"]
                    self.assertEqual(
                        row[f"fastqc_{side}_{count_name}"],
                        "" if expected is None else str(expected),
                    )
        statuses_from_csv = [row["qc_classification"] for row in rows]
        self.assertEqual(statuses_from_csv.count("PASS"), 1)
        self.assertEqual(statuses_from_csv.count("WARN"), 1)
        self.assertEqual(statuses_from_csv.count("FAIL"), 1)

    def test_summary_json_metadata_and_limitations(self) -> None:
        r1, r2 = self.clean_pair()
        self.pass_reports(r1, r2)
        result = run_audit(self.options(fastqc_dir=self.fastqc_dir))
        payload = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))

        parsed = datetime.fromisoformat(payload["audit_timestamp"])
        self.assertIsNotNone(parsed.tzinfo)
        self.assertIsNotNone(parsed.utcoffset())
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["tool"]["name"], "microbiome-qc-auditor")
        self.assertTrue(payload["tool"]["version"])
        self.assertEqual(payload["input_paths"]["fastq_dir"], str(self.fastq_dir.resolve()))
        self.assertEqual(payload["input_paths"]["fastqc_dir"], str(self.fastqc_dir.resolve()))
        self.assertEqual(payload["output_paths"]["output_dir"], str(self.output_dir.resolve()))
        self.assertEqual(
            set(payload["output_paths"]["files"]),
            {"sample_summary_csv", "fastqc_modules_csv", "summary_json", "report_html"},
        )
        self.assertTrue(payload["configuration"]["fastqc_requested"])
        self.assertEqual(payload["configuration"]["gc_denominator"], "A+C+G+T")
        self.assertEqual(payload["counts"]["missing_fastqc_reports"], 0)
        self.assertEqual(payload["counts"]["orphaned_reads"], 0)
        limitations = " ".join(payload["limitations"])
        self.assertIn("(G + C) / (A + C + G + T)", limitations)
        self.assertIn("FastQC", limitations)
        self.assertIn("limited to", limitations)
        self.assertEqual(payload["samples"][0]["classification"]["status"], "PASS")
        self.assertEqual(result.pass_count, 1)

    def test_fastqc_modules_csv_matches_actual_reports(self) -> None:
        a1, a2 = self.clean_pair("ALPHA", 3)
        self.pass_reports(a1, a2, 3)
        b1, b2 = self.clean_pair("BETA", 3)
        write_fastqc_for_fastq(
            self.fastqc_dir,
            b1.name,
            status_map=statuses(Per_base_sequence_quality="WARN"),
            total_sequences=3,
        )
        write_fastqc_for_fastq(
            self.fastqc_dir,
            b2.name,
            status_map=statuses(Adapter_Content="FAIL"),
            total_sequences=3,
        )
        run_audit(self.options(fastqc_dir=self.fastqc_dir))
        with (self.output_dir / "fastqc_modules.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        payload = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))

        self.assertEqual(len(rows), 44)
        by_side = {}
        for row in rows:
            by_side.setdefault((row["sample_id"], row["read_direction"]), []).append(row)
            self.assertTrue(Path(row["fastqc_path"]).is_file())
            self.assertIn(row["status"], {"PASS", "WARN", "FAIL"})
        self.assertEqual(len(by_side), 4)
        for key, module_rows in by_side.items():
            self.assertEqual(len(module_rows), 11)
            sample_id, side = key
            json_side = next(
                sample
                for sample in payload["samples"]
                if sample["sample_id"] == sample_id
            )["fastqc"][side.lower()]
            expected = json_side["report"]["modules"]
            self.assertEqual(
                [(row["module"], row["status"]) for row in module_rows],
                [(module["module"], module["status"]) for module in expected],
            )
            self.assertEqual({row["fastqc_report"] for row in module_rows}, {json_side["report"]["report_name"]})
        beta_r2 = by_side[("BETA", "R2")]
        adapter = [row for row in beta_r2 if row["module"] == "Adapter Content"]
        self.assertEqual(adapter[0]["status"], "FAIL")

    def test_missing_fastqc_evidence_is_distinct_from_passing_modules(self) -> None:
        r1, r2 = self.clean_pair()
        write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=3)
        run_audit(self.options(fastqc_dir=self.fastqc_dir))
        payload = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))
        with (self.output_dir / "sample_summary.csv").open(encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
        sample = payload["samples"][0]
        self.assertEqual(sample["classification"]["status"], "WARN")
        self.assertEqual(sample["fastqc"]["r1"]["availability"], "available")
        self.assertEqual(sample["fastqc"]["r2"]["availability"], "missing")
        self.assertIsNone(sample["fastqc"]["r2"]["pass_count"])
        self.assertIsNone(sample["fastqc"]["r2"]["report"])
        self.assertEqual(row["fastqc_r2_available"], "missing")
        self.assertEqual(row["fastqc_r2_pass"], "")
        self.assertEqual(row["fastqc_r2_warn"], "")
        self.assertEqual(row["fastqc_r2_fail"], "")
        self.assertEqual(len(payload["missing_fastqc_reports"]), 1)
        self.assertEqual(payload["missing_fastqc_reports"][0]["read_direction"], "R2")
        with (self.output_dir / "fastqc_modules.csv").open(encoding="utf-8", newline="") as handle:
            modules = list(csv.DictReader(handle))
        self.assertEqual(len(modules), 11)
        self.assertTrue(all(module["read_direction"] == "R1" for module in modules))

    def test_no_fastqc_requested_yields_header_only_module_csv(self) -> None:
        self.clean_pair()
        run_audit(self.options())
        with (self.output_dir / "fastqc_modules.csv").open(encoding="utf-8", newline="") as handle:
            modules = list(csv.DictReader(handle))
        self.assertEqual(modules, [])
        payload = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertFalse(payload["fastqc_requested"])
        self.assertEqual(payload["samples"][0]["fastqc"]["r1"]["availability"], "not_requested")
        self.assertEqual(payload["missing_fastqc_reports"], [])

    def test_existing_outputs_are_never_silently_overwritten(self) -> None:
        r1, r2 = self.clean_pair()
        self.pass_reports(r1, r2)
        options = self.options(fastqc_dir=self.fastqc_dir)
        run_audit(options)
        before = {
            name: (self.output_dir / name).read_bytes() for name in REPORT_FILENAMES
        }
        with self.assertRaises(OutputError) as caught:
            run_audit(options)
        self.assertIn("--overwrite", str(caught.exception))
        for name in REPORT_FILENAMES:
            self.assertEqual((self.output_dir / name).read_bytes(), before[name])

    def test_explicit_overwrite_replaces_reports(self) -> None:
        r1, r2 = self.clean_pair()
        self.pass_reports(r1, r2)
        run_audit(self.options(fastqc_dir=self.fastqc_dir))
        first = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(first["counts"]["discovered_samples"], 1)

        self.clean_pair("SECOND", 2)
        result = run_audit(self.options(fastqc_dir=self.fastqc_dir, overwrite=True))
        second = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(result.sample_count, 2)
        self.assertEqual(second["counts"]["discovered_samples"], 2)
        with (self.output_dir / "sample_summary.csv").open(encoding="utf-8", newline="") as handle:
            self.assertEqual(len(list(csv.DictReader(handle))), 2)

    def test_output_file_occupied_by_directory_is_rejected(self) -> None:
        self.clean_pair()
        self.output_dir.mkdir()
        (self.output_dir / "report.html").mkdir()
        with self.assertRaises(OutputError) as caught:
            run_audit(self.options())
        self.assertIn("directories", str(caught.exception))
        self.assertFalse((self.output_dir / "sample_summary.csv").exists())

    def test_output_path_that_is_a_file_is_rejected(self) -> None:
        self.clean_pair()
        output_file = self.root / "not-a-directory"
        output_file.write_text("occupied", encoding="utf-8")
        with self.assertRaises(OutputError):
            run_audit(self.options(output_dir=output_file))

    def test_html_escapes_untrusted_names_and_is_self_contained(self) -> None:
        malicious = 'EVIL<img src=x onerror=alert(1)> & "quoted", sample'
        self.clean_pair(malicious, 2)
        run_audit(self.options())
        html = (self.output_dir / "report.html").read_text(encoding="utf-8")

        self.assertNotIn("<img src=x", html)
        self.assertNotIn("</script><script>alert", html)
        self.assertIn("\\u003cimg src=x onerror=alert(1)\\u003e", html)
        self.assertIn("\\u0026", html)
        self.assertIn("default-src 'none'", html)
        self.assertIn('id="search-input"', html)
        self.assertIn('id="status-filter"', html)
        self.assertIn('id="fastqc-filter"', html)
        self.assertIn('id="sample-dialog"', html)
        self.assertNotIn("<link", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("http://", html.lower())
        self.assertNotIn("https://", html.lower())
        self.assertIn("<style>", html)
        self.assertIn("<script>", html)

        marker = '<script type="application/json" id="audit-data">'
        start = html.index(marker) + len(marker)
        end = html.index("</script>", start)
        payload = json.loads(html[start:end])
        self.assertEqual(payload["samples"][0]["sample_id"], malicious)
        with (self.output_dir / "sample_summary.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["sample_id"], malicious)
        self.assertEqual(rows[0]["qc_classification"], "PASS")

    def test_payload_retains_structural_and_pairing_errors(self) -> None:
        r1, r2 = self.clean_pair()
        write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=3)
        write_fastqc_for_fastq(self.fastqc_dir, r2.name, total_sequences=3)
        write_fastq(
            r2,
            [
                ("@read1/2", "ACGT", "IIII"),
                ("@wrong/2", "ACGT", "IIII"),
                ("@read3/2", "ACGT", "IIII"),
            ],
        )
        run_audit(self.options(fastqc_dir=self.fastqc_dir))
        payload = json.loads((self.output_dir / "summary.json").read_text(encoding="utf-8"))
        pairing = payload["samples"][0]["pairing"]
        self.assertEqual(pairing["result"], "FAIL")
        self.assertEqual(pairing["mismatch_count"], 1)
        self.assertEqual(pairing["mismatches"][0]["record_number"], 2)
        self.assertIn("record 2", pairing["details"])
        html = (self.output_dir / "report.html").read_text(encoding="utf-8")
        marker = '<script type="application/json" id="audit-data">'
        start = html.index(marker) + len(marker)
        end = html.index("</script>", start)
        html_payload = json.loads(html[start:end])
        self.assertEqual(
            html_payload["samples"][0]["pairing"]["mismatches"][0]["record_number"], 2
        )


if __name__ == "__main__":
    unittest.main()
