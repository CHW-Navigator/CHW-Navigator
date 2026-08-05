# WS0 Part A discovery report

Date: 2026-08-05

Status: `fail` for the combined baseline; stopped at the mandatory human gate.

Overall evidence level: **E0**. Source-lock integrity was executed, but the
mandatory Product suite has four failures and five tests across the compiler
and TypeScript suites were skipped. Passing subsets do not raise the combined
result to E1.

## Scope and method

This report is discovery only. No Product or compiler source was repaired.
The integrated work specification and blank decision template were added as
requested. The TypeScript suite ran from a disposable copy so its pinned source
was not modified.

The executed Python baselines are the current compiler suite and current
Product backend suite. Files under `old/` and independent experiments under
`Testing/` were inventoried as legacy/prototype material but were not silently
combined with the production baselines.

## Repository state

### Git roots found

| Location | Branch/commit at discovery start | Finding |
| --- | --- | --- |
| Outer workspace `CHW-Navigator/` | `master`; no commits | An uninitialized Git shell with many untracked projects, environments, generated archives, and documents. It is not a reproducible source baseline. |
| Nested `CHW-Navigator-current/` | `codex/integrate-prompt12-preparation`; `68109294878a8d53b83a18be25d704c209708d8b` | A real, initially clean Git history containing Product and compiler source. Used for executable discovery, without deciding the human authoritative-root question. |

The nested `.gitmodules` file is empty and `Product/` contains ordinary tracked
files, not a Git submodule. Several root documents still call Product a
submodule.

### Compiler working state at discovery start

- Modified tracked paths: none.
- Untracked paths: none.
- The baseline run generated only ignored artifacts.

Ignored paths were environment/test output. Committing each user-specific file
would violate the evidence-output prohibition, so the machine report records
the ignored roots, exact counts, and enumeration command.

| Ignored root | Path count | Classification | Referenced by tests? |
| --- | ---: | --- | --- |
| `compiler/.pytest_cache/` | 4 | Test-runner cache | No direct assertion |
| `compiler/build/` | 29 | Python packaging output | No direct assertion |
| `compiler/generated/cht-task-bridge-harness/` | 181 | Generated CHT bridge-harness workspace | Produced by the bridge-harness workflow; ignored execution output |
| `compiler/generated/t/` | 4,480 | Timestamped unit/golden/change-review scratch packages | Yes; multiple compiler tests write through the test scratch helpers |
| `compiler/scripts/__pycache__/` | 4 | Python bytecode cache | No |
| `compiler/src/chw_navigator/__pycache__/` | 38 | Python bytecode cache | No |
| `compiler/tests/__pycache__/` | 62 | Python bytecode cache | No |
| **Total** | **4,798** |  |  |

Exact reproduction command from the nested repository root:

```powershell
git status --porcelain=v1 --ignored --untracked-files=all -- compiler
```

### Local-data work

The local-data work is not currently uncommitted. It landed in commit
`68109294878a8d53b83a18be25d704c209708d8b` (`feat: compile registered CHT
local data`) together with implementation, examples, documentation, diagnostics,
and tests.

Key tracked files include:

- `compiler/src/chw_navigator/cht_local_data.py`;
- `compiler/src/chw_navigator/cht_xform.py`;
- `compiler/tests/test_cht_local_data.py`;
- `compiler/tests/cht_local_data_harness_runner.js`;
- `compiler/examples/cht-local-data-bindings.json`;
- `compiler/examples/cht_local_data_demo.ir.json`;
- `compiler/docs/local-data-authoring-handoff.md`.

Focused result: 8 tests ran; 7 passed and 1 skipped. The skipped official CHT
harness test reported: `The installed xsltproc is not executable by the
official CHT harness`.

The handoff accurately identifies the remaining boundary: Product Gen7/Gen8
emits a seven-part `clinical_logic` object, not canonical compiler Clinical IR.
There is no deterministic adapter between them, and Product naming metadata is
not the reviewed CHT local-data registry.

## Status and readiness claim conflicts

The following material top-level claims were found. They are quoted without
editing their source.

