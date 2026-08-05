# Mutation Workspace

Use this folder to keep deliberately altered candidate artifacts beside the canonical outputs for this bundle.

Recommended filenames:

- `dmn/candidate.dmn`
- `ir/candidate.ir.json`
- `xlsform/survey.csv` and `xlsform/choices.csv`
- `mermaid/candidate.mmd`
- `smt2/candidate.smt2`

Mutation tests should fail the relevant comparison step when the candidate no longer matches the canonical logic.
