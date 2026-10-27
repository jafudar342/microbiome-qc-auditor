"""Performance-oriented check: large input must stream through bounded memory.

The ordinary suite stays fast (roughly half a second for this module); the
standalone ``scripts/benchmark.py`` can be used for larger measurements.
"""

from __future__ import annotations

import tempfile
import time
import tracemalloc
import unittest
from pathlib import Path

from microbiome_qc.fastq import scan_fastq
from microbiome_qc.synthetic import write_fastq

READ_COUNT = 50_000
READ_LENGTH = 100
MEMORY_LIMIT_BYTES = 8 * 1024 * 1024


class PerformanceTests(unittest.TestCase):
    def test_large_fastq_is_scanned_with_bounded_memory(self) -> None:
        sequence = ("ACGT" * (READ_LENGTH // 4 + 1))[:READ_LENGTH]
        quality = "I" * READ_LENGTH

        def records():
            for index in range(READ_COUNT):
                yield f"@perf{index}", sequence, quality

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "large.fastq"
            write_fastq(path, records())
            self.assertGreater(path.stat().st_size, 10 * 1024 * 1024)

            tracemalloc.start()
            started = time.perf_counter()
            result = scan_fastq(path)
            elapsed = time.perf_counter() - started
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.stats.total_reads, READ_COUNT)
        self.assertEqual(result.stats.total_bases, READ_COUNT * READ_LENGTH)
        self.assertEqual(result.stats.min_length, READ_LENGTH)
        self.assertEqual(result.stats.max_length, READ_LENGTH)
        self.assertEqual(result.stats.gc_percent, 50.0)
        self.assertLess(
            peak,
            MEMORY_LIMIT_BYTES,
            f"streaming scan peaked at {peak / 1024 / 1024:.2f} MiB",
        )
        self.assertLess(elapsed, 30.0, "streaming scan was unexpectedly slow")


if __name__ == "__main__":
    unittest.main()