### Active-root conflict

- Outer `project_status.md:14`: `Active working root: [CHW Navigator-work](...)`.
- Outer `project_status.md:21`: ``REQUIRED`: Use `NEXT_BOUNDED_MILESTONE.md` as
  the current milestone contract`.
- Outer `project_status.md:34`: `Clarify the authoritative working root between
  the repo root and CHW Navigator-work.`
- Nested `README.md:146`: `If umbrella docs and Product/ disagree on behavior,
  Product/ on main wins.`
- Nested `STATUS.md:3`: `For deep implementation details, Product/ docs are the
  source of truth.`

These claims conflict with each other and with current practice: executable
compiler work is in the nested repository on
`codex/integrate-prompt12-preparation`, not Product `main` or `CHW
Navigator-work`. The human gate must select one root and disposition the stale
claims.

### Git-state conflict

- Outer `project_status.md:16`: `Current working tree has 16 uncommitted paths.`

The outer Git shell now contains far more untracked content, including complete
working copies and environments, while the nested repository was clean at
discovery start. The claim is stale and is not a usable baseline assertion.

### Product/submodule conflict

- Nested `handoff.md:39`: `Product submodule (authoritative implementation)`.
- Nested `handoff.md:165`: `Day-to-day implementation lives in the Product
  submodule`.
- Nested `README.md:146`: `submodule docs and code are the spec for the running
  system`.

`Product/` is not a submodule in this checkout. It is a tracked directory in
the same Git repository. The empty `.gitmodules` file and ordinary Product file
index entries mechanically contradict these claims.

### Readiness/test conflict

- Nested `README.md:3`: the pipeline produces `deployment-ready artifacts`.
- Nested `STATUS.md:19-28`: the section is `Shipped (current)` and lists
  converters, runtime app, core automated tests, and cross-check harnesses as
  current.
- Nested `STATUS.md:24`: Gen7 is identified as the current extraction path.
- Nested `handoff.md:58`: `on the order of 40 backend tests`.

Current evidence does not support an unqualified deployment-ready claim:

- Product's complete suite has four failures.
- The compiler official local-data harness is skipped.
- The source lock explicitly says exact CHT 4.22.0/5.2.0 runtime, live CouchDB,
  offline devices, and production identity/conflict behavior have not run.
- Product contains Gen8 and operational layers not reflected in the old Gen7
  status summary.
- The Product suite currently collects 82 tests, not approximately 40.

`QUALITY_AND_VERIFICATION.md` and `PLATFORM_INTEGRATION.md` primarily describe
models and checklists rather than asserting those gates passed; no conflicting
pass claim was assigned to them.

## Baseline execution

### Compiler Python suite

Command shape: root virtual environment, `PYTHONPATH=src`, complete unittest
discovery under `compiler/tests`.

| Result | Count |
| --- | ---: |
| pass | 135 |
| fail | 0 |
| skipped | 1 |
| not_run | 0 |
| total | 136 |

Result: suite command exited 0. Subset evidence: E1. Combined evidence remains
E0 because the mandatory Product suite failed and the E3-oriented local-data
harness did not execute.

### Product Python suite

The root `.venv` did not contain `pytest`. Product's existing
`Product/.e2e-venv` did, so the complete backend collection ran there rather
than being recorded as `not_run`.

| Result | Count |
| --- | ---: |
| pass | 78 |
| fail | 4 |
| skipped | 0 |
| warnings | 2 |
| total | 82 |

Failures:

1. `tests/test_converters.py::TestDMNConverter::test_contains_activator` expects
   `COLLECT`, while the fixture lacks an activator hit policy and the converter
   defaults it to `FIRST`.
2. `tests/test_converters.py::TestCSVConverter::test_phrases_csv_has_headers`
   expects `english_text`, while the converter intentionally emits `text`.
3. `tests/test_validators.py::TestValidLogic::test_all_validators_pass` fails
   because the purportedly valid fixture's activator references undefined
   modules `mod_diarrhea` and `mod_fever`.
