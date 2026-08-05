# CHW Navigator

CHW Navigator is the start of a compiler toolkit for translating structured clinical logic into:

- DMN-oriented execution inputs
- XLSForm
- Z3 models
- Mermaid audit views

The authored clinical source of truth is:

- variable catalog
- predicate catalog
- DMN decision tables
- phrase bank

Clinical IR is the canonical compiled representation used for execution, QA, and backend generation. Everything else in the toolchain compiles through that shared semantic layer after ingest from those authored sources.

Temporary compatibility adapters for one-off external artifact shapes should stay outside the core compiler contracts. As of 2026-05-05, the `gen7` mini-compiler bridge is intentionally kept separate from the main compiler branch and should not be treated as a long-term supported authoring path.

Supporting process docs:

- `docs/authoring-guide.md`
- `docs/user-types-manual.md`
- `docs/dmn-intake-runbook.md`
- `docs/release-workflow.md`
- `docs/llm-authoring-guidance.md`
- `docs/source-of-truth-editing-policy.md`

## Current scope

- typed Clinical IR data model
- normalized expression AST model
- semantic validator
- reference interpreter
- subset DMN import for decisions
- initial Z3 lowering
- Z3 QA checks with witness patients
- minimal Form IR and XLSForm CSV backend
- generated XLSForm runtime for comparison
- independent headless XLSForm runner for parity checks
- Mermaid audit graph generation
- staged linting for source inputs, compiled IR, and generated backends
- provenance validation and backend source maps
- evidence bundles that now carry lint reports and artifact hashes
- change-review package generation for baseline-vs-updated clinical deltas
- example IR document
- hardened DMN XML parsing via `defusedxml`
- reviewed CHT 4.22/5.2 special-function lowering with an isolated official harness
- platform-owned person registration and mutable administrative-conflict contracts

## Validation layers

The compiler now uses a clearer validation split:

- Pydantic/schema validation:
  - structural contract checks
  - identifier-family checks
  - local cross-field checks that do not require execution semantics
- `validate_document(...)` semantic validation:
  - expression typing
  - decision semantics
  - dependency ordering
  - runtime-subset compatibility
- `lint_document(...)` quality lint:
  - coverage gaps
  - dead or suspicious authored elements
  - workflow-policy guidance
  - non-blocking review findings

In short: invalid payload shape should fail in Pydantic first, semantic impossibility should fail in `validate_document`, and review-quality concerns should show up in lint.

## Project layout

