# Design notes and limitations

## Purpose

Microbiome QC Auditor is an offline quality-control tool for paired-end FASTQ
files and optional FastQC ZIP reports. It answers a narrow question: *are these
files structurally intact, correctly paired, and what did FastQC actually
report?* It does not align, trim, denoise, classify, or clinically interpret
reads.

## Data flow

```text
FASTQ directory ──> discovery ──> SampleFiles/R1+R2 paths
                                      │
                                      ├─> streaming FASTQ scans (R1, R2)
                                      ├─> positional read-ID pairing
                                      │
FastQC directory ──> ZIP parsing ─────┴─> per-side FastQC association
                                      │
                                      ├─> classification
                                      ├─> sample_summary.csv
                                      ├─> fastqc_modules.csv
                                      ├─> summary.json
                                      └─> report.html
```

`audit.build_audit` performs all computation and returns an immutable
`AuditResult`. `reporting` turns that result into CSV/JSON/HTML. The CLI only
parses arguments, configures logging, invokes the audit, prints a short
summary, and maps outcomes to exit codes.

## Module responsibilities

| Module | Responsibility |
| --- | --- |
| `discovery.py` | Parse supported filenames, group mates deterministically, detect orphans, duplicates, and ignored inputs |
| `fastq.py` | Stream binary/gzip FASTQ data, validate records, compute read/length/GC statistics |
| `pairing.py` | Normalize read identifiers and compare mates positionally |
| `fastqc.py` | Read FastQC ZIP metadata in place, parse module statuses, associate reports with samples/read sides |
| `classification.py` | Apply the sample-level PASS/WARN/FAIL precedence rules |
| `audit.py` | Orchestrate discovery, scanning, pairing, FastQC association, and warnings |
| `reporting.py` | Render and safely write the four report artifacts |
| `html_template.py` | Self-contained HTML/CSS/JS shell with escaped embedded data |
| `synthetic.py` | Generate synthetic fixtures and the demo dataset |
| `selftest.py` | Run small built-in checks without touching research data |
| `cli.py` | Argument parsing, logging, console output, and exit-code mapping |

## Discovery and pairing decisions

- Supported extensions are matched case-insensitively: `.fastq.gz`, `.fq.gz`,
  `.fastq`, `.fq`.
- Supported read markers are `_R1`/`_R2`, `_1`/`_2`, and `_R1_001`/`_R2_001`
  (any three-digit lane-like suffix). Markers are matched case-insensitively.
- Sample identifiers preserve case and are compared case-sensitively.
  `SampleA` and `samplea` therefore remain separate samples rather than being
  silently merged.
- Discovery is non-recursive. Subdirectories are reported, not searched.
- Multiple candidates for one read side make the sample ambiguous; every
  candidate is retained and reported. No file is silently picked or dropped.
- One candidate for one side and none for the other is an orphan and fails the
  sample. The file is still scanned and reported so the evidence is visible.
- Output ordering is lexicographic by sample ID and filename.

## FASTQ validation decisions

- Input is read one four-line record at a time in binary mode. Gzip input is
  read through `gzip.open`; nothing is extracted to disk.
- A structural error stops that file’s scan. Continuing after a malformed record
  risks treating sequence lines as headers and generating misleading cascades.
  Statistics for an invalid file are explicitly partial.
- Headers must start with `@` and contain an identifier. Separators must start
  with `+`. Sequences must be non-empty. Sequence and quality lengths must be
  equal. Quality bytes must be printable ASCII `!` (33) through `~` (126).
- CRLF line endings and a missing final newline are accepted. A record that ends
  before its quality line is rejected as truncated.
- GC percentage is `(G + C) / (A + C + G + T) * 100`. `N` and all other symbols
  are excluded from the denominator. If no A/C/G/T bases exist, GC is reported
  as 0.0 and the ACGT base count is zero.
- Mean read length is rounded to two decimal places. Values are computed with
  streaming counters; reads are never retained.
- Pairing is a second streaming pass that compares only normalized identifiers.
  It does not retain reads. A trailing `/1` or `/2` is removed and also recorded
  as a direction. Standard Illumina comment tokens such as `1:N:0:1` provide a
  direction when present.
- Identifier mismatches are counted in full, but only the first `--max-errors`
  examples are retained for presentation. Read-count differences are reported
  independently.
- Pairing comparison is skipped when either file failed structural validation,
  because record boundaries cannot be trusted. The CSV/JSON state
  `NOT_CHECKED` instead of implying that pairing passed.

## FastQC parsing decisions

- Only `*_fastqc.zip` archives are read; archives are opened in place and are
  never extracted or executed.
- Module statuses come only from actual `summary.txt` rows with a valid PASS,
  WARN, or FAIL status and non-empty module/input names. A module absent from
  `summary.txt` is absent from results; it is never assumed to be PASS.
- A missing `summary.txt` makes a report unusable for module evidence. A
  malformed row is reported, and valid rows from the same file are kept.
- A missing `fastqc_data.txt` does not erase valid module statuses, but the
  FastQC read count becomes unavailable and the report is flagged.
- A report’s sample/direction association prefers the archive name. If that
  fails, the filename recorded inside the report is used. Conflicting identity
  evidence is explicitly warned about, not hidden.
- Multiple archives mapping to the same sample/side are reported as ambiguous;
  no archive is chosen arbitrarily.
- A missing FastQC directory is an input error. An absent report inside a
  supplied directory is `missing`, not `PASS`. Invalid ZIPs are `invalid`.
  Duplicate associations are `ambiguous`. None of these states produces module
  counts.
