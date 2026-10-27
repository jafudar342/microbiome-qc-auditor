"""Microbiome QC Auditor: offline integrity and FastQC audit for paired FASTQ files."""

from importlib.metadata import PackageNotFoundError, version

TOOL_NAME = "microbiome-qc-auditor"

try:
    __version__ = version(TOOL_NAME)
except PackageNotFoundError:  # Running directly from a source checkout.
    __version__ = "1.0.0"

__all__ = ["TOOL_NAME", "__version__"]