4. `tests/test_validators.py::TestValidLogic::test_architecture_passes` fails for
   the same undefined-module defect.

Both warnings are `PytestCollectionWarning` for helper classes `TestItem` and
`TestSuite` with constructors in `validators/test_suite.py`.

All failing expectations, converter behavior, and invalid fixture references
date to the same initial commit. The baseline therefore appears not to have
been enforced as one complete root-level gate, rather than having been broken
only by the most recent compiler changes.

### Pinned TypeScript suite

The source `@chw-navigator/prompt14-reviewed-handoff` version `1.8.0` was copied
to a temporary directory excluding `node_modules`; `npm ci` and the unmodified
`npm test` script ran there. The pinned source itself was not edited.

| Result | Count |
| --- | ---: |
| pass | 615 |
| fail | 0 |
| skipped | 4 |
| not_run | 0 |
| total | 619 |

The build and all eleven package suites completed. Subset evidence: E1. This
does not prove target-runtime or deployment conformance.

### Combined test ledger

| Result | Count |
| --- | ---: |
| pass | 828 |
| fail | 4 |
| skipped | 5 |
| not_run | 0 |
| total | 837 |

Overall: `fail`. Skips and passing suites do not cancel failures.

## Skip audit

### Compiler skip

`tests.test_cht_local_data.CHTLocalDataTests.test_generated_xform_reads_contact_and_uses_missing_fallback_in_official_harness`

- Reason: installed `xsltproc` is not executable by the official CHT harness.
- Risk: a normal compiler run can be green without executing the official
  browser/XForm local-data behavior.
- Required Part B guardrail: the release-mode baseline verifier treats this as
  a required skip and fails, while ordinary discovery records it distinctly.

Other conditional compiler skips did not trigger in this environment: Node
execution, TypeScript composer compatibility, special-function module
execution, and the attached Prompt 12 source lock all ran.

### TypeScript skips

All four skips use `process.platform === "win32"` with reason `symlink semantics
differ on Windows`:

1. `packages/cht-integration/test/core.test.mjs`: `symlinked evidence is rejected`.
2. `packages/cht-integration/test/red-team.test.mjs`: `malicious symlink in a managed destination path blocks planning`.
3. `packages/cht-integration/test/red-team.test.mjs`: `symlinked integration state cannot authorize managed replacement`.
4. `packages/cht-integration/test/red-team.test.mjs`: `symlinked bundle manifest is rejected before parsing`.

These conditions are always true in Windows CI and can therefore silently
omit four filesystem-security cases while the aggregate suite exits 0. The
oracle must remain green-with-skips, not fully conformant. A non-Windows
required CI job or Windows-native junction/reparse-point tests are needed
before these cases can satisfy a release gate.

## Source-lock verification

`compiler/scripts/verify_prompt12_source_lock.py` executed against
`compiler/integration/prompt12-source-lock.json` and the attached reviewed
workspace. Package name/version and every declared SHA-256 matched. Result:
`pass`, E0.

The lock's external limits remain operative:

- no exact CHT 4.22.0 or 5.2.0 runtime execution;
- no live CouchDB upload or offline-device execution;
- no production identity/authorization/reconciliation validation;
- no live CouchDB/FHIR conflict or staffed review-queue execution;
- pinned isolated harness dependency risk still needs disposition.

No lock update is justified in WS0 Part A.

## Prior prompt status

Prompt numbers are overloaded between the reviewed TypeScript handoff and the
target repository's Python integration history. The execution language and
evidence source must always accompany a prompt number.

