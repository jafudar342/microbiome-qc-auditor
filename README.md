# Microbiome QC Auditor

An offline, command-line quality-control auditor for paired-end FASTQ files and
FastQC ZIP reports. It discovers R1/R2 mates, streams each file to verify its
four-line structure, compares mate identifiers, reads the module statuses that
FastQC actually reported, and produces deterministic CSV, JSON, and
self-contained HTML reports.

The tool is intended to help decide **which sequencing files need attention
before downstream microbiome analysis**. It does not diagnose disease, infer
breast-cancer status, assign biological meaning, or make clinical claims.

## What it does

- Discovers paired `.fastq`, `.fq`, `.fastq.gz`, and `.fq.gz` files with
  `_R1/_R2`, `_1/_2`, and `_R1_001/_R2_001`-style names.
- Flags orphaned mates, ambiguous duplicate candidates, unsupported files, and
  unrecognized names with actionable messages.
- Streams FASTQ files without retaining reads; validates headers, separators,
  sequence/quality lengths, printable quality characters, record completeness,
  and gzip readability.
- Computes read count, bases, min/max/mean read length, and GC percentage.
- Compares R1/R2 read counts and normalized read identifiers with a bounded
  number of detailed mismatch examples.
- Parses real FastQC `summary.txt` module statuses from `*_fastqc.zip` archives
  without running FastQC and without extracting the archives.
- Distinguishes a missing, invalid, ambiguous, or unrequested FastQC report from
  a report that was present and passed.
- Classifies each sample PASS/WARN/FAIL with documented precedence, then writes:
  - `sample_summary.csv`
  - `fastqc_modules.csv`
  - `summary.json`
  - `report.html`
- Refuses to overwrite reports without `--overwrite`; never modifies or deletes
  input FASTQ/FastQC files.

## Requirements

- Linux
- Python 3.11 or newer
- No runtime third-party packages, network access, database, container, or
  external service
- Optional FastQC ZIP reports; the FastQC executable itself is **not** needed

## Installation

Clone or copy the repository, then create a virtual environment.

### Standard install

```bash
cd /path/to/microbiome-qc-auditor
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
microbiome-qc --version
microbiome-qc --self-test
```

### Fully offline install

The application has no runtime dependencies, but `pip` normally needs the
setuptools build backend to install a local package. On an air-gapped Linux
system with system setuptools available, this verified recipe installs without
contacting a package index:

```bash
cd /path/to/microbiome-qc-auditor
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
python -m pip install --no-index --no-build-isolation -e .
microbiome-qc --version
microbiome-qc --self-test
```

If setuptools is not available at all, the application still runs directly from
the source tree with no installation:

```bash
PYTHONPATH=src python3 -m microbiome_qc --version
PYTHONPATH=src python3 -m microbiome_qc --self-test
PYTHONPATH=src python3 -m microbiome_qc audit --help
```

All commands in the rest of this document work with the installed
`microbiome-qc` command. The equivalent source-tree form is
`python3 -m microbiome_qc` with `PYTHONPATH=src`.

## Quick start with synthetic data

Generate a seven-sample demo dataset locally. It contains only synthetic reads
and synthetic FastQC archives; nothing is downloaded.

```bash
microbiome-qc demo --output-dir ./demo_data
microbiome-qc audit \
  --fastq-dir ./demo_data/FASTQ \
  --fastqc-dir ./demo_data/FastQC \
  --output-dir ./demo_data/QC_Report
echo "exit code: $?"
```

The demo deterministically contains **1 PASS, 3 WARN, and 3 FAIL** samples. The
audit command exits with **1** because three samples have structural or pairing
failures. That is the expected, correct result for this deliberately mixed demo.

Open `demo_data/QC_Report/report.html` directly in a local browser. It works
from `file://`; no web server is required.

If the demo directory already exists, either choose a new `--output-dir` or pass
`--overwrite` to the `demo` command explicitly.

## Usage

Audit real paired FASTQ files:

```bash
python -m microbiome_qc audit \
  --fastq-dir ./FASTQ \
  --fastqc-dir ./FastQC \
  --output-dir ./QC_Report
```

Audit without FastQC evidence:

```bash
python -m microbiome_qc audit \
  --fastq-dir ./FASTQ \
  --output-dir ./QC_Report_no_fastqc
```

