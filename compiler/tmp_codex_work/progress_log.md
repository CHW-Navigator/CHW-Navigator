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
- Extended bundle generation so each evidence bundle now stores staged lint reports for:
  - base IR
  - DMN input
  - explicit patient cases when provided
  - merged IR
  - generated XLSForm
  - generated Mermaid
  - generated SMT2
- Re-ran focused regression with:
  - `python -m unittest tests.test_bundles tests.test_staged_lint -v`
  - the run passed with the shared `.venv` interpreter
- Checked DOB/age support boundaries and recorded a blocker:
  - validator/lint know helper names like `date_diff_days` and `age_months_from_date`
  - end-to-end execution support is not yet confirmed across evaluator, XLSForm, and Z3
- Added process docs:
  - `docs/authoring-guide.md`
  - `docs/source-of-truth-editing-policy.md`
- Linked the new process docs from `README.md` and `contracts/README.md`.
- Added a real `build-change-review` CLI command on top of the existing change-control engine.
- Added regression coverage for:
  - CLI-based change-review package creation
  - the pneumonia fast-breathing cutoff shift proof
- Ran focused change-control regression with:
  - `python -m unittest tests.test_change_control -v`
  - the run passed with the shared `.venv` interpreter
- Added an independent headless XLSForm runner and integrated it into `compare_backends(...)`.
- Added regression coverage for:
  - headless runner parity with the generated XLSForm runtime
  - comparison log shape after headless integration
- Ran focused headless regression with:
  - `python -m unittest tests.test_headless_runner -v`
  - `python -m unittest tests.test_artifact_drift tests.test_engine_logs -v`
  - both runs passed with the shared `.venv` interpreter
- Implemented a working DOB/day-serial helper path across:
  - evaluator
  - Z3 lowering
  - generated XLSForm lowering
  - generated XLSForm runtime
  - headless XLSForm runner
  - generated XLSForm re-import
- Added helper support for:
  - `is_missing(...)`
  - `date_diff_days(...)`
  - `age_months_from_date(...)`
  - `floor(...)`
- Added regression coverage in `tests/test_date_helpers.py` for:
  - cross-engine compare on explicit DOB/day-serial cases
  - missingness handling for birth date presence
  - generated XLSForm round-trip back into IR
- Ran focused DOB/date regression with:
  - `python -m unittest tests.test_date_helpers -v`
  - `python -m unittest tests.test_xlsform_import tests.test_headless_runner tests.test_engine_logs -v`
  - both runs passed with the shared `.venv` interpreter
- Updated published guidance so the docs now describe the supported day-serial path and its current limits instead of treating DOB helpers as validator-only.
- Upgraded Mermaid staged lint to use two layers:
  - Python-side style/shape checks for graph declaration, edges, and bracket balance
  - optional `mmdc` render validation when Mermaid CLI is installed locally
- Added regression coverage for:
  - malformed Mermaid candidate text missing graph structure
  - Mermaid lint metadata showing which render backend was used
- Ran focused Mermaid/staged-lint regression with:
  - `python -m unittest tests.test_staged_lint -v`
  - `python -m chw_navigator.cli lint-mermaid examples/pneumonia.ir.json`
  - both passed; current environment reports `python_only` because `mmdc` is not installed locally
- Added more contract-aware source linters where the contracts are crisp:
  - predicate catalog:
    - detect expression variable refs missing from `inputs_used`
    - warn on `inputs_used` entries not used by the expression
    - reject non-`v_` / `st_` entries in `inputs_used`
  - phrase bank:
    - detect duplicate `entity_id` + `role` rows
    - warn when English text is missing from the row
  - simulated patient data:
    - reject `null` inside `values`
    - reject present/missing overlap
    - warn on duplicate entries in `missing`
- Beefed up Pydantic where it fits well by adding a patient-case model for source-preflight validation.
- Ran focused regression with:
  - `python -m unittest tests.test_staged_lint -v`
  - `python -m chw_navigator.cli preflight-source predicate_catalog examples/catalogs/pneumonia.predicates.json`
  - both passed
- Strengthened variable-catalog preflight further for numeric contract quality:
  - warn when numeric variables lack domain metadata
  - warn when numeric encounter-variable IDs do not encode stored units
  - warn when a declared `unit` is not clearly reflected in the identifier
  - warn when provenance only has `source_id` and no locator fields
  - catch inverted numeric domains explicitly in regression coverage