- `src/chw_navigator/clinical_ir.py`: canonical compiled data model
- `src/chw_navigator/catalogs.py`: standalone variable/predicate/phrase catalog ingest
- `src/chw_navigator/validator.py`: semantic checks
- `src/chw_navigator/evaluator.py`: Clinical IR reference interpreter
- `src/chw_navigator/dmn.py`: DMN decision-table import for the supported subset
- `src/chw_navigator/z3_backend.py`: initial Z3 lowering
- `src/chw_navigator/form_ir.py`: lightweight workbook model for generated forms
- `src/chw_navigator/xlsform_backend.py`: Clinical IR to XLSForm CSV backend
- `src/chw_navigator/xlsform_expr.py`: parser for the supported XLSForm expression subset
- `src/chw_navigator/xlsform_import.py`: supported XLSForm survey/choices import back into Clinical IR
- `src/chw_navigator/xlsform_runtime.py`: evaluator for the generated XLSForm subset
- `src/chw_navigator/headless_runner.py`: independent headless XLSForm evaluator used for cross-engine parity
- `src/chw_navigator/compare.py`: cross-engine comparison harness
- `src/chw_navigator/mermaid_backend.py`: Mermaid flowchart generation from canonical logic
- `src/chw_navigator/bundles.py`: immutable intake bundle creation for inputs, outputs, and test evidence
- `src/chw_navigator/change_control.py`: change-review package generation for clinician-facing delta review
- `src/chw_navigator/cli.py`: command-line entry points
- `src/chw_navigator/json_schema_export.py`: machine-checked JSON Schema export for supported JSON artifact families
- `src/chw_navigator/person_identity.py`: four-outcome person-registration boundary and deterministic fixture provider
- `src/chw_navigator/mutable_conflicts.py`: assertion-preserving mutable-field correction resolver
- `src/chw_navigator/cht_tasks.py`: versioned CHT task bindings, form task-intent rows, and deterministic `tasks.js` generation
- `tests/test_dmn_fail_loud.py`: fail-loud coverage for unsupported DMN inputs
- `tests/test_artifact_drift.py`: mutated artifact drift detection across DMN, XLSForm, Mermaid, and IR
- `tests/test_multi_module_router.py`: multi-table traffic-cop example with module priority and follow-on treatment/dosing tables
- `examples/pneumonia.ir.json`: minimal working Clinical IR example
- `examples/catalogs/`: standalone catalog examples for `compose-ir`
- `examples/pneumonia.cases.json`: explicit comparison cases
- `examples/pneumonia.missing.ir.json`: missingness-aware Clinical IR example
- `examples/pneumonia.missing.cases.json`: explicit comparison cases with allowed-missing inputs
- `examples/multi_module_router.ir.json`: multi-table module-routing example with treatment/dosing follow-on decisions
- `examples/multi_module_router.dmn`: DMN counterpart for the multi-table module-routing example
- `examples/multi_module_router.cases.json`: explicit comparison cases for the multi-table module-routing example
- `examples/state_prefix.ir.json`: minimal example showing supported `st_` state-variable prefix usage
- `examples/fever_basic.ir.json`: small second golden clinical example with a DMN counterpart and explicit cases
- `examples/fever_basic.dmn`: DMN counterpart for the small fever example
- `examples/fever_basic.cases.json`: explicit cases for the fever example
- `examples/cht_task_demo.ir.json` and `examples/cht-task-bindings.json`: connected Clinical IR `create_task` to CHT form/task-rule example
- `examples/catalogs/pneumonia_rr_cutoff_plus1.predicates.json`: persistent changed-source predicate example for review-package and diff testing
- `examples/change_memos/pneumonia_rr_cutoff_plus1.memo.json`: change memo paired with the cutoff-shift review example
- `examples/pneumonia_rr_cutoff_plus1.cases.json`: explicit changed-case suite for the cutoff-shift review example
- `examples/external_suites/pneumonia_external_review_cases.json`: external-style patient suite that is compared across DMN, IR, XLSForm, headless, and Z3

## Run the validator

```bash
$env:PYTHONPATH='src'; python -m chw_navigator.cli validate examples/pneumonia.ir.json
```

Or install the package in editable mode and use the console script:

```bash
pip install -e .
chw-nav validate examples/pneumonia.ir.json
```

## Write machine-checked JSON Schemas

```bash
$env:PYTHONPATH='src'; python -m chw_navigator.cli write-json-schemas generated\schemas
```

This currently writes JSON Schemas for:

- `clinical_ir`
- `metadata`
- `variable_catalog_json`
- `predicate_catalog_json`
- `phrase_bank_json`
- `patient_case`
- `patient_case_suite`

These cover the JSON-shaped artifact families that already have Pydantic-backed validation.

## Compose a base IR from standalone catalogs

```bash
$env:PYTHONPATH='src'; python -m chw_navigator.cli compose-ir examples/catalogs/pneumonia.metadata.json examples/catalogs/pneumonia.variables.csv examples/catalogs/pneumonia.predicates.json examples/catalogs/pneumonia.phrases.csv --output generated\catalog_demo\pneumonia.base.ir.json
```

This command accepts:

- variable catalog as `.csv` or `.json`
- predicate catalog as `.csv` or `.json`
- phrase bank as `.csv` or `.json`

Phrase bank rows should use `text_<language>` columns such as `text_en` and `text_fr`. Use `entity_id` to point at the variable, predicate, or output the phrase belongs to. For convenience, `variable_name` is also accepted as an alias for `entity_id`.

Structured provenance is required throughout the authored inputs. The variable catalog contract shows the baseline pattern, and the same structured provenance shape should be used across predicate catalogs, phrase banks, DMN-derived artifacts, patient suites, and QA logs.

