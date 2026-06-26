# Future State Analysis

## Automated Odin Cloud to LunchTab Balance Transfer

### Executive Summary

The Odin to LunchTab Balance Transfer application changes the migration process from a
manual, record-by-record reconciliation into a controlled, exception-driven workflow.

Instead of requiring an operator to search across multiple files for every Odin account,
the program reads the source exports, applies configured matching rules, validates identity
details, transfers balances to matched LunchTab records, and separates records that cannot
be resolved safely.

The application then supports the second stage of the process by aggregating reconciled
balances by LunchTab Family Code and adding them to the LunchTab InitialBalances export.
An import file is created only when the required integrity checks pass.

The future state therefore shifts staff effort away from repetitive lookup and data entry
and toward reviewing a smaller set of genuine exceptions. It also adds controls,
traceability, repeatability, and data-protection measures that are not practical in the
fully manual process.

The current-state baseline estimates at least **15.4 hours** to investigate 1,478 Odin
accounts manually. The automated workflow is designed to eliminate routine per-account
processing for safely matched records. An actual run using the final **v0.4.0** application
completed the automated process in **3 minutes**. Compared with the 15.4-hour manual
baseline, this represents an approximate **99.7% reduction in processing cycle time** and
makes the automated run approximately **308 times faster**.

Exception review, corrections, approval, and the final LunchTab import remain human
activities and should be measured separately from the three-minute automated runtime.

---

# Future Workflow

## Stage 1: Automated Reconciliation

The operator performs the following sequence:

1. Open the Odin to LunchTab desktop application.
2. Select the Odin account balance workbook.
3. Select the LunchTab users export.
4. Select the appropriate venue matching profile.
5. Validate the files and preview the matching results.
6. Run the reconciliation.
7. Review only the records placed in the manual-review report.
8. Complete any approved manual corrections in the reconciled transfer file.

During this stage, the application:

* Extracts and validates Odin account records.
* Preserves all rows from the selected LunchTab users export.
* Applies ordered identifier-matching rules automatically.
* Supports Login Barcode, External ID, and email-username matching.
* Applies configured identifier transformations and one-off crosswalk mappings.
* Validates surname and first or preferred name before accepting a match.
* Prevents unsafe updates when identifiers are duplicated, conflicting, stale, or
  ambiguous.
* Places unresolved records into exception reports instead of guessing.
* Writes accepted balances into a processed copy of the LunchTab users export.
* Produces an accepted-match audit showing how each balance was matched.

---

## Stage 2: Automated InitialBalances Transfer

After any required manual reconciliation, the operator:

1. Selects the reconciled transfer CSV.
2. Selects the LunchTab InitialBalances CSV.
3. Validates both files.
4. Runs the transfer and audit.
5. Uses the processed InitialBalances file only when the run completes without blocking
   exceptions.

During this stage, the application:

* Reads populated Odin balances from the reconciled transfer.
* Groups balances by the case-sensitive LunchTab Family Code.
* Aggregates multiple account balances belonging to the same family.
* Adds the aggregated amount to the family's existing InitialBalances amount.
* Treats blank target amounts as zero.
* Verifies source-row, matched-row, family, and financial control totals.
* Blocks creation of the import file when required family codes are blank, invalid,
  unmatched, or duplicated.
* Produces family-level audit and exception reports.
* Publishes a processed InitialBalances CSV only after the integrity checks succeed.

---

# What the Automation Achieves

## 1. Replaces Routine Record-by-Record Searching

The program performs the identifier translation that previously required repeated manual
searches across the Odin balance export, LunchTab users export, and LunchTab balance import
file.

Configured rules translate Odin account identifiers directly to supported LunchTab fields,
while name validation provides an additional identity check. Routine matches no longer
require the operator to search by ID, barcode, name, and Family Code individually.

---

## 2. Changes the Operating Model to Exception-Based Review

In the current state, every one of the 1,478 accounts must be investigated, including
legacy and graduated users.