- A report that refers to a sample absent from FASTQ discovery, or a report for
  a read side whose FASTQ file is missing, is surfaced as a warning. Stale
  reports are not applied to unrelated files.
- FastQC command-line execution, report recalculation, unzipped report folders,
  and non-ZIP formats are out of scope.

## Classification precedence

Rules are implemented only in `classification.py`:

1. **FAIL** if any structural or pairing problem exists: invalid/truncated/
   unreadable FASTQ, empty file, missing mate, ambiguous pairing, unequal mate
   counts, or positional identifier/direction mismatch. FastQC PASS cannot
   override this.
2. **WARN** if there is no structural/pairing problem but at least one FastQC
   concern exists: a module WARN/FAIL, missing/invalid/ambiguous report,
   malformed report evidence, unavailable FastQC read count, or a FastQC read
   count that disagrees with the FASTQ scan.
3. **PASS** otherwise.

A FastQC module **FAIL** is a sample **WARN**, not a sample **FAIL**. A FastQC
FAIL is a QC concern from FastQC’s calculations, not evidence that the FASTQ
four-line structure is corrupt. Sample FAIL is deliberately reserved for data
integrity and pairing failures. This distinction is visible in CSV, JSON, and
HTML.

If no FastQC directory is supplied, FastQC availability is `not_requested` and
a structural PASS is possible. That PASS explicitly means “no structural or
pairing problem detected”, not “fully validated by FastQC”. The report and JSON
limitations state this.

## Output safety and determinism

- The four output filenames are fixed. Existing report files are never replaced
  unless `--overwrite` is supplied. A directory occupying a target path is an
  error.
- All report content is rendered before writing. Each file is written to a
  temporary sibling, flushed, fsynced, and replaced with `os.replace`. The tool
  then verifies that every target exists and is non-empty.
- The four-file set is not a single filesystem transaction. If an OS error
  occurs during replacement, the tool raises `OutputError` and the CLI exits 2;
  it never reports success for a partial write. Existing content may already
  have been replaced in that rare case, which is stated in the error message.
- Temporary files are cleaned up on both success and failure.
- Sorting and serialization are deterministic for the same input and config.
  The audit timestamp is the only intentionally varying field.

## HTML security model

- All dynamic data is embedded once as JSON in a
  `<script type="application/json">` element. Characters that could terminate
  the script element or break JavaScript parsing (`<`, `>`, `&`, U+2028,
  U+2029) are escaped.
- The page constructs visible content with `document.createElement` and
  `textContent`; it does not assign untrusted data to `innerHTML`, event handler
  attributes, URLs, or CSS.
- A restrictive Content-Security-Policy meta tag permits only inline styles,
  inline scripts, and `data:` images. There are no external fonts, scripts,
  stylesheets, images, or network calls. The report works from `file://`.
- Filenames and error strings are treated as untrusted text. CSV preserves raw
  fields for accurate data exchange; opening a CSV from an untrusted dataset in
  a spreadsheet may still interpret leading `=`, `+`, `-`, or `@` characters as
  formulas. Use spreadsheet import safeguards when handling untrusted samples.

## Performance characteristics

- FASTQ scans are O(file size) time and bounded memory; tests enforce a peak
  traced-memory limit while scanning a 50,000-read fixture.
- Pairing performs a second pass over both mates but retains no reads.
- FastQC archives are read in place. `summary.txt` is capped at 5 MiB; module
  rows and malformed examples are bounded by `--max-errors`. The Basic
  Statistics section is streamed line by line.
- Discovery holds one path object per input file, not file contents.
- Large-data throughput depends on gzip decompression, disk, and Python I/O;
  `scripts/benchmark.py` provides repeatable local measurements.

## Known limitations

- This is not a clinical, diagnostic, or biological interpretation tool. It
  makes no claims about sample quality beyond the documented structural and
  FastQC checks.
- FASTQ validation does not validate the biological alphabet, adapter content,
  duplication, or base-quality distributions; those are FastQC’s domain.
- Sequence header formats beyond `/1`, `/2`, and the standard Illumina comment
  direction are treated as opaque identifiers.
- Discovery is name-based and non-recursive. It cannot infer pairing when
  filenames do not follow a supported convention; those files are reported as
  unrecognized.
- Only FastQC ZIP archives with `summary.txt` are supported. FastQC versions
  that write only uncompressed folders are not parsed.
- FastQC calculations are trusted as supplied. A stale archive with the right
  sample name but old content can only be detected when its Basic Statistics
  read count disagrees; other staleness cannot be proven offline.
- Module duplicates use the first valid row and are warned about. Different
  FastQC versions may legitimately expose different module sets.
- The tool does not repair, rename, move, or delete FASTQ or FastQC inputs.
- Resource limits for adversarial ZIP archives or extremely long lines are not
  a security boundary; audit trusted local data in a resource-limited context if
  necessary.
- CSV is intentionally unmodified. Spreadsheet formula-injection safeguards are
  left to the consumer.

## Possible future improvements

- Optional recursive discovery and an explicit path/pattern configuration file.
- Direct support for uncompressed FastQC report directories.
- Optional checksum manifest verification and run-to-run comparison.
- Machine-readable JSON Schema and a stable API for embedding audits.
- Parallel file scanning with deterministic output ordering.
- Richer FastQC comparisons (for example warning on FastQC version differences).
- Optional CSV hardening mode for environments that open reports in spreadsheets.
- Extended filters and per-module drill-down in the HTML report.

None of these are implemented unless present in the source tree and covered by
tests.