Require a nonzero exit for nonfatal warnings in a pipeline, retain at most three
examples of each detailed mismatch, and replace existing reports explicitly:

```bash
python -m microbiome_qc audit \
  --fastq-dir ./FASTQ \
  --fastqc-dir ./FastQC \
  --output-dir ./QC_Report \
  --max-errors 3 \
  --fail-on-warn \
  --overwrite
```

Enable INFO or DEBUG logging with `-v` or `-vv` (placed after the `audit`
subcommand):

```bash
python -m microbiome_qc audit \
  --fastq-dir ./FASTQ \
  --fastqc-dir ./FastQC \
  --output-dir ./QC_Report \
  -v
```

### `audit` options

| Option | Meaning |
| --- | --- |
| `--fastq-dir PATH` | Required. Directory directly containing FASTQ files; discovery is non-recursive. |
| `--fastqc-dir PATH` | Optional. Directory containing `*_fastqc.zip` archives. |
| `--output-dir PATH` | Required. Directory to receive the four report files. |
| `--max-errors N` | Maximum detailed pairing mismatches and malformed FastQC rows retained per file/report; also limits console warnings. Default `5`; must be at least 1. |
| `--overwrite` | Explicitly permit replacing existing report files. Without it, existing reports cause exit code 2. |
| `--fail-on-warn` | Exit 3 after a completed audit if any sample is WARN and no sample failed. A FAIL still exits 1. |
| `-v`, `-vv` | INFO or DEBUG logging on stderr. |
| `--version`, `--help` | Print version/help and exit 0. |

Other commands:

| Command | Meaning |
| --- | --- |
| `microbiome-qc demo --output-dir DIR [--overwrite]` | Generate the local synthetic demo dataset. |
| `microbiome-qc self-test` | Run built-in temporary-directory checks. |
| `microbiome-qc --self-test` | Same self-test via the top-level flag. |

The self-test never touches research data. It checks FASTQ statistics,
identifier normalization, corruption detection, FastQC parsing, classification
precedence, and an end-to-end report write.

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Audit completed; at least one sample was discovered and no sample is FAIL. With `--fail-on-warn`, this also requires no WARN samples. |
| `1` | Audit completed and wrote reports, but at least one sample is FAIL. |
| `2` | Usage, input, discovery, FastQC, or output error. Recoverable details are printed to stderr; reports must not be treated as complete. |
| `3` | Audit completed with no FAIL but at least one WARN while `--fail-on-warn` is set. |

FAIL takes precedence over the warning gate. A run that cannot write all four
reports never reports success.

## Input names and pairing

Supported extensions, matched case-insensitively:

```text
.fastq.gz    .fq.gz    .fastq    .fq
```

Supported read-marker forms:

```text
SRR123456_1.fastq.gz      SRR123456_2.fastq.gz
SRR123456_R1.fastq.gz     SRR123456_R2.fastq.gz
SRR123456_R1_001.fastq.gz SRR123456_R2_001.fastq.gz
sample_R1.fq              sample_R2.fq
```

Pairing rules:

- Read markers and extensions are matched **case-insensitively**.
- Sample identifiers are compared **case-sensitively**. `SampleA` and `samplea`
  are different samples and are never silently merged.
- Discovery is **non-recursive**. Put FASTQ files directly in `--fastq-dir`.
- Exactly one R1 and one R2 file form a complete sample.
- One side without the other is an **orphan** and classifies as FAIL.
- More than one candidate for either side is **ambiguous** and classifies as
  FAIL. All candidates are retained in the reports; none is chosen arbitrarily.
- Files with unsupported extensions or names that do not contain a recognized
  read marker are reported as ignored/unrecognized. They are not audited.
- Sample ordering and file ordering are deterministic.

If the input naming does not match one of these conventions, rename the files or
run the audit on a directory containing correctly named pairs. The tool does not
guess arbitrary filename pairing.

## FASTQ validation and statistics

Every candidate file is streamed as four-line records. No complete file or read
collection is held in memory.

Checked per record:

- Header exists and begins with `@`.
- Header contains a non-empty identifier.
- Separator line begins with `+`.
- Sequence is non-empty.
- Sequence and quality lengths are equal.
- Quality characters are printable ASCII from `!` (33) through `~` (126).
- The final record is complete (header, sequence, separator, quality).
- Gzip data can be decompressed without error.