EHR/history-fed fields should stay in the same identifier families and use an `_h` suffix when helpful, for example:

- `v_weight_kg_h`
- `v_last_hb_h`
- `st_prev_referral_h`

For isolated local work, you can also use the project virtual environment:

```bash
python -m venv .venv
.\.venv\Scripts\python -m pip install -e .
```

## Evaluate one patient

```bash
$env:PYTHONPATH='src'; python -m chw_navigator.cli evaluate examples/pneumonia.ir.json examples/patient.home-treatment.json
```

## Import decisions from DMN

```bash
$env:PYTHONPATH='src'; python -m chw_navigator.cli import-dmn examples/pneumonia.ir.json examples/pneumonia.dmn
```

If the base IR came from standalone catalogs, `import-dmn` now infers missing output declarations from the DMN output columns before validating the merged document.

## Import a supported XLSForm back into Clinical IR

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli import-xlsform generated\pneumonia\survey.csv generated\pneumonia\choices.csv --guideline-id pneumonia_imported --output generated\test_artifacts\imported_pneumonia.ir.json
```

This importer currently supports:

- generated CHW Navigator XLSForm workbooks
- simple hand-authored rows using:
  - `integer`
  - `decimal`
  - `text`
  - `select_one yes_no`
  - simple `select_one <list>`
  - `calculate`
  - `note`

It reconstructs:

- variables
- predicates
- decisions and rule order
- outputs
- note-backed phrases for output messages/guidance

For XLSForms written outside CHW Navigator, the importer is permissive about naming and then normalizes into canonical IR identifiers:

- question rows are normalized to canonical variable IDs such as `v_amount`
- calculate rows are normalized to canonical predicate/output IDs such as `p_eligible` or `o_tip`
- embedded `${...}` references in calculations, `relevant`, and labels are rewritten to follow those canonical IDs
- the importer emits a structured report with `normalized`, `warning`, and `error` findings

If you pass `--output`, the CLI writes the imported IR and a sidecar report at `*.import-report.json`.

and then the imported IR can go directly into:

- `z3-summary`
- `z3-checks`
- `build-mermaid`
- `build-xlsform`
- `compare`

The regression suite now treats imported XLSForms as proof targets, not just parser targets:

- generated `survey.csv` + `choices.csv` are imported back into IR
- the imported IR is validated
- the imported IR is compared across interpreter, generated XLSForm runtime, headless runner, and Z3 on explicit patient cases

## Build an XLSForm round-trip proof package

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli prove-xlsform generated\pneumonia\survey.csv generated\pneumonia\choices.csv generated\xlsform_proof --reference-ir examples\pneumonia.ir.json --patients examples\pneumonia.cases.json
```

This command is the stronger quality-proof path for the supported XLSForm subset:

- it imports the XLSForm back into Clinical IR
- it writes the imported IR and import report
- it compares the imported IR against the original workbook on a patient suite
- it optionally compares the imported IR against a supplied reference IR
- it runs backend comparison and Z3 checks on the imported IR
- it writes a short proof summary plus machine-readable evidence files

## Run post-compile quality checks

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli quality-check examples\pneumonia.ir.json generated\quality_check --patients examples\pneumonia.cases.json
```

This command writes a local quality package for a compiled IR:

- it compiles XLSForm, Mermaid, and SMT-LIB artifacts
- it runs IR lint plus backend-specific lint
- it runs the XLSForm round-trip proof against the generated workbook
- it runs backend comparison and Z3 checks
- it marks release blockers such as decision-relevant variables with no documented collection path

If you also want an external upload-based confirmation, the quality package points to [XLSForm Online](https://getodk.org/xlsform/), which ODK documents as a temporary preview path for XLSForms.

## Check Z3 lowering

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli z3-summary examples/pneumonia.ir.json
```

## Run formal Z3 checks

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli z3-checks examples/pneumonia.ir.json
```

`z3-checks` now emits the structured `engine-log` contract envelope with `log_type: "z3_checks"`.

## Generate one witness patient for a rule

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli z3-rule-patient examples/pneumonia.ir.json r2
```

