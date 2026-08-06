# CHW Navigator — status board

This file is the umbrella repo's quick status view. `Product/` is the authoring
application source of truth; `compiler/` is the canonical Clinical IR and
Python production-compiler source of truth. WS5 now connects one bounded,
synthetic tracer slice through a deterministic adapter; broader Product logic
still fails closed and is not yet supported.

**Last updated:** 2026-08-05

---

## Scope and source of truth

- **Current runtime implementation:** `Product/ARCHITECTURE.md`
- **Current/target pipeline vocabulary:** `Product/PIPELINE.md`
- **RLM/REPL orchestration rationale:** `Product/ORCHESTRATOR.md`

When this file and `Product/` disagree, trust `Product/`.

---

## Implemented locally (not deployment approval)

| Capability | Status | Owner path | Evidence |
|---|---|---|---|
| Manual ingestion (PDF -> structured guide) | Current | `Product/backend/ingestion/` | `Product/ARCHITECTURE.md` ingest flow |
| Gen7 extraction (`guide_json` -> `clinical_logic.json`) | Current | `Product/backend/gen7/`, `Product/backend/rlm_runner.py` | Reference runs in `Product/backend/output/` |
| Deterministic converters (DMN/XLSForm/Mermaid/CSV) | Current | `Product/backend/converters/` | Generated artifacts in output folders |
| Backend+frontend runtime app | Current | `Product/backend/`, `Product/frontend/` | `Product/ARCHITECTURE.md` |
| Core automated tests | Current | `Product/backend/tests/`, `compiler/tests/` | WS0 baseline verifier and manifest |
| Cross-check harnesses | Current | `Testing/` | Gigi/Angelina/Aaron toolchains |
| Canonical Clinical IR compiler and bounded CHT lowering | Current | `compiler/` | `compiler/tests/`; exact target-runtime evidence remains external |

---

## In progress

| Capability | Status | Why it matters | Primary refs |
|---|---|---|---|
| WS1 minimum registry and target contracts | Implemented; E1 isolated evidence | Gives the WS2 tracer a content-addressed, fail-closed capability boundary without adding approval machinery | `compiler/contracts/*registry*.schema.json`, `compiler/contracts/target-profile.schema.json`, `compiler/src/chw_navigator/registry_set.py` |
| WS2 early CHT tracer | Implemented; E2 only, not deployment-ready | Proves one hand-written IR can resolve a capability and produce a deterministic CHT form/task bundle while preserving non-pass evidence | `compiler/examples/tracer/`, `compiler/src/chw_navigator/tracer.py`, `compiler/docs/work-log.md` |
| WS3 governed registry release | Implemented mechanics; E1 only, human approval not supplied | Separates executable contracts, concept/governance metadata, human attestations, and activation while binding every layer to exact digests | `compiler/contracts/registry-set-v2.schema.json`, `compiler/src/chw_navigator/registry_governance.py`, `compiler/tests/test_registry_governance.py` |
| WS4 Prompt B candidate-needs evaluation | Implemented; E2 recorded evidence, live model `not_run` | Tests whether source-grounded candidate authoring adds value without exposing registry IDs, implementations, approvals, or answer annotations | `Product/backend/operational/capability_scan.py`, `Product/backend/tests/prompt_b_fixtures/`, `compiler/docs/work-log.md` |
| WS5 canonical bridge and exact resolution | Implemented bounded tracer; E1-E2 only | Binds the exact registry-blind candidate to a reviewed semantic contract, converts the supported Product slice, and resolves only by exact governed semantics | `compiler/src/chw_navigator/canonical_bridge.py`, `compiler/examples/ws5/`, `compiler/docs/ws5-canonical-bridge.md` |
| Stable equivalence workflow vs medical reference DMNs | In progress | Real-world deployment confidence requires repeatable comparison criteria | `workflow.md`, `Testing/`, `Medical/` |
| Determinism and semantic diff checks | In progress | Distinguish harmless reorderings from behavioral drift | `Product/ARCHITECTURE.md` open issues |
| Pipeline docs harmonization (spec vs shipped) | In progress | Reduce confusion between long-horizon pipeline and Gen7 shipped path | `Product/PIPELINE.md`, `workflow.md` |

---

## Planned

| Capability | Status | Notes |
|---|---|---|
| Formal artifact contracts and owners | Planned | Introduced in `ARTIFACTS.md`; operationalize in CI over time |
| Quality gate matrix by risk type | Planned | Introduced in `QUALITY_AND_VERIFICATION.md`; link to concrete checks per release |
| Deployment integration conformance checklist | Planned | Introduced in `PLATFORM_INTEGRATION.md` |
| Contributor "single command" run experience | Planned | Captured in `RUNBOOK.md` as baseline manual runbook |

---

## Deprecated / out of scope

- `old/` is legacy and not part of current architecture.