CRLF line endings and a missing final newline are accepted. A scan stops at the
first structural error to avoid misleading cascades after record boundaries are
lost; statistics for an invalid file are partial and are reported as such.

For valid files the reports contain:

- Total reads.
- Total bases.
- Minimum, maximum, and mean read length. Mean length is rounded to 2 decimal
  places.
- GC percentage, defined as `(G + C) / (A + C + G + T) * 100`. `N` and other
  symbols are excluded from the denominator. If no A/C/G/T bases exist, GC is
  reported as `0.00`.

Pairing is a separate streaming pass over the two valid mates:

- Read counts must match.
- Read identifiers at corresponding positions must match after normalizing a
  trailing `/1` or `/2` and the first whitespace token.
- Standard Illumina comment direction tokens (`1:N:0:1`, `2:N:0:1`, etc.) are
  checked as read directions.
- Swapped read directions are reported explicitly.
- All mismatches are counted; only the first `--max-errors` examples are
  retained and displayed.
- If either mate failed structural validation, pairing is marked
  `NOT_CHECKED`; it is never reported as PASS.

## FastQC integration

`--fastqc-dir` should directly contain FastQC ZIP archives named like:

```text
SAMPLE_R1_fastqc.zip
SAMPLE_R2_fastqc.zip
```

The report is associated with a sample/read side using the archive name first;
if that is not possible, the original FASTQ filename recorded inside the report
is used. The tool reads archives in place with Python’s `zipfile`; it never
extracts or executes them. The FastQC executable is not required.

From each archive it reads:

- `summary.txt` rows (`STATUS<TAB>module<TAB>input filename`) to collect actual
  module-level PASS/WARN/FAIL results.
- The `Basic Statistics` `Total Sequences` value from `fastqc_data.txt` for a
  FastQC read-count comparison.

Important evidence rules:

- A module that is absent from `summary.txt` is **not** assumed to be PASS. It is
  simply absent, and module counts reflect only actual rows.
- A missing `summary.txt` makes the report unavailable.
- A malformed row is reported while valid rows from the same archive survive.
- A missing `fastqc_data.txt` leaves actual module statuses usable but makes the
  FastQC read count unavailable and adds a warning.
- Invalid ZIPs, duplicate archives for one sample/side, conflicting archive and
  internal filenames, and reports for unknown samples or missing FASTQ mates are
  reported explicitly.
- Missing is distinct from not requested: `available`, `missing`, `invalid`,
  `ambiguous`, `not_requested`, `not_applicable`, and `not_assessed` are
  separate availability states in CSV, JSON, and HTML.
- No missing evidence is converted into PASS.

Only zipped FastQC reports are supported. Uncompressed FastQC output directories
are ignored; the report states this limitation.

## Classification

The rules live in one tested module and are applied deterministically:

| Classification | Conditions |
| --- | --- |
| **FAIL** | Any structural or pairing problem: invalid/truncated/unreadable/empty FASTQ, missing mate, ambiguous file pairing, unequal mate read counts, or paired identifier/direction mismatch. FAIL overrides every FastQC result. |
| **WARN** | No structural/pairing problem, but at least one FastQC concern: module WARN or FAIL, missing/invalid/ambiguous report, malformed report evidence, unavailable FastQC read count, or FastQC read count disagreeing with the FASTQ scan. |
| **PASS** | No detected structural/pairing problem and no FastQC concern. |

A **FastQC module FAIL produces a sample WARN**, not a sample FAIL. FastQC’s
module calculations are QC findings; sample FAIL is reserved for FASTQ
integrity/pairing problems. The original module FAIL is preserved in
`fastqc_modules.csv` and `summary.json`.

When no FastQC directory is supplied, FastQC availability is `not_requested`.
PASS then means “no structural or pairing problem detected”, **not** “fully
validated by FastQC”. The limitation is stated in the JSON and HTML.

A sample with a structural error is never PASS, even when its FastQC report is
all PASS.

## Output artifacts

Each successful audit writes exactly four files to `--output-dir` (unless
pre-existing unrelated files are present, which are left untouched):

### `sample_summary.csv`

One row per discovered sample, with columns for:

- Sample ID.
- R1 and R2 filenames.
- Per-side scan validity, read counts, total bases, mean read length, and GC
  percentage.
- Pairing result (`PASS`, `FAIL`, `MISSING_MATE`, `AMBIGUOUS`, `NOT_CHECKED`) and
  detailed pairing evidence.
