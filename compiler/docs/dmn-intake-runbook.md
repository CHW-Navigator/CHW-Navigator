# DMN Intake Runbook

This runbook defines the normal path for a new DMN delivery.

## Inputs

Expected source artifacts:

- metadata file
- variable catalog
- predicate catalog
- phrase bank
- DMN file
- optional patient case suite

## Workflow

1. Place source artifacts in a fresh intake workspace or bundle input folder.
2. Run source preflight lint on each source artifact.
3. Compose the base IR from metadata + variable catalog + predicate catalog + phrase bank.
4. Run IR validation and IR lint on the composed base IR.
5. Import DMN decisions into the base IR.
6. Run IR validation and IR lint again on the DMN-imported IR.
7. Generate:
   - XLSForm
   - Mermaid
   - SMT/Z3 outputs
8. Run backend-specific lint after each generated artifact.
9. Run comparison tests on:
   - explicit patient cases if provided
   - derived Z3 witness suites
10. Create or update the evidence bundle with:
   - copied inputs
   - generated outputs
   - lint reports
   - compare reports
   - hashes
   - provenance metadata

## Review

Primary review questions:

- Did source preflight pass?
- Did IR validation/lint pass?
- Did all backend lints pass?
- Did compare results agree across engines?
- Did mutation checks still fail when artifacts were altered?

## Change discipline

- Fix source artifacts at the source whenever possible.
- Do not patch compiled IR as the long-term fix for authored logic.
- If a fail-safe or system-default rule is added, mark it with explicit provenance.
