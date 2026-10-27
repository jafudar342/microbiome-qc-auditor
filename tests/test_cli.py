from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from microbiome_qc import __version__
from microbiome_qc.cli import (
    EXIT_AUDIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    EXIT_WARN_GATE,
    main,
)
from tests.helpers import simple_pair, write_fastq, write_fastqc_for_fastq


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        self.fastq_dir = self.root / "FASTQ"
        self.fastqc_dir = self.root / "FastQC"
        self.fastq_dir.mkdir()
        self.fastqc_dir.mkdir()

    def tearDown(self) -> None:
        self._temp.cleanup()

    def run_main(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def create_clean(self, sample: str = "SAMPLE", *, with_fastqc: bool = True) -> None:
        r1, r2 = simple_pair(self.fastq_dir, sample=sample, count=3)
        if with_fastqc:
            write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=3)
            write_fastqc_for_fastq(self.fastqc_dir, r2.name, total_sequences=3)

    def create_warn_only(self) -> None:
        r1, _r2 = simple_pair(self.fastq_dir, sample="WARNS", count=3)
        write_fastqc_for_fastq(self.fastqc_dir, r1.name, total_sequences=3)

    def create_failing(self) -> None:
        _r1, r2 = simple_pair(self.fastq_dir, sample="BROKEN", count=3)
        write_fastq(
            r2,
            [("@read1/2", "ACGT", "IIII")],
            trailing=b"@read2/2\nACGT\n+\n",
        )

    def audit_args(self, output: Path, *extra: str) -> list[str]:
        return [
            "audit",
            "--fastq-dir",
            str(self.fastq_dir),
            "--output-dir",
            str(output),
            *extra,
        ]

    def test_clean_audit_exits_zero_and_writes_reports(self) -> None:
        self.create_clean()
        output = self.root / "report"
        code, stdout, stderr = self.run_main(
            self.audit_args(output, "--fastqc-dir", str(self.fastqc_dir))
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("PASS=1 WARN=0 FAIL=0", stdout)
        self.assertIn("Reports written to", stdout)
        self.assertEqual(stderr, "")
        for name in ("sample_summary.csv", "fastqc_modules.csv", "summary.json", "report.html"):
            self.assertTrue((output / name).is_file(), name)

    def test_failing_sample_exits_one(self) -> None:
        self.create_failing()
        output = self.root / "report"
        code, stdout, stderr = self.run_main(self.audit_args(output))
        self.assertEqual(code, EXIT_AUDIT_FAILURE)
        self.assertIn("FAIL=1", stdout)
        self.assertIn("FAIL samples: BROKEN", stderr)
        self.assertTrue((output / "summary.json").is_file())

    def test_warn_gate_exit_code(self) -> None:
        self.create_warn_only()
        normal_output = self.root / "normal"
        code, stdout, _stderr = self.run_main(
            self.audit_args(normal_output, "--fastqc-dir", str(self.fastqc_dir))
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("WARN=1", stdout)

        gated_output = self.root / "gated"
        code, _stdout, stderr = self.run_main(
            self.audit_args(
                gated_output,
                "--fastqc-dir",
                str(self.fastqc_dir),
                "--fail-on-warn",
            )
        )
        self.assertEqual(code, EXIT_WARN_GATE)
        self.assertIn("--fail-on-warn", stderr)
        self.assertTrue((gated_output / "summary.json").is_file())

    def test_input_error_exits_two(self) -> None:
        self.create_clean(with_fastqc=False)
        output = self.root / "report"
        code, _stdout, stderr = self.run_main(
            self.audit_args(output, "--fastqc-dir", str(self.root / "absent"))
        )
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("FastQC directory does not exist", stderr)
        self.assertFalse(output.exists())

    def test_existing_reports_require_explicit_overwrite(self) -> None:
        self.create_clean()
        output = self.root / "report"
        args = self.audit_args(output, "--fastqc-dir", str(self.fastqc_dir))
        self.assertEqual(self.run_main(args)[0], EXIT_SUCCESS)
        before = (output / "summary.json").read_bytes()

        code, _stdout, stderr = self.run_main(args)
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("--overwrite", stderr)
        self.assertEqual((output / "summary.json").read_bytes(), before)

        code, _stdout, _stderr = self.run_main([*args, "--overwrite"])
        self.assertEqual(code, EXIT_SUCCESS)

    def test_invalid_max_errors_is_a_usage_error(self) -> None:
        self.create_clean()
        stdout = io.StringIO()
        stderr = io.StringIO()
        with self.assertRaises(SystemExit) as caught:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                main(
                    [
                        *self.audit_args(self.root / "report"),
                        "--max-errors",
                        "0",
                    ]
                )
        self.assertEqual(caught.exception.code, 2)
        self.assertIn("at least 1", stderr.getvalue())

    def test_version_and_help_exit_zero(self) -> None:
        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as caught:
            with redirect_stdout(stdout):
                main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn(__version__, stdout.getvalue())

        stdout = io.StringIO()
        with self.assertRaises(SystemExit) as caught:
            with redirect_stdout(stdout):
                main(["--help"])
        self.assertEqual(caught.exception.code, 0)
        help_text = stdout.getvalue()
        self.assertIn("audit", help_text)
        self.assertIn("demo", help_text)
        self.assertIn("self-test", help_text)
        self.assertIn("exit codes", help_text)

    def test_no_command_is_a_usage_error(self) -> None:
        code, _stdout, stderr = self.run_main([])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("usage:", stderr)

    def test_verbose_logging_reports_discovery(self) -> None:
        self.create_clean()
        output = self.root / "report"
        code, _stdout, stderr = self.run_main(
            self.audit_args(output, "--fastqc-dir", str(self.fastqc_dir), "-v")
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("Discovered 1 sample candidate", stderr)
        self.assertIn("Sample SAMPLE: PASS", stderr)

    def test_self_test_commands(self) -> None:
        code, stdout, _stderr = self.run_main(["--self-test"])
        self.assertEqual(code, 0)
        self.assertIn("Self-test: 6/6 checks passed", stdout)

        code, stdout, _stderr = self.run_main(["self-test"])
        self.assertEqual(code, 0)
        self.assertIn("Self-test: 6/6 checks passed", stdout)

    def test_demo_command_and_demo_audit(self) -> None:
        demo_dir = self.root / "demo"
        code, stdout, _stderr = self.run_main(["demo", "--output-dir", str(demo_dir)])
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("7 synthetic samples", stdout)
        self.assertTrue((demo_dir / "FASTQ").is_dir())
        self.assertTrue((demo_dir / "FastQC").is_dir())
        self.assertTrue((demo_dir / "README.md").is_file())

        code, stdout, _stderr = self.run_main(
            [
                "audit",
                "--fastq-dir",
                str(demo_dir / "FASTQ"),
                "--fastqc-dir",
                str(demo_dir / "FastQC"),
                "--output-dir",
                str(demo_dir / "QC_Report"),
            ]
        )
        self.assertEqual(code, EXIT_AUDIT_FAILURE)
        self.assertIn("PASS=1 WARN=3 FAIL=3", stdout)

        code, _stdout, _stderr = self.run_main(
            [
                "audit",
                "--fastq-dir",
                str(demo_dir / "FASTQ"),
                "--fastqc-dir",
                str(demo_dir / "FastQC"),
                "--output-dir",
                str(demo_dir / "QC_Gated"),
                "--fail-on-warn",
            ]
        )
        self.assertEqual(code, EXIT_AUDIT_FAILURE)

    def test_demo_refuses_nonempty_directory_without_overwrite(self) -> None:
        demo_dir = self.root / "demo"
        demo_dir.mkdir()
        (demo_dir / "keep.txt").write_text("user data", encoding="utf-8")
        code, _stdout, stderr = self.run_main(["demo", "--output-dir", str(demo_dir)])
        self.assertEqual(code, EXIT_USAGE)
        self.assertIn("--overwrite", stderr)
        self.assertEqual((demo_dir / "keep.txt").read_text(encoding="utf-8"), "user data")


if __name__ == "__main__":
    unittest.main()
