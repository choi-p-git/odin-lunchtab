# Odin to Lunchtab Balance Transfer 0.4.0

## New workflow

- Added an **InitialBalances Transfer** tab for the second stage of the Lunchtab import.
- Aggregates reconciled `OdinBalanceAmount` values by `DefaultFamilyCode`.
- Adds aggregated balances to existing InitialBalances amounts.
- Blocks the import CSV when integrity exceptions are present while still publishing audit
  and exception reports.
- Produces timestamped, atomic run folders with privacy-conscious manifests.

## Data compatibility and safeguards

- Stage-one Lunchtab exports now require and preserve `DefaultFamilyCode`.
- Added strict support for UTF-8, Windows-1252, and BOM-marked UTF-16 CSV files.
- Rejects unsupported, malformed, binary-looking, or replacement-decoded input.
- Generated CSV files remain UTF-8 with a BOM for Windows and Excel compatibility.
- Manifests record detected input encodings without storing balances, identifiers, names, or
  absolute paths.

## Upgrade notes

- Existing matching profiles remain compatible.
- Existing reconciliation CLI behavior is preserved.
- Install over the previous version to upgrade; user-created result folders and profiles are
  retained.