- Strengthened phrase-bank preflight further for authoring consistency:
  - detect per-language duplicates after normalizing codes like `text_EN` and `text_en`
  - warn when output phrases are missing `message` or `guidance` role coverage
- Fixed a bug in the new phrase-language normalization path so duplicate-language checks run correctly instead of relying on a nonexistent `.keys()` call.
- Ran focused regression and real preflight checks with:
  - `python -m unittest compiler.tests.test_staged_lint -v`
  - `python -m chw_navigator.cli preflight-source variable_catalog compiler/examples/catalogs/pneumonia.variables.csv`
  - `python -m chw_navigator.cli preflight-source phrase_bank compiler/examples/catalogs/pneumonia.phrases.csv`
  - all passed; the current pneumonia phrase bank correctly emits a warning that `o_referral` has no `guidance` role yet
- Reworked DMN source preflight from a simple subset-parse smoke test into a structured authoring linter:
  - preserve decision/rule/output counts on good files
  - report row-level authoring findings without stopping at the first unsupported construct
  - flag non-`FIRST` hit policy
  - flag `AND` / `OR` / `NOT` / parentheses in DMN input expressions and input/output cells
  - flag duplicate rule ids
  - flag rules with no output assignments
  - flag fully empty rule rows
- Wired those DMN authoring findings into `preflight-source dmn` so the source-lint report now carries real issues instead of only counts.
- Added staged-lint regression coverage for:
  - unsupported hit policy plus compound-cell logic
  - duplicate rule ids plus empty rule rows
- Ran focused DMN regression with:
  - `python -m unittest compiler.tests.test_staged_lint -v`
  - `python -m chw_navigator.cli preflight-source dmn compiler/examples/pneumonia.dmn`
  - both passed
- Surfaced evidence provenance and hashes more clearly in human-facing artifacts:
  - bundle README now includes a `Key Evidence Hashes` section with short SHA-256 fingerprints for copied inputs and key generated outputs
  - bundle metadata now records `key_artifact_hashes` explicitly, alongside the full `artifact_hashes.json` manifest
  - change-review packages now write `artifact_hashes.json`
  - change-review README now includes `Key Evidence Hashes`
  - change summary now includes a `Review Provenance` section with compiler/git info and short SHA-256 fingerprints for the memo, copied source inputs, semantic diff, and case delta
- Strengthened actual IR phrase/output coverage lint, not just phrase-bank preflight:
  - outputs now warn separately when message coverage is missing
  - outputs now warn separately when guidance coverage is missing
  - decision-produced outputs still warn when they have no runtime-facing message or guidance coverage at all
  - the current pneumonia catalog example now clearly surfaces the expected `o_referral` guidance gap at IR-lint time
- Updated regression coverage for:
  - bundle metadata/README hash visibility
  - change-review hash manifest and provenance text
  - IR-lint warning on missing output guidance coverage after DMN import
- Ran focused regression and manual evidence checks with:
  - `python -m unittest compiler.tests.test_bundles compiler.tests.test_change_control compiler.tests.test_staged_lint -v`
  - `python -m chw_navigator.cli create-bundle compiler/examples/pneumonia.ir.json compiler/examples/pneumonia.dmn --patients compiler/examples/pneumonia.cases.json --bundle-root compiler/generated/t/manual_bundle_check2 --label pneumonia-hash-check`
  - both passed
- Extended action/task phrase coverage lint:
  - `create_task` actions still warn when `message_key` is missing
  - actions now also warn when `message_key` does not exist in `phrases`
  - actions now warn when `message_key` points to a non-`message` phrase
  - actions now warn when the phrase entity does not match the action id
- Added a new cross-file source preflight step for authored source bundles:
  - new CLI command: `preflight-bundle`
  - composes metadata + variable catalog + predicate catalog + phrase bank
  - optionally imports DMN before running the cross-file checks
  - reports:
    - output phrase-coverage gaps after DMN import
    - predicate references to unknown variables
    - orphan phrase rows whose `entity_id` does not match anything in the compiled IR
- Added regression coverage for:
  - action message-key/entity mismatch
  - bundle-level warning on the current `o_referral` guidance gap after DMN import
  - bundle-level warning on orphan phrase rows