- Per-side FastQC availability and actual PASS/WARN/FAIL module counts. Counts
  are blank when module evidence is unavailable; blank is not zero/PASS.
- Overall QC classification.
- Concise detected problems.

### `fastqc_modules.csv`

One row per sample, read direction, and discovered FastQC module. Columns are
sample ID, read direction, FastQC report name, source ZIP path, module name, and
actual module status. Samples/sides without usable module evidence contribute no
rows.

### `summary.json`

Machine-readable evidence, including:

- Schema version and ISO 8601 audit timestamp with UTC timezone.
- Tool name/version.
- Resolved input and output paths.
- Full audit configuration.
- Counts of discovered samples, PASS/WARN/FAIL, missing FastQC reports, orphaned
  reads, ambiguous samples, and ignored/unrecognized files.
- Orphan, ambiguous, missing-report, and ignored-file details.
- Global warnings and explicit limitations.
- Per-sample scan statistics, structural errors, pairing mismatches, FastQC
  availability, actual modules, classification reasons, and source paths.

### `report.html`

A responsive, self-contained dashboard with:

- PASS/WARN/FAIL summary cards and an overall status banner.
- Search by sample, filename, or problem.
- Status filtering and a FastQC-incomplete filter.
- A per-sample QC table and detail dialog.
- Pairing and integrity errors with record numbers.
- FastQC module tables for each read direction.
- Missing FastQC reports, orphaned reads, ambiguous samples, ignored files,
  warnings, and limitations.

The HTML contains only local CSS and vanilla JavaScript. It requires no server
and no network. Untrusted filenames, sample IDs, and error text are embedded as
JSON with `<`, `>`, `&`, U+2028, and U+2029 escaped, and are rendered with
`textContent`; the page also uses a restrictive Content-Security-Policy.

### Output safety

- Existing report files are never overwritten without `--overwrite`.
- Input FASTQ and FastQC files are only read; they are never renamed, modified,
  or deleted.
- Each report is staged in a temporary sibling, flushed, fsynced, and atomically
  replaced. Final files are checked for existence and nonzero size.
- The four-file set is not one filesystem transaction. If a write fails midway,
  the command exits 2 and explicitly tells you not to treat the run as
  successful.

## Interpreting a run

1. **Look at FAIL samples first.** Check the listed structural and pairing
   errors. Restore, re-download, or regenerate corrupted files; locate missing
   mates; or remove duplicate/ambiguous candidates before rerunning.
2. **Read WARN reasons individually.** A FastQC module WARN/FAIL is different
   from a missing report and from a FastQC-versus-FASTQ read-count disagreement.
   The reports preserve the actual module statuses.
3. **Do not equate missing evidence with success.** A blank module count, a
   `missing` availability, or `not_requested` is not a PASS. If FastQC matters
   for your workflow, generate the reports and rerun.
4. **Check pairing status.** `NOT_CHECKED` means structural validation already
   failed, so identifier comparison was intentionally skipped.
5. **Keep the audit report with the analysis record.** It documents exactly which
   files and FastQC archives were assessed and which limitations applied.

## Testing

The test suite uses only Python’s `unittest`; no third-party test dependency is
required. Fixtures are generated programmatically in temporary directories.

Run all unit, integration, CLI, and end-to-end tests from the repository root:

```bash
python -m unittest discover -s tests -t . -v
```

`tests/__init__.py` adds `src/` to the import path, so tests work from a source
checkout even when the package is not installed. The suite currently contains
**122 tests**, including the required pairing, corruption, FastQC, classification,
HTML-escaping, overwrite-protection, exit-code, CSV/JSON-consistency, and
synthetic end-to-end scenarios.

Run only the performance-oriented streaming-memory test:

```bash
python -m unittest tests.test_performance -v
```

Run the standalone benchmark for larger, repeatable measurements:

```bash
python scripts/benchmark.py --reads 200000 --length 150
python scripts/benchmark.py --reads 500000 --length 150 --gzip
```

From an uninstalled source checkout, prefix with `PYTHONPATH=src`:

```bash
PYTHONPATH=src python3 scripts/benchmark.py --reads 200000 --length 150 --gzip
```

The benchmark creates its synthetic input in a temporary directory and reports
scan time, throughput, and traced peak memory. It does not touch research data.

## Troubleshooting

**No paired-end FASTQ samples discovered**

