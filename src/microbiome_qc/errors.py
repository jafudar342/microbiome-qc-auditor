"""Exception types shared across the application."""

from __future__ import annotations


class MicrobiomeQCError(Exception):
    """Base class for expected, user-actionable application errors."""


class DiscoveryError(MicrobiomeQCError):
    """The FASTQ directory or a naming operation could not be completed."""


class FastQCError(MicrobiomeQCError):
    """The FastQC report directory cannot be read."""


class AuditError(MicrobiomeQCError):
    """The audit cannot proceed or cannot produce trustworthy evidence."""


class OutputError(MicrobiomeQCError):
    """Report output was refused or could not be written completely."""


class DemoError(MicrobiomeQCError):
    """The synthetic demo dataset could not be created safely."""
