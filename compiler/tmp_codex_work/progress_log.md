# Progress Log

## 2026-05-05

- Created checkpoint workspace files for the overnight hardening pass.
- Confirmed current branch state and existing CLI/lint surfaces before implementation.
- Reorganized the team to-do list into `Now / Next / Later / Maybe`.
- Added `docs/dmn-intake-runbook.md` to define the DMN intake and review workflow.
- Added staged lint helpers for source preflight, compiled IR validation/lint, and backend-specific lint for XLSForm, Mermaid, and SMT.
- Wired new CLI commands for staged lint:
  - `preflight-source`
  - `lint-ir`
  - `lint-xlsform`
  - `lint-mermaid`
  - `lint-smt2`
- Added DMN source-preflight parsing support through `lint_dmn_file(...)`.
- Reused the existing shared compiler `.venv` from `C:\Users\levine\Dropbox\PC (2)\Documents\Codex\CHW Navigator` when the local repo clone had no `.venv`.
- Added bundle artifact hashing via `artifact_hashes.json` and linked it from bundle metadata.
- Ran focused regression with:
  - `python -m unittest tests.test_staged_lint -v`
  - `python -m unittest tests.test_staged_lint tests.test_bundles tests.test_engine_logs tests.test_artifact_drift -v`
  - both runs passed when executed with `PYTHONPATH='src;tests'` and the shared `.venv` interpreter