Check that files are directly in `--fastq-dir` (not a subdirectory) and end with
a supported extension plus `_R1/_R2`, `_1/_2`, or `_R1_001/_R2_001`. The warning
lists unrecognized/ignored files.

**Sample is orphaned**

Only one mate was found. Add the missing file with the matching sample ID and
opposite read marker, or move the orphan elsewhere.

**Sample is ambiguous**

More than one file exists for a read side. Keep exactly one R1 and one R2 file
for that sample; move duplicates to another directory.

**FastQC report reported missing**

The FastQC directory was supplied but the expected archive was not found. Name
it `<fastq-stem>_fastqc.zip` (for example `SAMPLE_R1_fastqc.zip`) or rerun FastQC.
Reports for missing FASTQ mates or unknown samples are listed separately as
stale/unmatched.

**FastQC archive is invalid**

The ZIP cannot be read or lacks `summary.txt`. Rerun FastQC, verify the archive
opens locally, and remove/replace the damaged file. An invalid archive is not
treated as PASS.

**FastQC is all PASS but the sample is WARN**

Look for a missing/invalid report on the other read side, a FastQC read-count
disagreement, or a malformed module row. Missing evidence and evidence problems
are nonfatal but produce WARN.

**FastQC is all PASS but the sample is FAIL**

Inspect the FASTQ structural/pairing errors. Integrity failure takes precedence
over FastQC.

**Pairing result is `NOT_CHECKED`**

At least one FASTQ file failed structural validation, so identifier comparison
was skipped by design.

**Output files already exist**

Choose a new `--output-dir` or pass `--overwrite`. Without it the tool refuses to
replace anything.

**`invalid or truncated gzip`**

The `.gz` file cannot be decompressed completely. Re-download or regenerate it;
do not trust downstream results from that file.

**`No module named microbiome_qc`**

Activate the virtual environment and install the package, or run with
`PYTHONPATH=src python3 -m microbiome_qc ...` from the repository root.

**Offline `pip install` cannot find setuptools**

Use the fully offline recipe above with `--system-site-packages` and
`--no-build-isolation`, or run from source with `PYTHONPATH=src`.

**Permission denied while writing reports**

Choose a writable `--output-dir`. The tool will not modify input files to work
around permissions.

## Project layout

```text
microbiome-qc-auditor/
├── pyproject.toml
├── README.md
├── LICENSE
├── .gitignore
├── docs/
│   └── DESIGN.md
├── scripts/
│   └── benchmark.py
├── src/
│   └── microbiome_qc/
│       ├── __init__.py
│       ├── __main__.py
│       ├── audit.py
│       ├── classification.py
│       ├── cli.py
│       ├── discovery.py
│       ├── errors.py
│       ├── fastq.py
│       ├── fastqc.py
│       ├── html_template.py
│       ├── models.py
│       ├── pairing.py
│       ├── reporting.py
│       ├── selftest.py
│       └── synthetic.py
└── tests/
    ├── __init__.py
    ├── helpers.py
    ├── test_audit.py
    ├── test_classification.py
    ├── test_cli.py
    ├── test_discovery.py
    ├── test_end_to_end.py
    ├── test_fastq.py
    ├── test_fastqc.py
    ├── test_pairing.py
    ├── test_performance.py
    └── test_reporting.py
```

See [`docs/DESIGN.md`](docs/DESIGN.md) for architecture, precedence rationale,
security model, limitations, and future improvements.

## Limitations and non-goals

This is a quality-control and data-integrity tool only. It does not align,
trim, denoise, assemble, taxonomically classify, or biologically interpret
reads, and it must not be used for diagnosis or clinical decision-making.

Key limitations:

- FastQC module calculations are trusted as supplied and are not recomputed.
- Only ZIP-form FastQC reports are parsed.
- Discovery is filename-based and non-recursive.
- FASTQ validation checks structure and basic composition, not biological
  plausibility or adapter contamination.
- Only a bounded number of detailed mismatch/error examples are displayed;
  totals are still reported.
- Missing evidence is reported as missing and is not silently converted to PASS.
- CSV fields are preserved exactly; use spreadsheet import safeguards when
  opening reports from untrusted datasets.

See [`docs/DESIGN.md`](docs/DESIGN.md) for the full list.

## License

Released under the [MIT License](LICENSE). Copyright (c) 2026 Microbiome QC
Auditor contributors.
