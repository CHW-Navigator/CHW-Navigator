# User Types Manual

This manual is for the main kinds of people who touch the compiler workflow.

Use it together with:

- `docs/authoring-guide.md`
- `docs/dmn-intake-runbook.md`
- `docs/source-of-truth-editing-policy.md`
- `contracts/`

## 1. DMN Author

Your job:

- write or revise decision routing
- control rule order
- assign outputs in the supported DMN subset

What you own:

- DMN decision tables

What you do not own:

- variable units or domains
- compound predicate logic
- multilingual text

Main rules:

- use `FIRST` hit policy only
- use simple identifiers in input expressions
- keep input cells to `true`, `false`, or `-`
- do not put `AND`, `OR`, `NOT`, or parentheses in authored DMN cells for v1
- add an explicit wildcard fallback when the clinical policy needs one

If a report complains about:

- bad hit policy: fix the DMN
- compound logic in DMN cells: move that logic into the predicate catalog
- missing fallback path: decide with reviewers whether the guideline needs an explicit fallback row

## 2. Predicate Author

Your job:

- encode Boolean or computed clinical logic
- define threshold logic and helper expressions

What you own:

- predicate catalog

What you do not own:

- DMN routing
- question labels
- output guidance wording

Main rules:

- use structured `expression` AST, not only a prose formula
- keep `inputs_used` aligned with the variables actually referenced
- do not reference outputs inside predicate expressions
- keep units and measurement domains on variables, not predicates

If a report complains about:

- threshold change: fix the predicate catalog
- unknown variable in a predicate: fix the variable catalog or the predicate reference
- output reference inside a predicate: redesign the logic; do not make predicates depend on outputs

## 3. Variable Catalog Author

Your job:

- define encounter inputs, state variables, history-fed fields, and measurement metadata

What you own:

- variable catalog

Main rules:

- use canonical families such as `v_`, `st_`, and `_h` where appropriate
- include stored units in measured numeric IDs where practical
- keep domains and optional MOH `remeasure_*` / `dont_allow_*` thresholds here
- keep provenance structured

If a report complains about:

- missing unit in a numeric ID: fix the variable catalog
- missing domain metadata: fix the variable catalog
- sparse provenance: fix the variable catalog row

## 4. Phrase Bank Author

Your job:

- supply labels, messages, guidance, and multilingual text

What you own:

- phrase bank

Main rules:

- use one row per `key + entity_id + role`
- keep text in `text_<lang>` columns
- separate labels from messages and guidance
- do not hide clinical logic in phrase text

If a report complains about:

- missing label phrase: add a label row
- missing output guidance coverage: add a guidance row or binding
- orphan phrase row: fix `entity_id`

## 5. Intake/Compiler Operator

Your job:

- run the pipeline when new source artifacts arrive
- produce evidence bundles and review packages

What you own:

- command execution
- evidence packaging
- surfacing failures to reviewers

Normal sequence:

1. run source preflight
2. compose IR from metadata + catalogs
3. import DMN
4. run IR validation and lint
5. generate XLSForm, Mermaid, and SMT/Z3 artifacts
6. run backend lint
7. run compare on explicit and/or derived cases
8. create bundle or change-review package

## 6. Clinical Reviewer / MOH Reviewer

Your job:

- decide whether the clinical behavior is correct
- review changed cases, fallback behavior, and wording

What you should look at first:

- `change_summary.md`
- `impact_map.md`
- `case_delta.md`
- Mermaid outputs
- bundle or review README

What you should not be asked to do:

- debug parser errors
- reverse-engineer where a fix belongs in source artifacts

If the review package shows a changed case:

- decide whether the changed outcome is intended
- if yes, approve the authored-source change
- if no, send the correction back to the owning artifact type

## 7. Rule Of Thumb: Where To Fix Things

- variable problem -> variable catalog
- threshold or Boolean logic problem -> predicate catalog
- routing or precedence problem -> DMN
- wording or multilingual problem -> phrase bank
- generated artifact mismatch -> fix the authored source, not only the generated artifact

## 8. Minimal Command Set

Typical commands:

- `chw-nav preflight-source ...`
- `chw-nav preflight-bundle ...`
- `chw-nav compose-ir ...`
- `chw-nav import-dmn ...`
- `chw-nav lint-ir ...`
- `chw-nav build-xlsform ...`
- `chw-nav build-mermaid ...`
- `chw-nav z3-checks ...`
- `chw-nav compare ...`
- `chw-nav create-bundle ...`
- `chw-nav build-change-review ...`

## 9. Review-Oriented Example Paths

Useful examples in this repo:

- `examples/catalogs/`
- `examples/pneumonia.dmn`
- `examples/change_memos/pneumonia_covid_no_test.memo.json`
- `examples/change_memos/pneumonia_rr_cutoff_plus1.memo.json`
- `examples/pneumonia_rr_cutoff_plus1.cases.json`
