# Bundle `20260505-160123-multi-module-proof`

This bundle captures one DMN intake, its copied source inputs, the generated canonical artifacts, and the baseline comparison reports used to confirm semantic agreement.

## Provenance

- Created: `2026-05-05T16:01:26`
- Compiler version: `0.1.0`
- Python: `3.12.10`
- Platform: `Windows-11-10.0.22631-SP0`
- Git commit: `e1fe111b3b898723cb811d175fe2228dbf37f312`
- Source label: `multi-module-proof`
- Original base IR: `C:\Users\levine\Dropbox\PC (2)\Documents\GitHub\CHW-Navigator\compiler\examples\multi_module_router.ir.json`
- Original DMN: `C:\Users\levine\Dropbox\PC (2)\Documents\GitHub\CHW-Navigator\compiler\examples\multi_module_router.dmn`
- Original patient cases: `C:\Users\levine\Dropbox\PC (2)\Documents\GitHub\CHW-Navigator\compiler\examples\multi_module_router.cases.json`

## Bundle Layout

- Inputs: `inputs/base.ir.json`, `inputs/source.dmn`, `inputs/explicit.cases.json`
- Canonical IR: `outputs/merged.ir.json`
- XLSForm: `outputs/xlsform/survey.csv`, `outputs/xlsform/choices.csv`, `outputs/xlsform/source-map.json`
- Mermaid: `outputs/mermaid/multi-module-proof.mmd`, `outputs/mermaid/multi-module-proof.mmd.source-map.json`
- Z3: `outputs/z3/multi-module-proof.smt2`, `outputs/z3/z3-checks.json`, `outputs/z3/derived.cases.json`
- Good-path tests: `tests/good/z3-derived.compare.json`, `tests/good/explicit.compare.json`
- Mutation workspace: `mutations/` with expected candidate filenames documented in `mutations/manifest.json`

## Expected Workflow

1. Copy a new DMN and base IR into a fresh bundle by rerunning the bundle command. Do not overwrite older bundles.
2. Review the copied inputs and generated outputs in this folder.
3. Add deliberate drift candidates under `mutations/` when you want to prove that mismatch detection still works.
4. Keep any new patient suites or reviewer notes in this bundle so the audit trail stays attached to the exact compiler version and source snapshot.
