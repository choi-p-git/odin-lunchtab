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
and accepted-match audit.

The generated `run-manifest.json` records application version, timestamps, source
filenames, summary counts, and generated filenames. It does not contain student rows,
balances, or absolute source paths.

Diagnostic logs are stored under `%LOCALAPPDATA%\Odin Lunchtab\logs` and contain only
operational events and summary counts.

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
- `run-manifest.json` for desktop managed runs.

The transfer CSV adds `OdinBalanceAmount` immediately after
`DefaultFamilyBalanceAmount`. The manual-review report excludes `no Lunchtab match`
records, which are likely legacy or closed accounts.

The match audit identifies the profile, rule, transformed identifier, and destination for
each accepted balance. Matching metadata is not added to the Lunchtab import CSV. The
manifest records the profile schema version and per-rule totals.

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
- Offers an optional desktop shortcut.
- Supports upgrades through its stable application ID.
- Leaves user-created results intact during upgrades and uninstall.

The versioned installer is written to `release`. Publish the installer together with a
SHA-256 checksum and release notes to the trusted internal software location.

Example checksum command:

```powershell
Get-FileHash .\release\Odin-Lunchtab-Setup-0.3.0-x64.exe -Algorithm SHA256
```

## Release checklist

Before internal publication:

1. Run the release build script.
2. Test fresh installation and launch on clean Windows 10 and Windows 11 x64 systems.
3. Confirm operation without Python or administrator rights.
4. Test a normal run and a run containing manual-review exceptions.
5. Install the new version over the previous version.
6. Uninstall and confirm that user result folders remain.
7. Publish the installer, checksum, version, release notes, and this user guidance.
