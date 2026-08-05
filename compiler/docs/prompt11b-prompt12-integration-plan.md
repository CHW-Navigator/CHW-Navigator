# Prompt 12A, 12B, 13, and 14 integration preparation

## Status

Integration is in progress on `codex/integrate-prompt12-preparation` from commit
`f9d29ab057369a9c1f07c6ce5b912aec3975312d`. This document does not claim that
all Prompt 12A-14 behavior has been integrated into the authoritative Python
compiler. Prompt 12A applicability, Prompt 12B core/CHT lowering, Prompt 13 person
registration, and Prompt 14 mutable-conflict contracts are now implemented. Live
field registration and synchronization remain external because this repository has
no target runtime adapters for those operations.

The reviewed source is `@chw-navigator/prompt14-reviewed-handoff` version 1.8.0.
Its critical inputs are pinned in
[`../integration/prompt12-source-lock.json`](../integration/prompt12-source-lock.json).
Verify that lock from the compiler directory with:

```powershell
..\.venv\Scripts\python.exe scripts\verify_prompt12_source_lock.py
```

The reviewed TypeScript handoff is an external integration input and is not shipped
as a second compiler inside this repository. The normal test runs the real lock when
that workspace is attached and reports a transparent skip in a standalone clone;
the dedicated command remains a required local integration/merge gate.

## Root cause and integration rule

The reviewed handoff is a TypeScript package assembled around package-level CHT,
identity, and mutable-conflict contracts. The target repository already has a Python
compiler, a Python CHT adapter planning layer, and a separate Product operational
package. Copying the handoff wholesale would create a second compiler and divergent
sources of truth for all three concerns.

Integration will therefore preserve the reviewed contracts and test vectors while
translating their implementation into the target architecture. Generated `dist/`,
example bundles, reports, and `node_modules/` are evidence or reproducible outputs;
they are not production source to transplant.

The generalized guardrail is a source lock plus a file-level destination map. A
later implementation may not silently substitute a newer handoff file or bypass a
missing prerequisite phase.

## Dependency order

1. **Preserve Prompt 11A/11B prerequisites.** Truthful conformance, requirement
   traceability, degraded operation, and manual fallback remain prerequisites; their
   package evidence is not target-repository execution evidence.
2. **Prompt 12A — dead declaration removal.** Confirm whether the target has the
   analogous dead checksum, remove only observed dead declarations, and add a normal
   check that detects reintroduction. Retain enforced implementation digests.
3. **Prompt 12B — special-function lowering.** Add the shared clinical vocabulary,
   diagnostic coverage gate, special-function registry, versioned CHT lowering,
   extension-library integration, and isolated official harness.
4. **Prompt 13 — person identity boundary.** Add a platform-neutral `Create × Person`
   resolution seam before wiring field registration. Keep automatic merge
   unreachable and production matching claims external.
5. **Prompt 14 — mutable conflict policy.** Add registered field policies and a pure
   assertion-preserving resolver before backend-specific conflict integration.

Each slice must pass its own tests before the next slice begins. No phase may be
merged by treating TypeScript-package evidence as target-repository execution.

## Source-to-target map

| Reviewed concern | Target destination | Preparation decision |
| --- | --- | --- |
| Truthful conformance and divergence records | `compiler/src/chw_navigator/equivalence.py`, `quality_checks.py`, new registry/schema files | Extend existing bounded reports; do not add a parallel reporter. |
| Manual fallback and operational events | `Product/backend/operational/` plus compiler CHT lowering | Operational contract lives with existing Prompt 8–10 companions; compiler consumes typed intent. |
| FHIR fallback lowering | No current target backend | Explicitly defer or add a separately reviewed FHIR backend; never mark it integrated by documentation alone. |
| Shared clinical vocabulary | `compiler/src/chw_navigator/clinical_vocabulary.py` | One versioned module must serve registry validation, CHT lowering, conformance preparation, and future backends. |
| Diagnostic declarations and dead-code guard | `compiler/src/chw_navigator/diagnostics.py` and `compiler/tests/test_diagnostic_code_coverage.py` | The normal Python test command must prove every declared code is emitted by source and asserted by a test. |
| Dead `implementationChecksum` contract | Target schemas/models only if the same field exists | Search first; remove an observed dead field, preserve enforced special-function digests, and add a repository reintroduction guard. |
| Special-function registry and status model | New `compiler/src/chw_navigator/special_functions.py` plus versioned JSON registry/reference files | Preserve the closed eight-status set, digests, purity rules, and technical-only boundary. |
| WFA lowering | Existing `compiler/src/chw_navigator/cht_backend.py` plus a focused special-function lowering module | Emit native `z-score()` only and always report unverified deployment-owned chart data; generate no WFA JavaScript. |
| Gestational-age lowering | Compiler special-function module and generated `extension-libs/gestational-age-from-lmp.js` | Preserve dependency-free `{t, v}` CHT envelopes, explicit dates, pinned versions, and one-call hidden-form binding. |
| CHT profiles | Versioned profiles for exactly 4.22.0 and 5.2.0 | Keep XForm syntax explicit per target even where reviewed output is byte-identical. Reject unreviewed versions. |
| Non-clobbering integration and rollback | New compiler integration planner, feeding existing bundle/change-control evidence | Refuse divergent unmanaged files; replace only previously managed exact hashes; include extension libraries in rollback state. |
| Official CHT harness | New isolated `Testing/official-cht-harness/` fixture | Keep pinned Node dependencies outside Python runtime dependencies and preserve the external-limit report. |
| Person identity boundary | New compiler-neutral identity contract plus Product integration seam | Port authorization-before-comparison, minimal disclosure, offline scope, deliberate-new provenance, explicit outcomes, and the no-merge rule; do not port a production matcher claim. |
| Mutable conflict policy | New compiler-neutral correction-event and policy module, consumed by Product/backend adapters | Preserve all assertions, separate projection from resolution, reject device time as authority, and label CHT/FHIR translations as fixtures until live tests exist. |