- Ran focused regression and live bundle preflight with:
  - `python -m unittest compiler.tests.test_catalog_ingest compiler.tests.test_pydantic_and_lint compiler.tests.test_staged_lint -v`
  - `python -m chw_navigator.cli preflight-bundle compiler/examples/catalogs/pneumonia.metadata.json compiler/examples/catalogs/pneumonia.variables.csv compiler/examples/catalogs/pneumonia.predicates.json compiler/examples/catalogs/pneumonia.phrases.csv --dmn compiler/examples/pneumonia.dmn`
  - both passed after rerunning `test_staged_lint` once to clear a transient Windows file lock in the shared generated test folder
- Refactored the validation stack to reduce duplication between Pydantic, semantic validation, and lint:
  - moved predicate-output prohibition into `PredicateModel`
  - moved history-freshness output prohibition into `HistoryBindingModel`
  - moved phrase-binding output-id validity into `ClinicalIRDocumentModel`
  - removed duplicated phrase-binding and predicate-output checks from `lint.py`
  - removed the same local-contract checks from `validator.py`
- Clarified validation-layer responsibilities in `compiler/README.md`:
  - Pydantic for structural/local contract failures
  - `validate_document(...)` for semantic/runtime-subset failures
  - `lint_document(...)` for non-blocking quality and coverage findings
- Updated regression coverage to reflect the new ownership:
  - predicate output references are now rejected at `ClinicalIRDocument.from_dict(...)`
  - phrase bindings to unknown outputs are now rejected at `ClinicalIRDocument.from_dict(...)`
- Ran focused cleanup regression with:
  - `python -m unittest compiler.tests.test_pydantic_and_lint compiler.tests.test_staged_lint -v`
  - all 24 tests passed
- Added a user-type manual:
  - new `docs/user-types-manual.md`
  - covers DMN authors, predicate authors, variable authors, phrase authors, operators, and clinical reviewers
  - includes “where to fix things” pointers instead of making reviewers infer artifact ownership
- Promoted the pneumonia RR cutoff-shift proof into persistent repo examples:
  - `examples/catalogs/pneumonia_rr_cutoff_plus1.predicates.json`
  - `examples/change_memos/pneumonia_rr_cutoff_plus1.memo.json`
  - `examples/pneumonia_rr_cutoff_plus1.cases.json`
  - updated `test_change_control.py` to use the persistent example instead of generating it ad hoc in scratch
- Strengthened the `XLSForm -> IR -> Z3` proof path:
  - `test_xlsform_import.py` now compares imported/generated workbooks across interpreter, XLSForm runtime, headless runner, and Z3
  - added the same parity check for the imported web tip example
- Added an external-style patient-suite example and regression:
  - `examples/external_suites/pneumonia_external_review_cases.json`
  - `tests/test_external_patient_suites.py`
  - this suite is tagged and proven across DMN, IR, XLSForm, headless, and Z3
- Updated `compiler/README.md` to point to:
  - the user manual
  - the persistent cutoff-shift review example
  - the external patient-suite example
  - the stronger imported-XLSForm proof story
- Ran focused regression with:
  - `python -m unittest compiler.tests.test_change_control compiler.tests.test_xlsform_import compiler.tests.test_external_patient_suites -v`
  - all 10 tests passed
- Added process docs for two remaining roadmap items:
  - `docs/release-workflow.md` for review gates, signoff states, bundle expectations, and versioning
  - `docs/llm-authoring-guidance.md` to separate mechanical checks that belong in code/lint from clinical-content instructions that still belong in prompts
- Added machine-checked JSON Schema export for the JSON-backed artifact families:
  - new `src/chw_navigator/json_schema_export.py`
  - new CLI command: `write-json-schemas`
  - schemas currently cover:
    - `clinical_ir`
    - `metadata`
    - `variable_catalog_json`
    - `predicate_catalog_json`
    - `phrase_bank_json`
    - `patient_case`
    - `patient_case_suite`
  - updated README and TODO to reflect that this roadmap item is now partly implemented
- Added a second small golden clinical example:
  - `examples/fever_basic.ir.json`
  - `examples/fever_basic.dmn`
  - `examples/fever_basic.cases.json`
  - `tests/test_golden_examples.py`
  - this example is intentionally simple so the repo is not overly centered on pneumonia and the router example
- Added a bounded clinical-equivalence report feature:
  - new `src/chw_navigator/equivalence.py`
  - new CLI command: `build-equivalence-report`
  - report scope is explicitly `explicit_case_suite_only`
  - added `tests/test_equivalence_report.py`
  - this addresses the roadmap item honestly without claiming whole-proof-space equivalence yet