## Export SMT-LIB

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli export-smt2 examples/pneumonia.ir.json --output generated\test_artifacts\pneumonia.smt2
```

## Compare an SMT-LIB candidate

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compare-smt2 examples/pneumonia.ir.json generated\test_artifacts\pneumonia.smt2 --patients examples/pneumonia.cases.json
```

## Build XLSForm CSV sheets

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli build-xlsform examples/pneumonia.ir.json generated\pneumonia
```

This writes:

- `survey.csv`
- `choices.csv`
- `source-map.json`

## Build Mermaid audit graph

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli build-mermaid examples/pneumonia.ir.json --output generated\pneumonia\pneumonia.mmd
```

This also writes a companion Mermaid source map at `pneumonia.mmd.source-map.json`.

The Mermaid backend now defaults to a more clinician-friendly style:

- left-to-right layout
- larger labels
- color-coded variables, predicates, decisions, outputs, and rules
- humanized labels instead of raw `v_` / `p_` / `o_` identifiers where possible
- automatic line breaks for longer rule labels

You can override the main layout knobs from the CLI:

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli build-mermaid examples/pneumonia.ir.json --output generated\pneumonia\pneumonia.mmd --direction TD --font-size 30
```

## Create an immutable intake bundle

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli create-bundle examples/pneumonia.ir.json examples/pneumonia.dmn --patients examples/pneumonia.cases.json --bundle-root generated\bundles --label pneumonia-demo
```

Each bundle gets a fresh timestamped folder and is never overwritten. The bundle includes:

- copied source inputs under `inputs/`
- generated IR, XLSForm, Mermaid, and SMT-LIB outputs under `outputs/`
- baseline comparison reports under `tests/good/`
- a mutation workspace plus manifest under `mutations/`
- `metadata.json` and `README.md` with compiler version, source paths, and provenance

## Build the persistent cutoff-shift review example

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compose-ir examples/catalogs/pneumonia.metadata.json examples/catalogs/pneumonia.variables.csv examples/catalogs/pneumonia_rr_cutoff_plus1.predicates.json examples/catalogs/pneumonia.phrases.csv --output generated\catalog_demo\pneumonia_rr_cutoff_plus1.base.ir.json
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli import-dmn generated\catalog_demo\pneumonia_rr_cutoff_plus1.base.ir.json examples/pneumonia.dmn --output generated\catalog_demo\pneumonia_rr_cutoff_plus1.ir.json
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli build-change-review examples/change_memos/pneumonia_rr_cutoff_plus1.memo.json examples/pneumonia.ir.json generated\catalog_demo\pneumonia_rr_cutoff_plus1.ir.json generated\reviews --patients examples/pneumonia_rr_cutoff_plus1.cases.json --baseline-dmn examples/pneumonia.dmn --updated-dmn examples/pneumonia.dmn
```

This example is intentionally small:

- only one authored predicate threshold changes
- the review package shows which patient case changes
- the generated diff is meant to be understandable to clinicians and technical reviewers

## Build a bounded clinical-equivalence report

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli build-equivalence-report examples/fever_basic.ir.json examples/fever_basic.ir.json examples/fever_basic.cases.json generated\equivalence
```

This report is intentionally scoped:

- it compares two IR documents on an explicit supplied patient suite
- it reports both any-semantic mismatch counts and output-changing case counts
- it does not claim whole-proof-space equivalence
- it is useful for reviewer-facing “same behavior on these cases?” checks while fuller proof-space equivalence remains future work

## Team Docs

- [Start here](./docs/start-here.md)
- [Authoring guide](./docs/authoring-guide.md)
- [Contribute DMN for testing](./docs/contribute-dmn.md)
- [User types manual](./docs/user-types-manual.md)
- [DMN intake runbook](./docs/dmn-intake-runbook.md)
- [Source-of-truth editing policy](./docs/source-of-truth-editing-policy.md)
- [Release workflow](./docs/release-workflow.md)
- [LLM authoring guidance](./docs/llm-authoring-guidance.md)
- [Use cases](./docs/use-cases.md)