## Planned implementation slices

### Completed slice: Prompt 12A applicability and Prompt 12B core/CHT lowering

- Confirmed that the target has no `implementationChecksum` or analogous
  unenforced checksum to delete; added a source/contract reintroduction test rather
  than inventing a replacement field.
- Added one versioned clinical-vocabulary module and adversarial renamed/nested/FHIR
  tests.
- Added a central diagnostic namespace for the new integration and a normal-suite
  gate proving that each declaration is emitted by source and asserted by a test.
- Added enforced implementation/vector digests and the closed eight-status
  gestational-age contract.
- Integrated reviewed 4.22.0 and 5.2.0 special-function lowering into the existing
  Python CHT plan/writer, including non-clobbering output.
- Regenerated Python-owned artifacts into an external temporary project and passed
  both profiles through official `cht-conf` archive packaging and the real
  `cht:extension-lib` XPath implementation in the pinned CHT 4.11 browser harness.

### Completed follow-on: Clinical IR task lowering to the reviewed CHT task contract

- Added a versioned, fail-closed deployment binding for CHT task types.
- The Python compiler now emits the form-side task-intent fields and the `tasks.js`
  rules that read those exact fields in one bundle operation.
- Rule names, event IDs, duplicate-intent suppression, resolution windows, and the
  module export shape follow the reviewed TypeScript implementation.
- A bridge regression executes the generated module and passes it through the
  reviewed TypeScript AST composer, proving that unrelated destination task rules
  can still be preserved.
- `read_history` remains plan-only without a registry. When supplied a versioned
  local-data registry, the Python compiler lowers its legacy spelling through the
  same reviewed form-input adapters as `read_local_data`.

### Completed slice: Prompt 13 person identity

- Added the four-outcome `Create x Person` service before any future field
  registration seam.
- Added versioned provider configuration, authorization-before-comparison, minimal
  candidate disclosure, offline-scope propagation, and deterministic fixture
  matching.
- Required complete, internally consistent provenance for deliberate-new creation
  and kept automatic merge unreachable.
- Recorded the evidence boundary: this is not a validated master patient index or
  live access-control implementation.

### Completed slice: Prompt 14 mutable conflicts

- Added a versioned ten-field person/administrative policy registry and canonical
  correction events.
- Added a pure, input-order-independent resolver that preserves assertions,
  separates projection from resolution, and rejects device time as authority.
- Added deterministic handling for duplicate delivery, divergent event IDs,
  supersession chains, unqueued review obligations, and local CHT/FHIR fixtures.
- Confirmed that the target has no live person-registration/synchronization adapter;
  no invented Product wiring or live-backend claim was added.

### Slice A: target-repo claims audit

- Enumerate conformance/equivalence claims in compiler and Product reports.
- Port only the Prompt 11A contracts that close an observed target-repo gap.
- Add tests for unsupported claims and read-only golden behavior.
- Record deliberate divergences from the TypeScript handoff.

### Slice B: Prompt 11B operational contract

- Add versioned fallback instruction and event registries.
- Validate terminal paths, retry bounds, acknowledgment, episode disposition, and
  topology requirements.
- Lower CHT fallback events without deployment identities or embedded English
  instructions.
- Keep FHIR status explicit as `not_implemented` until a target backend exists.