- Refined the bounded equivalence report so it separates:
  - any semantic case mismatch count
  - output-changing case count
  - predicate-changing case count
  - rule-hit-changing case count
  - this keeps reviewer summaries honest when a source change only alters internal predicate truth on some cases but changes outputs on fewer cases
- Extended the variable-source contract and lint around numeric proof domains and scaling guidance:
  - variable payload validation now accepts precision/storage metadata such as `storage_unit`, `input_decimals`, and `display_decimals`
  - variable payload validation now structurally checks flat and nested measurement-limit fields
  - staged lint now warns when well-known clinical numeric variables declare domains narrower than the recommended broad proof domains
  - staged lint now nudges weight variables to document UI/display precision guidance
- Added a practical use-case survey:
  - new `docs/use-cases.md`
  - captures current, near-term, and future compiler use cases
  - makes the "other use cases?" backlog item concrete enough for team review
- Added a stronger XLSForm round-trip proof path:
  - new `src/chw_navigator/xlsform_proof.py`
  - new CLI command: `prove-xlsform`
  - proof package now captures imported IR, import report, workbook-pairwise parity, optional reference-IR pairwise parity, backend comparison, and Z3 checks
  - this turns the supported XLSForm importer into a reviewable quality-case workflow instead of only a parser/runtime test
- Improved newcomer orientation docs:
  - new `docs/start-here.md`
  - new `docs/contribute-dmn.md`
  - README now points directly to those docs
  - this makes it easier for a new student or clinician to find the right manual, contracts, examples, and commands quickly

## 2026-08-04 — Prompt 12A-14 integration preparation

- Created `codex/integrate-prompt12-preparation` from the clean recovered Prompt 8 base at `f9d29ab`.
- Identified the root integration risk: the reviewed handoff is a TypeScript package while this repository's authoritative compiler is Python; wholesale copying would create divergent compilers.
- Added `integration/prompt12-source-lock.json` to bind the reviewed 1.8.0 Prompt 12A-14 handoff inputs and external-gate evidence by SHA-256.
- Added `scripts/verify_prompt12_source_lock.py` so source provenance is an executable preparation gate rather than a documentary claim.
- Added focused verifier tests covering the exact-source pass case, content drift, and path escape attempts.
- Added `docs/prompt11b-prompt12-integration-plan.md` with the required prerequisite → 12A → 12B → 13 → 14 sequence, source-to-target map, acceptance gates, and explicit identity/conflict/target-runtime limits.
- Repaired the existing root virtual environment's broken package installer, installed the compiler's declared dependencies, and established clean baselines: 93 compiler tests and 41 focused operational tests pass.
- Generalized guardrail: integration work must translate locked contracts into existing ownership seams, retain prerequisite phase ordering, and rerun both baseline suites before advancing a slice.
- Re-reviewed and improved the four source prompts, then implemented all still-relevant work in the TypeScript handoff:
  - Prompt 12A removed the dead implementation-checksum declaration and added a permanent active-artifact reintroduction guard.
  - Prompt 12B passed the full source check plus real archived extension-library and six-bundle official CHT harness execution.
  - Prompt 13 added the governed `Create × Person` identity boundary, deterministic reference provider, minimal disclosure, provenance, and no-merge enforcement.
  - Prompt 14 added the mutable-field policy registry, correction-event contract, pure resolver, and local CHT/FHIR conflict fixtures.
- Repaired the source chain of custody so later phases derive from an immutable 447-file Prompt 12 baseline rather than invalidating historical Prompt 12 hashes.
- Source evidence now passes the root check, formatting check, 93-code diagnostic coverage gate, core coverage thresholds, Prompt 14 handoff verifier, and a 14-phase cross-audit with no findings.
- Refreshed the target source lock to package 1.8.0 and added identity, conflict, dead-declaration, cumulative-governance, and official-harness evidence hashes.
- Replaced the extension-library harness staging check with a real browser execution path:
  - official `cht-conf` archives the generated modules and verifies attachment bytes;
  - the archived modules are installed into the pinned CHT Core 4.11 form engine's existing XPath module;
  - both extension-bearing bundles fill and submit `technical_gestational_age` and assert status/version/result fields.
