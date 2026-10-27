#!/usr/bin/env python3
"""Benchmark the streaming FASTQ scanner on a synthetic file.

The scanner never retains reads.  This script reports elapsed time, throughput,
and traced peak memory so the streaming behaviour can be checked on large
inputs without relying on the ordinary test suite.

Run from an installed environment:

    python scripts/benchmark.py --reads 500000 --length 150 --gzip

Or directly from a source checkout:

    PYTHONPATH=src python3 scripts/benchmark.py --reads 500000 --length 150 --gzip
"""

from __future__ import annotations

import argparse
import tempfile
import time
import tracemalloc
from collections.abc import Iterator
from pathlib import Path

from microbiome_qc.fastq import scan_fastq
from microbiome_qc.synthetic import write_fastq


def _records(reads: int, length: int) -> Iterator[tuple[str, str, str]]:
    sequence = ("ACGT" * (length // 4 + 1))[:length]
    quality = "I" * length
    for index in range(reads):
        yield f"@benchmark{index}", sequence, quality


def _mebibytes(value: int | float) -> float:
    return value / (1024 * 1024)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure streaming FASTQ scan throughput and peak memory.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--reads", type=int, default=200_000, help="number of synthetic reads")
    parser.add_argument("--length", type=int, default=150, help="read length in bases")
    parser.add_argument("--gzip", action="store_true", help="write and scan a .fastq.gz file")
    args = parser.parse_args(argv)
    if args.reads < 1:
        parser.error("--reads must be at least 1")
    if args.length < 1:
        parser.error("--length must be at least 1")

    suffix = ".fastq.gz" if args.gzip else ".fastq"
    with tempfile.TemporaryDirectory(prefix="microbiome-qc-benchmark-") as temporary:
        path = Path(temporary) / f"benchmark{suffix}"
        started = time.perf_counter()
        write_fastq(path, _records(args.reads, args.length))
        generation_seconds = time.perf_counter() - started
        file_size = path.stat().st_size

        tracemalloc.start()
        started = time.perf_counter()
        result = scan_fastq(path)
        scan_seconds = time.perf_counter() - started
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    reads_per_second = result.stats.total_reads / scan_seconds if scan_seconds else 0.0
    megabytes_per_second = _mebibytes(file_size) / scan_seconds if scan_seconds else 0.0
    print("Synthetic FASTQ benchmark")
    print(f"  reads                 {args.reads:,}")
    print(f"  read length           {args.length} bp")
    print(f"  compression           {'gzip' if args.gzip else 'none'}")
    print(f"  file size             {_mebibytes(file_size):.2f} MiB")
    print(f"  fixture generation    {generation_seconds:.3f} s")
    print(f"  scan time             {scan_seconds:.3f} s")
    print(f"  throughput            {reads_per_second:,.0f} reads/s")
    print(f"  input throughput      {megabytes_per_second:.2f} MiB/s")
    print(f"  traced peak memory    {_mebibytes(peak):.3f} MiB")
    print(f"  total reads           {result.stats.total_reads:,}")
    print(f"  total bases           {result.stats.total_bases:,}")
    print(f"  GC percent            {result.stats.gc_percent:.2f}%")
    print(f"  valid                 {result.valid}")
    if not result.valid:
        for error in result.errors:
            print(f"  error                 {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