### Slice C: Prompt 12A guard and Prompt 12B core/CHT lowering

- Search the target for checksum-shaped declarations with no enforcing consumer.
- Add the dead-contract reintroduction guard without inventing a replacement field.
- Port the versioned clinical-vocabulary API and its renaming/structure tests.
- Introduce a central diagnostic declaration module and mechanical coverage test.
- Port special-function registry validation and pinned vectors.
- Extend CHT generation for native WFA and gestational-age extension lowering.
- Add closed status-branch, envelope, version, provenance, and clinical-safety tests.

### Slice D: integration and external evidence

- Add non-clobbering extension-library planning and rollback tests.
- Generate six deterministic CHT profile/workflow fixtures.
- Run the isolated official harness and real archived extension-library gate.
- Retain target-runtime, live-upload, chart-equivalence, and offline-device gates as
  external until executed.

### Completed Slice E: Prompt 13 person identity

- Inventory the target's current select/register-person paths and identifiers.
- Add the four-outcome registration boundary and versioned provider configuration.
- Port deterministic adversarial fixtures, authorization filtering, minimal
  disclosure, offline-scope propagation, confirmed-new provenance, and no-merge
  enforcement.
- Keep master-patient-index accuracy and live access enforcement explicitly external.

### Completed Slice F: Prompt 14 mutable conflicts

- Inventory target-owned mutable person/administrative fields and assign one policy
  to each; exclude clinical evidence from ordinary mutation.
- Port the canonical correction event and pure input-order-independent resolver.
- Add target adapter fixtures for CHT losing revisions and any supported optimistic
  locking; leave absent FHIR/live-server paths deferred.
- Expose unresolved conflicts and unqueued review obligations without inventing a
  supervisor service.

## Acceptance gates

Before an integration commit is proposed:

- the source-lock hashes must match;
- the 93-test compiler baseline and 41-test focused operational baseline must remain
  green, with new tests added rather than replacing those baselines;
- all declared diagnostic codes must have a source emission and explicit test
  assertion;
- both reviewed CHT profiles must generate deterministic artifacts;
- all six browser harness bundles and both archived extension attachments must pass;
- the identity boundary must fail closed on missing provider, authorization,
  provenance, offline scope, and merge attempts;
- every registered mutable field must have one policy, and conflict resolution must
  preserve assertions and be invariant to event input order;
- no runtime dependency may be added solely for the isolated Node harness;
- the target repository must remain clean of generated scratch evidence;
- documentation must distinguish local, harness, target-runtime, live-upload, and
  offline evidence.

## Known preparation findings

- The root `.venv` initially had a broken `pip` and lacked the compiler's declared
  dependencies. It was repaired and the compiler package was installed; repository
  files were not changed by that environment repair.
- Documentation examples sometimes imply a compiler-local `.venv`, while this
  checkout uses the repository-root `.venv`. Integration should standardize one
  command without committing an environment.
- The pinned harness tree is test-only but has known legacy advisories. CI must
  either isolate and accept that risk explicitly or upgrade the gate without
  weakening behavioral coverage.
- The official harness runs `cht:extension-lib()` through its real bundled CHT Core
  4.11 XPath module after installing officially archived bytes. It still lacks the
  deployment-owned native `z-score()` chart and is not exact CHT 4.22.0 or 5.2.0.
  Exact target-runtime gates remain necessary before deployment.
- Prompt 13 evidence is a deterministic reference provider, not a validated master
  patient index or production duplicate-prevention claim.
- Prompt 14 evidence is a pure local resolver plus backend fixtures, not live
  CouchDB/FHIR synchronization or a staffed supervisor-review queue.

## Current baseline evidence

- Compiler: the 93-test pre-preparation baseline remains green; 119 tests including
  the source-lock, vocabulary, diagnostics, special functions, person identity,
  mutable conflicts, CommonJS, and non-clobbering guards passed on 2026-08-04.
- Prompt 8–10 operational focus: 41 `unittest` tests passed on 2026-08-04.
- Reviewed source root check passed, including 93 diagnostic codes and core coverage
  of 95.08% lines, 87.13% branches, and 95.67% functions.
- Reviewed source cross-phase audit passed for 447 protected Prompt 12 files, 15
  authorized later migrations, and 27 additions.
- Reviewed source gate: six harness bundles passed; two extension-library archives
  matched and executed; two generated XForms executed the real CHT 4.11
  `cht:extension-lib` XPath function; status remains `pass_with_external_limits`.
- Authoritative Python integration gate: fresh 4.22.0 and 5.2.0 compiler output
  passed eight browser assertions, including form fill, submit, and technical report
  field checks through the real extension XPath module.