- Generalized the official runner to accept external workspaces and declare its pinned Node package path. This repaired the hidden assumption that specs always lived below the harness directory.
- Audited Prompt 12A applicability in the target Python compiler. No `implementationChecksum` or analogous dead checksum exists, so no cosmetic deletion was made; a source/contract reintroduction test now protects that boundary.
- Integrated Prompt 12B into the authoritative Python compiler:
  - shared versioned clinical vocabulary;
  - seven-code declaration/emission/test-assertion guard;
  - closed eight-status technical function contract and pinned vectors/digests;
  - explicit CHT 4.22.0 and 5.2.0 profiles;
  - native WFA `z-score()` with mandatory external-chart warning and no WFA JavaScript;
  - dependency-free gestational-age extension module and XForm;
  - non-clobbering output through the existing CHT plan/writer.
- Fresh Python-generated output passed the external browser gate for both profiles (eight assertions total), including genuine `cht:extension-lib` XPath form execution. Generated module and XForm hashes exactly match the independently reviewed source artifacts.
- Ran the full compiler suite: 107 tests passed. Re-ran the 41-test focused Product operational baseline: all passed.
- Found a source-lock test design gap: the normal test suite tested the verifier against synthetic fixtures but did not invoke the repository's real lock. Added a real-lock regression so reviewed-source drift can no longer pass the normal suite unnoticed.
- Integrated Prompt 13 into the authoritative Python package as a platform-owned
  person-registration service. Authorization is applied before matching, candidate
  disclosure is minimal, ambiguous matches defer, confirmed-new provenance must
  agree with the actual candidates/search scope/offline state, and merge attempts
  fail closed.
- Integrated Prompt 14 as a pure mutable-field resolver plus a versioned ten-field
  policy registry. It preserves distinct assertions, deterministically rejects
  divergent event-ID reuse, separates projections from unresolved conflicts, and
  keeps clinical evidence outside ordinary mutation.
- Audited the target Product package for a live person-registration or backend
  synchronization seam. None exists; the safe integration point is therefore the
  compiler-neutral platform contract, with live CHT/FHIR/queue wiring retained as an
  explicit external gate rather than an invented implementation.
- Root cause found during the exhaustive source check: the shared clinical vocabulary
  and CHT special-function implementation changed after the gestational function's
  multi-file implementation digest was registered. The artifact verifier correctly
  failed. Refreshed the digest, added that protected registry entry to the authorized
  migration generator, and reran the cross-phase audit.
- Generalized guardrails from that failure: identity-provider match features now use
  the same shared clinical vocabulary (so renamed clinical fields cannot enter the
  matcher); divergent correction events sort by canonical bytes as well as event ID;
  governance treats digest refreshes as explicit protected migrations; and mutable
  conflict resolution rejects reordered authority policy and cross-person
  supersession chains.
- Final integration evidence: 119 authoritative compiler tests, 41 Product
  operational/synthetic tests, the full reviewed TypeScript `npm run check`, the
  447-file/29-migration cross-phase audit, the six-bundle official CHT gate, and the
  two-profile fresh Python-generation gate all passed. Both Python-generated forms
  exercised the real CHT Core 4.11 XPath extension implementation with officially
  archived attachment bytes.
- A read-only merge simulation against local `main` reported zero textual conflicts.
  The reviewed TypeScript handoff remains an explicit external integration input;
  standalone clones transparently skip its real-lock assertion, while the dedicated
  source-lock and official-harness commands remain required pre-merge evidence gates.

## 2026-08-04 — CHT task bridge

- Root cause: the Python and TypeScript implementations used different workflow
  models, and the earlier integration copied Prompt 12A-14 features without creating
  the form-data/task-rule seam. Copying `tasks.js` alone would have produced rules
  that never matched Python-generated reports.
- Added `cht-task-bindings@1.0.0` so target-owned form, translation, permission,
  timing, role, icon, and priority values are explicit instead of inferred.
- Connected Clinical IR `create_task` lowering to both sides of the CHT behavior:
  matching XLSForm task-intent fields and deterministic report-based `tasks.js`.
- Preserved the reviewed TypeScript rule identities, canonical-intent duplicate
  suppression, resolution window, and generated module shape. The Python output is
  executed under Node and accepted by the reviewed TypeScript AST composer.
- Added a permanent diagnostic guard for invalid bindings, unbound task types,
  unsupported schedules/roles, and generated task-identity collisions. Every new
  code is emitted and asserted by tests.
- Generalized guardrail: a backend behavior that consumes stored fields must be
  generated and tested with the producer of those fields; a plan-only placeholder
  may not be described as an implemented backend action.
- Explicit limit: `read_history` is still plan-only because there is no TypeScript
  implementation to bridge and no target-approved CHT document/field lookup contract.
