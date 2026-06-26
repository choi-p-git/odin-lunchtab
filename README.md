# Odin to Lunchtab Balance Transfer

This Windows utility safely transfers matched balances from an Odin Cloud POS account
balance workbook into a copy of the Lunchtab users export. It preserves every Lunchtab row
and sends unsafe, ambiguous, malformed, or unmatched records to exception reports.

Source exports contain personal data and remain on the local computer. The application
never changes, moves, or deletes either selected source file.

## Desktop application

For local development:

```powershell
uv sync --locked
uv run odin-lunchtab-gui
```

## Sandbox data generator

For non-live testing, launch the separate sandbox utility:

```powershell
uv run odin-lunchtab-sandbox
```

The sandbox app creates deterministic synthetic test packs containing:

- `Sandbox Odin Account Balance Report.xlsx`
- `Sandbox Lunchtab Users.csv`
- `Sandbox InitialBalances.csv`
- `Sandbox Expected Summary.json`
- `sandbox-manifest.json`

Use the preset selector for clean baseline data, reconciliation exceptions, malformed Odin
rows, InitialBalances blockers, or a mixed stress set. Row counts, identifier conventions,
family grouping, balance ranges, exception volumes, output folder, and random seed can be
edited before generation.

Identifier conventions are configured separately for Odin IDs, LunchTab login barcodes, and
LunchTab family codes. Family codes can use their own prefix, starting number, and padding
so they can model venue exports where the family-code digits are unrelated to Odin IDs.

Choose **Generate + Verify** to immediately run the generated files through the production
reconciliation and InitialBalances workflows. Verification results are written under the
generated sandbox run folder. The generated data uses synthetic names, identifiers, email
addresses under `sandbox.invalid`, family codes, and balances; it should not contain live
student or family data.

The user selects:

1. The Odin `.xlsx` account balance report.
2. The Lunchtab users `.csv` export.
3. A matching profile.
4. An optional results location.

The default results location is:

```text
Documents\Odin Lunchtab Transfers
```

Each successful run creates a new `YYYY-MM-DD_HHMMSS` folder. Results are first written to
a private staging folder and published only after every report and the manifest succeed.
The completion screen provides buttons to open the folder, transfer CSV, manual-review CSV,
accepted-match audit, audit-control summary, candidate-match report, and run summary.

The generated `run-manifest.json` records application version, timestamps, source
filenames, source-file SHA-256 hashes, summary counts, generated filenames, and generated
artifact SHA-256 hashes. It does not contain student rows, balances, or absolute source
paths.

Diagnostic logs are stored under `%LOCALAPPDATA%\Odin Lunchtab\logs` and contain only
operational events and summary counts.

### Manual reconciliation review

The **Manual Reconciliation Review** tab supports the expected staff workflow where
exception accounts are manually resolved after the automated Odin reconciliation:

1. Select the original automated `Processed - Odin to Lunchtab Balance Transfer.csv`.
2. Select the staff-edited copy of that same transfer CSV.
3. Choose **Review edited transfer**.

The review writes a timestamped result folder with a delta audit, short summary, and
`manual-reconciliation-manifest.json`. Normal manual resolutions are rows where a
previously blank `OdinBalanceAmount` was filled in. Changed automated balances, cleared
automated balances, changed family codes, changed identity fields, and other non-balance
edits are highlighted for audit review. Invalid manual amounts block downstream use until
corrected.

### InitialBalances transfer

The **InitialBalances Transfer** tab performs the second stage after any manual
reconciliation:

1. Select the reconciled `Processed - Odin to Lunchtab Balance Transfer.csv`.
2. Select the `InitialBalances...csv` downloaded from the Lunchtab transaction page.
3. Validate. Validation also runs a non-writing preflight preview showing whether the
   transfer would be ready or blocked.
4. Choose **Transfer and audit** when ready to create the formal timestamped result folder.

The reconciled transfer must contain `DefaultFamilyCode` and `OdinBalanceAmount`.
The InitialBalances export must contain exactly:

```text
FamilyName,FamilyCode,Amount
```

Populated Odin balances are aggregated by the case-sensitive family code and added to the
existing Amount. Blank target amounts are treated as zero. Source rows with blank, invalid,
unmatched, or duplicate required family codes block creation of the import file.

Every run creates a timestamped results folder containing a family-level audit, an exception
report, an audit-control summary, a run summary, and `initial-balances-manifest.json`. A
clean run also creates `Processed - {original InitialBalances filename}`. A blocked run
deliberately omits that processed import while retaining the audit evidence needed for
correction.

The completion counts describe different levels of aggregation:

- **Populated transfer rows** counts source rows with an `OdinBalanceAmount`, including zero.
- **Matched source rows** counts those source rows that safely resolved to InitialBalances.
- **Updated families** counts unique `FamilyCode` destinations after family aggregation.
- The audit contains one row per updated family; summing its `SourceRowCount` column should
  equal **Matched source rows**.

Multiple source rows can share one family, so updated families may be lower than matched
source rows. A family with a net aggregate of zero is still counted as updated even though
its target `Amount` does not change numerically. Control totals in the manifest and audit
must agree before the processed import is published.

`InitialBalances Audit Control Summary.csv` provides the operator-facing traceability
ledger. It separates applied balances, blocked balances, exception reason counts, invalid
or excluded source amounts, and control-total pass/fail rows. Blocked balances are reported
once per affected family code, even when multiple exception reasons apply, so manual review
can inspect reasons without double-counting dollars.

`InitialBalances Run Summary.md` provides a short operator-readable status page with the
run status, key counts and totals, important artifacts, and recommended next action.

The preflight preview is intentionally non-writing. It reports expected applied rows,
updated families, exception counts, applied total, blocked total, and exception reasons
before the operator creates a formal InitialBalances run.

CSV inputs support UTF-8 (with or without a BOM), Windows-1252, and BOM-marked UTF-16
little- or big-endian files. Unsupported, ambiguous, or binary-looking files are rejected
rather than decoded with replacement characters. Source files remain unchanged, and all
generated CSV files use UTF-8 with a BOM for Windows and Excel compatibility. Run manifests
record the detected encoding and whether the Windows-1252 fallback was used.

## Venue matching profiles

The application starts with the protected **Legacy Default** profile, preserving the
original exact Odin `ID Number` to Lunchtab `LoginBarcode` rule and unique-name fallback.
Use **Manage Profiles** to duplicate it and configure another venue without changing code.

Profiles support:

- Ordered rules for every record or selected Odin account types.
- `LoginBarcode`, `ExternalId`, or the username portion of `EmailAddress` as the Lunchtab
  target.
- Trim, prefix/suffix addition or removal, zero-padding, leading-zero removal, and
  fixed-position substring transforms.
- Persistent one-off crosswalk mappings.
- Unique-name fallback globally or for selected account types.

Identifiers always remain strings, preserving leading zeros and mixed letters/numbers.
Every identifier and crosswalk match must also pass surname and first/preferred-name
validation. Conflicts, duplicates, stale mappings, and ambiguous matches are quarantined.

### Email username matching

An **Email username** rule extracts the complete local part before the single `@`. For
example, `Pat.User+Lunch@School.org` becomes `Pat.User+Lunch`. The extracted username is
compared case-insensitively, while barcode and external-ID matching remain case-sensitive.

Email rules may optionally restrict matches to selected domains. Domain matching is exact
and case-insensitive, so `school.org` does not include `sub.school.org`. Empty, malformed,
or disallowed email addresses do not become candidates. The editor discovers domains from
the selected Lunchtab export and also permits validated custom domains. Enter one domain
at a time without `@` (for example, `school.org`), using **Add custom** separately for each
additional domain.

### Structured rule editor

Rule configuration uses selectors and checklists rather than typed command values:

- Enable or disable a rule with a checkbox.
- Select the Lunchtab target from a dropdown.
- Apply the rule to all account types or select discovered/custom types.
- Select discovered/custom email domains when Email username is the target.
- Add, edit, reorder, and remove transform steps from a structured list.
- Verify each pipeline through a live sample input/output preview.

The profile editor, preview, and main results areas are scrollable and keep primary action
buttons visible on smaller screens. Data tables provide both horizontal and vertical
scrollbars.

Profiles are stored as versioned JSON under:

```text
%LOCALAPPDATA%\Odin Lunchtab\profiles
```

Profiles can be imported and exported. Crosswalk CSV files use:

```text
AccountType,OdinId,TargetField,TargetValue,AllowedEmailDomains
```

These exports may contain account identifiers and should be stored only in approved secure
locations.

After files are selected, validation performs a non-writing dry run. **Preview profile**
shows rule totals, conflicts, unmatched rows, representative transformations, manual-review
counts, and differences from Legacy Default. Changing profiles invalidates prior validation.

## Command-line workflow

The original CLI remains available for technical use:

```powershell
uv run odin-lunchtab
```

Place one Odin `.xlsx` report and `Lunchtab Users.csv` in `Raw Data`, or provide explicit
paths:

```powershell
uv run odin-lunchtab `
  --odin "Raw Data\Account Balances Report.xlsx" `
  --lunchtab "Raw Data\Lunchtab Users.csv" `
  --profile "Venue Profiles\My Venue.json" `
  --output-dir "Processed Data"
```

Omit `--profile` to use Legacy Default.

Existing CLI outputs are protected by default. Use `--overwrite` only when replacement is
intentional.

## Reports