## Compare engines on explicit cases

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compare examples/pneumonia.ir.json --dmn examples/pneumonia.dmn --patients examples/pneumonia.cases.json
```

`compare` now emits the structured `engine-log` contract envelope with `log_type: "comparison_report"`.

Missingness-aware comparison is also supported when the IR allows the input to be missing and the logic handles or defaults it before decision time:

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compare examples/pneumonia.missing.ir.json --patients examples/pneumonia.missing.cases.json
```

If `--patients` is omitted, `compare` derives a richer Z3-driven comparison suite that includes:

- endpoint-reaching patients for non-default clinical outputs
- pairwise module patients when two module-presence predicates can both be true
- cutpoint neighbors on both sides of numeric thresholds such as `n-1 / n / n+1` or `x-0.1 / x / x+0.1`
- a no-problems baseline patient
- five repeated deterministic copies of one seed patient to catch any accidental stochastic behavior

The comparison log now also records the generated case category, tags, and the Mermaid trace nodes checked for that case.

The toolkit also supports sequential multi-table workflows where later decisions read outputs produced by earlier decisions. For example:

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compare examples/multi_module_router.ir.json --dmn examples/multi_module_router.dmn --patients examples/multi_module_router.cases.json
```

## Why this comes first

The validator and canonical IR are the semantic core of the project. DMN ingest, XLSForm generation, Mermaid output, and Z3 lowering will all be safer and simpler if they target the same explicit typed representation from the beginning.

## New contributors

If you are landing in this repo for the first time:

1. start with [Start here](./docs/start-here.md)
2. if you want to submit or revise a table, read [Contribute DMN for testing](./docs/contribute-dmn.md)
3. if you need the exact file contracts, use `contracts/`
4. if you want working examples, use `examples/`

## Supported subset today

- Clinical IR expressions in the documented core subset
- `FIRST` hit policy
- DMN inputs and outputs that must use explicit `v_` or `st_` for variables, `p_` for predicates, and `o_` for outputs
- DMN cells that compile to Boolean predicate or variable checks using `true`, `false`, and `-`
- standalone authoring ingest for variable catalogs, predicate catalogs, and multilingual phrase banks
- XLSForm subset import back into Clinical IR for generated forms and a narrow hand-authored subset
- Z3 checks for predicate satisfiability, rule reachability, output reachability, decision overlap, fallback reachability, and invariant violations
- Z3 witnesses now include explicit input and predicate missingness flags
- XLSForm generation to `survey.csv` and `choices.csv` for typed variables, predicates, rule-hit calculations, outputs, and note rows
- generated-form runtime for the emitted XPath subset, including omitted optional inputs
- Mermaid flowchart generation for clinician audit
- validator-enforced provenance on core clinical entities
- backend source maps for generated XLSForm and Mermaid artifacts
- comparison output with per-engine predicate, output, and rule-hit mismatches
- immutable intake bundles so new DMN deliveries accumulate instead of replacing older audit evidence

## Current limitations

- The decision engine remains point-in-time. Registered scalar values already present in supported CHT form contexts can be loaded into history variables, but report searches, longitudinal trends, and aggregated histories are not yet supported.
- Scalar carry-forward state can be represented today with `st_` variables such as `st_fever_done`, but list-valued or longitudinal state is not yet first-class.
- `FIRST` is enforced per decision, not globally. Multiple decisions may coexist. Clinical IR has a bounded `create_task` action that the CHT backend lowers to stored task-intent report fields plus report-based `tasks.js`; this is not an aggregated care-plan model.

## Build a connected CHT task bundle

`build-cht` compiles a Clinical IR form and its `create_task` actions together. The
generated XLSForm source stores `required`, `task_type`, timing, follow-up form, and
operation-ID fields. The generated `tasks.js` reads those exact fields. This prevents
the previous failure mode where a task rule existed separately from the form data it
needed.

```powershell
chw-nav build-cht `
  examples/cht_task_demo.ir.json `
  examples/cht-task-bindings.json `
  generated/cht-task-demo
```

The task-binding file is deployment configuration, not clinical policy. It must name
the exact CHT version, follow-up form, translation and permission keys, timing window,
role, icon, and priority. Missing task types, unsupported absolute due-date
expressions, role mismatches, and generated identity collisions fail closed.

