# Odin to Lunchtab Balance Transfer 0.4.1

## New workflow

- Added a **Manual Reconciliation Review** tab for comparing the automated transfer CSV with
  staff-edited transfer files before InitialBalances import.
- Added reconciliation and InitialBalances audit-control summaries, operator-readable run
  summaries, and SHA-256 provenance hashes for source and generated artifacts.
- Added a sandbox data generator app for deterministic synthetic reconciliation and
  InitialBalances test packs.
- Added manual-review candidate reports with evidence scoring, transfer-row traceability,
  actionable and ambiguous filters, checklist export, proposed edited transfer generation,
  and candidate decision audit output.
- Added InitialBalances preflight validation that previews ready/blocked status, applied
  totals, blocked totals, and exception reasons before writing a formal run.

## Data compatibility and safeguards

- Candidate review is advisory until the operator exports a proposed edited transfer; the
  original automated transfer is not modified.
- Manual reconciliation audits block invalid manual balances and highlight higher-risk edits
  such as changed automated balances, changed family codes, or identity-field changes.
- Sandbox data uses synthetic names, identifiers, `sandbox.invalid` email addresses, family
  codes, and balances.
- Run manifests continue to avoid student rows, balances, and absolute source paths.

## Upgrade notes

- Existing matching profiles remain compatible.
- Existing reconciliation CLI behavior is preserved.
- Install over version 0.4.0 to upgrade; user-created result folders and profiles are retained.