| Work | Target/status | WS0 disposition finding |
| --- | --- | --- |
| Reviewed Prompts 5-7 | Present in the pinned TypeScript archive | Reference/oracle history only; no independent claim that these are Python production implementations. |
| Product Prompt 8 | Python operational contracts landed in `a4ab6b5` | Candidate/lifecycle contracts exist in Product; deterministic local evidence only. |
| Product Prompt 9 | Python topology core landed in `b51ba1e` | Typed topology validation/resolution exists; no live deployment topology source. |
| Product Prompt 10 | Python planning layer landed in `d75a52e`, with admission caveats in `8e9bb6c` | Planning only; it cannot send or claim delivery. |
| Reviewed Prompt 11A | Implemented in pinned TypeScript | Python target claims-audit slice remains planned; TypeScript evidence is not Python execution evidence. |
| Reviewed Prompt 11B | Implemented in pinned TypeScript | Python degraded-operation/fallback slice remains planned; FHIR backend is absent. |
| Reviewed Prompts 12A/12B, 13, 14 | Implemented in pinned TypeScript and semantically translated into Python in `a1e134a` | Python has vocabulary/special-function, identity boundary, and pure conflict contracts; live adapters and exact target evidence remain external. |
| CHT task lowering follow-on | Python compiler commit `996556a` | Emits connected form task-intent fields and `tasks.js`; compatibility with the TypeScript AST composer is tested. |
| Registered local-data follow-on | Python compiler commit `6810929` | Bounded registered contact/contact-summary/task-input reads exist; arbitrary report/PouchDB search does not. |

### Prompt B and mini-manual status

- `Product/backend/operational/capability_scan_prompt.py` defines
  `CAPABILITY_SCAN_PROMPT`.
- Repository search finds no import or invocation of that constant.
- `gen8.pipeline.run` accepts externally supplied `operational_requirements`
  and `registry_snapshot` sidecars, but the normal session-manager path does
  not supply them.
- Ten three-page synthetic packages exist under
  `Product/backend/tests/e2e_fixtures/` and are valuable for structure,
  grounding, admission, reference-oracle, and local-only sink behavior.
- `test_synthetic_e2e_fixtures.py` does not call Prompt B and is therefore not
  a Prompt B unit/evaluation suite.

Prompt B tests belong in later WS4, after tracer-driven contract correction.
Recorded deterministic outputs should run in pull requests; live-model
evaluation must be separate and must not see its answer oracle.

### Canonical boundary

Product Gen8 still emits its own seven-part `clinical_logic` object. The Python
compiler consumes typed canonical `ClinicalIRDocument`. No adapter currently
connects them. Prompt-only additions would therefore create data with no
deterministic consumer. This boundary is a WS5 concern after WS2, not something
to paper over during WS0.

## Root causes and required generalized guardrails

| Defect class | Root cause found | Mechanical guardrail required in Part B or later |
| --- | --- | --- |
| Ambiguous repository/source of truth | An uninitialized outer Git shell, copied workspaces, and stale documents name different roots; status claims are not bound to a commit. | Root-independent verifier records selected root, branch, commit, source lock, and normal Git status and refuses release mode outside that root. |
| Product baseline red since initial material | Tests, converter contracts, and the “valid” fixture were committed together without one enforced complete suite. | One root command executes compiler and Product suites; release mode fails on any failure, collection warning, or required skip. |
| Green aggregate can hide missing security/harness behavior | Conditional skips are reported by framework output but not elevated into release semantics. | Structured manifest preserves every skip reason; required skip policy fails release mode. |
| Stale readiness language | Top-level claims are prose not mechanically capped by current evidence. | Evidence manifest computes a minimum E-level; readiness text must reference a current manifest/digest or be marked non-authoritative. |
| Prompt B appears implemented when only prompt text exists | Definition, deterministic sidecar consumer, and synthetic fixtures live separately without an invocation/test path. | WS4 adds prompt-construction tests, recorded outputs, live-eval separation, and an invocation reference check. |
| Product/local-data integration gap | Product and compiler evolved different IR contracts; local-data capability was added only to canonical compiler IR. | WS5 adds an explicit, loss-detecting adapter or changes Product to emit canonical IR; unsupported fields fail rather than drop. |

## Human gate

Part A is complete. The five substantive decisions plus decision owner/date in
`compiler/docs/ws0-decisions-template.md` remain `UNSET`; gate status is
`not_supplied`.

Do not create ADR-001, the overlap map, baseline verifier, work log, WS1
contracts, or WS2 tracer until a human completes the template and separately
authorizes repair of the failing Product baseline.