In the future state, safely matched records are processed automatically. Staff attention is
reserved for records that are malformed, unmatched, ambiguous, duplicated, conflicting, or
otherwise unsafe to update.

Records with no LunchTab match are reported separately and excluded from the focused
manual-review report because they are likely to represent legacy or closed accounts. This
prevents those records from consuming the same level of review effort as actionable
matching conflicts.

---

## 3. Reduces Manual Balance Entry

For accepted matches, the Odin balance is inserted automatically into the processed
LunchTab transfer file.

In the InitialBalances stage, the program automatically aggregates balances by Family Code
and updates the corresponding amount. This removes the need to manually locate the family
row, calculate combined family balances, and copy the result into the import CSV.

Manual intervention remains available for genuine exceptions, but it is no longer the
standard path for every account.

---

## 4. Prevents Unsafe or Ambiguous Transfers

The program follows a fail-safe approach: a record must satisfy the configured matching and
name-validation requirements before its balance is accepted.

The application quarantines conditions such as:

* Duplicate Odin identifiers
* Duplicate or ambiguous LunchTab identifiers
* Name-validation failures
* Multiple Odin accounts resolving to one LunchTab user
* Invalid or missing balances
* Blank, duplicate, or unmatched Family Codes
* Malformed input records
* Stale or conflicting crosswalk mappings

The InitialBalances import is deliberately withheld when blocking integrity exceptions are
present. This prevents a partially trusted file from being mistaken for a completed import.

---

## 5. Creates a Reproducible Audit Trail

Each managed run creates a timestamped result folder containing the processed files,
exception reports, audit reports, and a run manifest.

The audit evidence identifies:

* Which records were accepted
* Which profile and matching rule were used
* Which transformed identifier resolved the match
* Which LunchTab destination received the balance
* Which source rows contributed to each updated family
* Which records were rejected and why
* Whether control totals reconciled
* Which files were generated during the run

This allows an individual transfer decision or an entire run to be reviewed without
reconstructing the operator's manual searches.

---

## 6. Improves Repeatability Across Venues and Data Variations

Venue matching profiles allow identifier differences to be configured without changing the
program code.

Profiles support:

* Ordered matching rules
* Account-type-specific rules
* Prefix, suffix, substring, padding, and leading-zero transformations
* Login Barcode, External ID, and email-username targets
* Domain restrictions for email matching
* Persistent one-off crosswalks
* Controlled unique-name fallback

The protected Legacy Default profile preserves the original matching behavior, while
additional profiles allow the process to adapt to other venue data conventions.

---

## 7. Protects Source Data and Personal Information

The application operates locally and does not change, move, or delete the selected source
files.

Generated reports are first written to a private staging location and are published only
after the required output files and manifest are successfully created. Operational logs
contain events and summary counts rather than names, identifiers, balances, or absolute
source paths.

These controls reduce the risk of source-file damage, incomplete result publication, and
unnecessary exposure of personal data.

---

# Future-State Performance

## Measured Performance Improvement

The current-state time study and final v0.4.0 production run provide the following
comparison:

| Metric | Current State | Automated Future State |
| --- | ---: | ---: |
| Accounts in migration dataset | 1,478 | 1,478 |
| Processing method | Manual record-by-record review | Automated reconciliation and transfer |
| Processing time | ~15.4 hours minimum | 3 minutes |
| Equivalent minutes | ~924 minutes | 3 minutes |
| Cycle-time reduction | — | ~99.7% |
| Relative processing speed | 1× baseline | ~308× faster |

In the future state, routine matching, balance placement, Family Code aggregation, and
report generation are completed by the application. Human processing time is primarily
limited to:

* Selecting and validating the input files
* Reviewing the run summary
* Resolving actionable exceptions
* Performing final operational approval and import

The measured three-minute run demonstrates the reduction in automated processing cycle
time. It does not, by itself, mean that every migration-related staff activity is completed
within three minutes.

Actual active labor savings should be calculated using:

```text
Labor hours saved =
15.4 baseline hours - future operator handling hours
```