The workflow writes:

- A cleaned Odin CSV.
- A processed Odin CSV with split names.
- `Processed - Odin to Lunchtab Balance Transfer.csv`.
- A complete exceptions CSV.
- `Manual Review Exceptions - Odin to Lunchtab Balance Transfer.csv`.
- `Accepted Match Audit - Odin to Lunchtab Balance Transfer.csv`.
- `Reconciliation Audit Control Summary.csv`.
- `Reconciliation Run Summary.md`.
- `run-manifest.json` for desktop managed runs.

The transfer CSV adds `OdinBalanceAmount` immediately after
`DefaultFamilyBalanceAmount`. The manual-review report excludes `no Lunchtab match`
records, which are likely legacy or closed accounts.

The selected Lunchtab users export must also contain `DefaultFamilyCode`; this column is
preserved in the transfer CSV for the InitialBalances stage.

The match audit identifies the profile, rule, transformed identifier, destination, and
accepted `OdinBalanceAmount` for each accepted balance. Matching metadata is not added to
the Lunchtab import CSV. The manifest records the profile schema version, per-rule totals,
audit-control status, and audit-control report filename.

`Reconciliation Audit Control Summary.csv` summarizes valid Odin source balances, accepted
matches by method and rule, exceptions by reason, malformed or unparseable rows excluded
from dollar controls, and a pass/fail row verifying that valid Odin source dollars equal
matched dollars plus valid exception dollars.

`Reconciliation Run Summary.md` provides a short operator-readable status page with the
matching profile, key counts, important artifacts, and recommended next action before
continuing to manual reconciliation or InitialBalances.

`Manual Review Candidate Matches.csv` is an advisory helper for exception reconciliation.
For each manual-review exception, it ranks possible LunchTab candidates using evidence such
as ID/barcode matches, ExternalId matches, email usernames, surname matches, and
first/preferred-name compatibility. It does not change the transfer file; staff should
verify the evidence before manually editing `OdinBalanceAmount`.

### Manual reconciliation audit artifacts

When staff manually edit the reconciled transfer CSV to resolve exception accounts, the
edited file should be audited before it is used for InitialBalances. The manual
reconciliation audit compares the original automated transfer to the edited transfer and
creates:

- `Manual Reconciliation Delta Audit.csv`
- `Manual Reconciliation Summary.md`

The audit distinguishes normal manual resolutions, where a previously blank
`OdinBalanceAmount` is filled in, from higher-risk edits such as changed automated balances,
cleared automated balances, changed `DefaultFamilyCode` values, or changed LunchTab
identity fields. Invalid manual amounts block downstream use until corrected.

## Tests and quality checks

```powershell
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv lock --check
```

## Build the Windows application

PyInstaller builds are Windows-specific. From Windows 10 or 11 x64:

```powershell
.\scripts\build-release.ps1 -SkipInstaller
```

The script performs a locked environment sync, tests, lint and format checks, generates
Windows version metadata from `pyproject.toml`, builds the windowed `onedir` bundle, and
runs a frozen executable smoke test.

The application bundle is written to:

```text
dist\OdinLunchtab
```

## Build the installer

Install Inno Setup 6 and ensure `iscc.exe` is available on `PATH`, then run:

```powershell
.\scripts\build-release.ps1
```

The per-user installer:

- Requires no administrator access.
- Installs beneath `%LOCALAPPDATA%\Programs\Odin Lunchtab`.
- Creates a Start Menu shortcut.
- Creates a Start Menu uninstall shortcut and a Windows **Installed apps** entry.
- Offers an optional desktop shortcut.
- Supports upgrades through its stable application ID.
- Leaves user-created results intact during upgrades and uninstall.

The versioned installer is written to `release`. Publish the installer together with a
SHA-256 checksum and release notes to the trusted internal software location.

Example checksum command:

```powershell
Get-FileHash .\release\Odin-Lunchtab-Setup-0.4.0-x64.exe -Algorithm SHA256
```

The release script also copies the current notes to
`release\RELEASE_NOTES-{version}.md`, verifies the executable version metadata, confirms
that Tcl/Tk runtime data was collected, and prints the installer SHA-256.

## Release checklist

Before internal publication:

1. Run the release build script.
2. Test fresh installation and launch on clean Windows 10 and Windows 11 x64 systems.
3. Confirm operation without Python or administrator rights.
4. Test reconciliation, a clean InitialBalances transfer, and a blocked-exception run.
5. Install the new version over the previous version.
6. Uninstall and confirm that user result folders remain.
7. Publish the installer, checksum, version, release notes, and this user guidance.

The application can be removed from **Settings > Apps > Installed apps** or from
**Start > Odin to Lunchtab Balance Transfer > Uninstall Odin to Lunchtab Balance Transfer**.
