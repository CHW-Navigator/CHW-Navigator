# Bundle `20260501-082341-pneumonia-demo`

This bundle captures one DMN intake, its copied source inputs, the generated canonical artifacts, and the baseline comparison reports used to confirm semantic agreement.

## Provenance

- Created: `2026-05-01T08:23:41`
- Compiler version: `0.1.0`
- Python: `3.12.10`
- Platform: `Windows-11-10.0.22631-SP0`
- Git commit: `unknown`
- Source label: `pneumonia-demo`
- Original base IR: `C:\Users\levine\Dropbox\PC (2)\Documents\Codex\CHW Navigator\examples\pneumonia.ir.json`
- Original DMN: `C:\Users\levine\Dropbox\PC (2)\Documents\Codex\CHW Navigator\examples\pneumonia.dmn`
- Original patient cases: `C:\Users\levine\Dropbox\PC (2)\Documents\Codex\CHW Navigator\examples\pneumonia.cases.json`

## Bundle Layout

- Inputs: `inputs\base.ir.json`, `inputs\source.dmn`, `inputs\explicit.cases.json`
- Canonical IR: `outputs\merged.ir.json`
- XLSForm: `outputs\xlsform\survey.csv`, `outputs\xlsform\choices.csv`, `outputs\xlsform\source-map.json`
- Mermaid: `outputs\mermaid\pneumonia-demo.mmd`, `outputs\mermaid\pneumonia-demo.mmd.source-map.json`
- Z3: `outputs\z3\pneumonia-demo.smt2`, `outputs\z3\z3-checks.json`, `outputs\z3\derived.cases.json`
- Good-path tests: `tests\good\z3-derived.compare.json`, `tests\good\explicit.compare.json`
- Mutation workspace: `mutations/` with expected candidate filenames documented in `mutations/manifest.json`

## Expected Workflow

1. Copy a new DMN and base IR into a fresh bundle by rerunning the bundle command. Do not overwrite older bundles.
2. Review the copied inputs and generated outputs in this folder.
3. Add deliberate drift candidates under `mutations/` when you want to prove that mismatch detection still works.
4. Keep any new patient suites or reviewer notes in this bundle so the audit trail stays attached to the exact compiler version and source snapshot.