The output contains executable `tasks.js`, matching XLSForm survey/choices source,
task and local-data plans, hashes, and a bundle manifest. The `tasks.js` module is
accepted by the reviewed TypeScript AST composer, which inserts or replaces its
managed block without overwriting unrelated destination rules. XLSForm conversion,
target-project compilation, the official CHT harness, and exact target-runtime tests
remain deployment gates.

## Read registered on-device CHT data

The optional `cht-local-data-bindings@1.0.0` registry turns an IR
`read_local_data` action (or its legacy `read_history` spelling) into an exact CHT
form read. The IR names a versioned binding; it never contains an arbitrary CouchDB
query or deployment XPath.

```powershell
chw-nav build-cht `
  examples/cht_local_data_demo.ir.json `
  examples/cht-task-bindings.json `
  generated/cht-local-data-demo `
  --local-data-bindings examples/cht-local-data-bindings.json `
  --form-context contact
```

Registry version 1 supports three reviewed adapters:

- `cht_contact_field`: a declared field under `inputs/contact`, available from a contact or task launch;
- `cht_contact_summary`: a declared `instance('contact-summary')/context/...` value, available from a contact profile;
- `cht_task_input`: a declared field under `inputs`, available from a task launch.

Every binding declares its value type, meaning, subject, supported launch contexts,
and either `immutable` freshness or an observation-date path plus `max_age_days`.
The compiler rejects unknown binding IDs, XPath-like injected paths, context
mismatches, type/unit mismatches, and conflicting freshness declarations. Runtime
failure is explicit: `soft_missing`, `ask_if_missing`, or `hard_error`.

The bundle contains CSV XLSForm source and a directly executable CHT XForm for
registered reads. The official harness regression covers contact injection and the
missing-value fallback when its browser and `xsltproc` prerequisites are present.
Arbitrary local report/PouchDB search remains deliberately unsupported. See
[`docs/local-data-authoring-handoff.md`](docs/local-data-authoring-handoff.md) for
the exact upstream LLM handoff and the Product-to-Clinical-IR boundary that remains.

- Form structure is intentionally minimal today. Groups, repeats, and multivalue variables are not yet supported by the current validator/runtime path.
- The XLSForm importer is intentionally narrow. It does not yet support general question `relevant`, general `constraint`, repeats, groups, or arbitrary legacy production forms.
- External lookup tables and nonlinear or lookup-backed math are not supported in the current Z3 boundary. Unsupported constructs should be rejected rather than approximated.
- Legacy XLSForm ingest remains a narrow planned subset, not a general importer for arbitrary production forms.

## Important assumptions

- Clinical IR examples are expected to include provenance on variables, predicates, decisions, rules, outputs, and invariants.
- `compare` accepts missing inputs when the variable is allowed to be missing and the logic resolves or safely handles missingness before any decision depends on it.
- Predicate missingness policy is part of XLSForm lowering: `treat_missing_as_false` is compiled explicitly, while `require_inputs` and `propagate_unknown` preserve unknown values in the generated runtime.
- Phrase bindings currently map `message_key` and optional `guidance_key` into output-gated XLSForm `note` rows.
- Phrase bank rows with `role=label` are used as XLSForm labels when present. Phrase rows with `role=message` or `role=guidance` attached to outputs are used as note text when those outputs exist.
- Unsupported constructs are rejected intentionally rather than approximated.
- DMN parsing uses `defusedxml` rather than the standard library XML parser so uploaded decision tables are not processed with unsafe entity expansion.
- If a fail-safe fallback rule is added by the system, it should carry explicit provenance such as `source_id: SYSTEM_DEFAULT` instead of being silently merged into authored clinical logic.

Unsupported constructs should fail loudly rather than being approximated silently.

## Test coverage notes

- The test suite includes malformed DMN fixtures for each currently supported DMN failure class.
- The test suite also includes mutated DMN, XLSForm, Mermaid, and IR artifacts to confirm the comparison layer catches semantic or structural drift instead of silently accepting it.