Future operator handling hours should include file selection, validation, exception review,
corrections, reruns, approval, and final import preparation. The measured **3-minute
automated runtime** should remain separate from active staff handling time in operational
reporting.

---

# Current State vs. Future State

| Area | Current State | Future State |
| --- | --- | --- |
| Processing model | Every account investigated manually | Safe matches automated; staff review exceptions |
| Identifier translation | Repeated manual cross-referencing | Configured matching rules and transformations |
| Name verification | Manual visual confirmation | Automated first/preferred-name and surname validation |
| Legacy or closed accounts | Investigated during routine processing | Unmatched records reported separately |
| Balance entry | Manually copied to destination rows | Automatically written for accepted matches |
| Family aggregation | Manually determined and entered | Automatically grouped and totaled by Family Code |
| Ambiguous records | Dependent on operator judgment | Quarantined with a documented reason |
| Import safety | File can contain unnoticed manual errors | Import withheld when blocking exceptions exist |
| Audit trail | Difficult to reconstruct | Match audits, family audits, exceptions, and manifests |
| Source-file protection | Dependent on operator handling | Source files remain unchanged |
| Repeatability | Varies by operator and session | Consistent rules applied by reusable profiles |
| Scalability | Labor grows approximately with account count | Routine processing scales computationally; labor follows exceptions |

---

# Future-State Controls

The automated process introduces the following operational controls:

1. **Input validation** confirms required files, formats, headers, and supported encodings.
2. **Dry-run preview** reports expected matches, conflicts, unmatched records, and manual
   review volume before outputs are written.
3. **Identity validation** requires compatible names in addition to identifier matching.
4. **Exception quarantine** prevents uncertain records from receiving automatic balances.
5. **Control-total validation** verifies source rows, matched rows, updated families, and
   transferred amounts.
6. **Blocked-run behavior** prevents creation of an import file when integrity issues
   remain.
7. **Atomic publication** exposes results only after the complete result set is created.
8. **Timestamped outputs** preserve separate evidence for each run.
9. **Manifest creation** records run-level provenance and summary information without
   storing student-level personal data.
10. **Protected source files** ensure the original exports remain unchanged.

---

# Recommended Future-State Measures

The following measures should be captured during production use to quantify the realized
benefit:

| Measure | Purpose |
| --- | --- |
| Total Odin records | Confirms workload size |
| Automatically accepted matches | Measures straight-through processing |
| Manual-review exceptions | Measures remaining actionable workload |
| No-match or likely legacy records | Measures non-migrating population |
| Automated match rate | Accepted matches divided by valid Odin records |
| Exception rate | Actionable exceptions divided by valid Odin records |
| Operator handling time | Measures actual future-state labor |
| Automated runtime | Measures system processing performance |
| Updated families | Measures final destination scope |
| Source and destination control totals | Confirms financial reconciliation |
| Blocked runs | Measures input-quality or integrity failures |
| Post-import corrections | Measures outcome accuracy |

---

# Future State Assessment

The automation program transforms the Odin-to-LunchTab migration from a labor-intensive
search-and-entry task into a governed reconciliation process.

Its central achievement is not simply faster processing. The application establishes a
repeatable decision path for every record:

* Safe matches are processed automatically.
* Unsafe matches are isolated rather than guessed.
* Family balances are aggregated consistently.
* Import files are withheld when integrity checks fail.
* Every accepted transfer and rejected exception is documented.

For the current population of 1,478 Odin accounts, the program directly addresses the
activities responsible for the estimated 15.4-hour minimum manual workload. The final
v0.4.0 program completed the automated run in 3 minutes, reducing processing cycle time by
approximately 99.7%. Staff effort becomes proportional to the number of genuine exceptions
rather than the total number of accounts.

The measured result establishes the program's cycle-time improvement. Capturing operator
handling time and exception-volume data will additionally quantify the realized reduction
in active labor, automated match rate, and exception rate. The future state also provides
clear improvements in accuracy, control, auditability, repeatability, data protection, and
scalability.
