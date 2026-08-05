# CHW Navigator Codex work specifications

## How to use this document

Hand Codex `WS-COMMON` plus exactly one work specification at a time. Do not
hand it more than one WS. Each WS has a hard stop. The next WS does not begin
until the prior WS exit criteria are met and a human has cleared its
`[HUMAN INPUT]` items.

WS3 through WS9 are intentionally not specified yet. WS2 exists to discover
whether the WS1 contracts survive contact with real `tasks.js` composition and
a real form runner. Governance and generalization must be informed by that
result.

The intended order is:

1. WS0: establish the executable baseline and record human decisions.
2. WS1: define only the minimum contracts needed by the tracer.
3. WS2: run the early CHT tracer bullet.
4. Specify WS3 through WS9 from the tracer findings.

Prompt B is an optional authoring input, not a dependency of the deterministic
pipeline. Its later failure must be able to descope AI-assisted candidate
generation without blocking human-authored capability needs.

## WS-COMMON

Prepend this section to every WS handed to Codex.

### Task labels

Every task, test, and artifact carries exactly one label.

| Label | Meaning |
| --- | --- |
| `[CODEX]` | Code, schemas, deterministic fixtures, diagnostics, automated tests, and documentation of what the code does |
| `[HUMAN INPUT]` | Policy decisions, clinical review, named owners, approvals, risk acceptance, and choice of pilot workflow |
| `[EXTERNAL EVIDENCE]` | Exact CHT runtime, real handsets, translations, accessibility, battery and memory, provider behavior, and pilot results |

Codex performs `[CODEX]` work only.

For `[HUMAN INPUT]`, Codex may create an empty template with required fields.
It must not populate a name, role, approval, review date, clinical judgment,
risk acceptance, jurisdiction, or deployment fact. An invented record is worse
than an absent record.

For `[EXTERNAL EVIDENCE]`, Codex may create a runner and manifest shape. It
must not fabricate a result.

### Result vocabulary

Every check reports exactly one of:

- `pass`: executed and succeeded;
- `fail`: executed and failed;
- `skipped`: deliberately not executed, with a non-empty reason;
- `not_run`: could not execute because a tool, environment, or hardware was unavailable;
- `not_supplied`: a required `[HUMAN INPUT]` artifact does not exist;
- `not_comparable`: a differential comparison has no defined semantics for the case.

`skipped`, `not_run`, `not_supplied`, and `not_comparable` never aggregate into
a pass, never render as green, and never satisfy a mandatory exit criterion.
An overall pass containing any such mandatory result is a defect.

Do not write "where available" or "if the environment supports it" in an
acceptance criterion. Specify which status is recorded when a prerequisite is
absent and the resulting evidence ceiling.

### Evidence ladder

| Level | Meaning |
| --- | --- |
| E0 | Schema, lint, and static contract validity |
| E1 | Deterministic local unit and property tests |
| E2 | Generated-artifact, golden, differential, and mutation tests |
| E3 | Official tool or isolated official harness |
| E4 | Exact target-version sandbox |
| E5 | Representative offline/sync, server, or provider behavior |
| E6 | Clinical, governance, security, and deployment approval |

Every test and report declares the level it earns. A report's overall level is
the minimum across mandatory checks, not the maximum reached by one check.
Producing well-formed JSON earns E0 and nothing more. An exact target-version
sandbox result is E4; it must never be labeled E2.

### Standing prohibitions

- Never weaken or delete an existing test to reach green. If a test changes,
  record why and preserve or explicitly supersede the old assertion.
- Never modify the pinned TypeScript workspace. Run it from a disposable copy
  when its build modifies generated files. It is a read-only differential
  oracle, not a production dependency.
- Never invent reference data, clinical thresholds, provider endpoints,
  credentials, people, facilities, or approval records.
- Never resolve a specified ambiguity by choosing. Report the exact ambiguity
  and stop at its gate.
- Never introduce a declared-but-unemitted diagnostic. Every diagnostic is
  emitted by source and asserted by a test in the same change.
- Never commit environment-specific evidence containing user paths, hostnames,
  or timestamps. Commit schemas and deterministic summaries; git-ignore run
  manifests.
- Never count evidence under `generated/prompt12-*` as current-tree execution
  evidence.
- Never silently approximate an unsupported subject scope, local-data query,
  clinical function, target feature, or external effect.

### Diagnostics

Python compiler diagnostics use `CHWN-` with stable sub-namespaces:

- `CHWN-REG-*`: registry and registry set;
- `CHWN-RES-*`: capability resolution;
- `CHWN-IR-*`: canonical IR;
- `CHWN-CHT-*`: CHT lowering and composition;
- `CHWN-SCOPE-*`: subject-scope violations;
- `CHWN-EVID-*`: evidence and manifest integrity.

Each code has one meaning, one message template, and at least one test asserting
its emission.

### Work log

Every completed WS appends this structure to `compiler/docs/work-log.md`:

```text
## WS<n> - <title> - <ISO date>

Delivered: <what now exists>
Deviations: <what differs from the WS and why>
Defects found: <what was discovered, including in prior work>
Root cause: <why each defect was possible>
Generalized guardrail: <mechanical check added>
Status ledger: pass / fail / skipped / not_run / not_supplied / not_comparable
Evidence level earned: E<n>, and why it is not higher
Blocked on: <HUMAN INPUT and EXTERNAL EVIDENCE>
```

A generalized guardrail is a test, schema constraint, or CI check, not an
intention. The future `verify_repository_baseline.py` must assert that the
current completed WS has a non-empty entry.

### Repository mechanics

- All committed paths are repository-relative.
- Do not hardcode user-specific paths in code, tests, or documentation.
- Every documented command runs from the selected repository root regardless
  of the caller's initial working directory.
- Preserve unrelated user changes.
- Use the project's existing Python formatting conventions.
- Each WS starts by recording the branch, commit, and clean/dirty state.

## WS0 - Establish the executable baseline

### Objective

Remove repository ambiguity and establish an honest, reproducible description
of what currently exists before contract changes.

WS0 contains a mandatory human gate. Codex performs Part A, creates an empty
decision template, and stops. Part B starts only after a human supplies every
decision.

### Part A - Discovery `[CODEX]`

Produce:

- `compiler/reports/ws0-discovery.md`;
- `compiler/reports/ws0-discovery.json`;
- `compiler/docs/ws0-decisions-template.md` with all values unset.

Part A may add those reports and this work-spec document, but must not repair
product or compiler source.

#### Repository state

- Record every Git root, branch, commit, and normal modified/untracked path
  relevant to the workspace.
- Under `compiler/`, list every modified and untracked path exactly.
- Classify ignored material by ignored root and exact path count. Include the
  deterministic command for enumerating every ignored path, but do not commit
  individual environment-specific cache, build, harness, or timestamped
  scratch paths.
- Identify the local-data implementation, the commit or working-tree state
  containing it, all focused tests, and their current outcomes.

#### Status-claim conflicts

- Inspect top-level status/readiness claims in the selected repository and in
  any outer workspace status file that claims to identify the active root.
- Quote each material claim with repository-relative file and line.
- Report contradictions and staleness without editing the source documents.

#### Baseline execution

Run and report separately:

1. the complete current compiler Python suite;
2. the complete current Product Python suite using its existing test environment;
3. the complete pinned TypeScript `npm test` from a disposable clean copy.

Legacy directories and independent prototype harnesses are not silently folded
into these suites. List them as excluded with their reason. Record pass, fail,
skip reason, `not_run`, warning, and evidence level for each suite. A red
baseline is a finding and must not be repaired during Part A.

#### Source-lock verification

Verify `compiler/integration/prompt12-source-lock.json` against the attached
reviewed TypeScript source. Report all mismatches. Do not update the lock in
Part A.

#### Prior-prompt status

For Prompt 11, Prompt 12, and any earlier/later prompt work found:

- distinguish Product Python work, compiler Python work, and reviewed
  TypeScript-source work;
- state what landed and what remains documentation, planning, or external;
- flag TypeScript-only work that cannot be treated as Python production;
- identify prompt-number overloading when two tracks use the same number;
- report the Product `clinical_logic` to canonical Clinical IR boundary;
- report whether Prompt B is actually invoked and whether mini-manual tests
  exercise it.

#### Skip audit

List every skip in all three executed suites with its reason and test. Flag any
condition that can make CI green while omitting a required platform or security
case.

### Human gate `[HUMAN INPUT]`

Codex stops after Part A. The human template contains these unset fields:

1. authoritative repository root;
2. disposition of each conflicting status claim: update, archive, or mark non-authoritative;
3. disposition of the committed or uncommitted local-data work: retain as an intentional compiler capability or isolate from the implementation branch;
4. prior prompts remaining in force, withdrawn, or retargeted to Python;
5. candidate Release 1 clinical workflow and subject scope.

An intended household-, service-area-, or cohort-scoped workflow is outside the
WS1/WS2 `current_contact` boundary and must be identified now.

### Part B - Record decisions `[CODEX]`

Part B begins only after every human field is populated.

Named outputs:

- `compiler/docs/adr-001-python-production-typescript-oracle.md`;
- `compiler/docs/evidence-levels.md`;
- `compiler/docs/work-log.md`;
- `compiler/scripts/verify_repository_baseline.py`;
- `compiler/tests/test_repository_baseline.py`;
- `compiler/integration/oracle-overlap-map.json`;
- `compiler/tests/test_oracle_overlap_map.py`.

Update the source lock only for a genuine Part A mismatch, with the cause
recorded.

#### ADR-001 decision

Record exactly:

- Python is the production compiler.
- The pinned TypeScript implementation is a test-only differential oracle and
  is never a production runtime dependency.
- Do not port it wholesale or invoke Node as a production subprocess/service.
- Preserve its workspace, tests, vectors, purity checks, and diagnostics
  unmodified.
- Run equivalent canonical cases through both implementations where semantics
  overlap.
- Compare normalized semantic results, not byte-identical output.
- Report unsupported comparisons as `not_comparable`, never pass.
- Retirement requires protected-vector parity, equivalent negative and
  mutation coverage, and a later explicit ADR.

Record the human decisions without adding new ones. Stop if ADR-001 would
require an uncovered human decision.

#### Oracle overlap map

The map prevents `not_comparable` from becoming an unbounded escape hatch. It
uses schema `oracle-overlap-map@1` and records, per case:

- stable case ID;
- Python entry point;
- TypeScript entry point;
- `comparable` or `not_comparable`;
- normalization rule;
- specific semantic reason for non-comparability.

Tests assert a non-empty comparable set, executable cases on both sides,
specific non-implementation reasons for `not_comparable`, and explicit
demotion records when a formerly comparable case is removed.

#### Baseline verifier

One root-independent command emits a git-ignored
`compiler/reports/baseline-manifest.json`. It:

- runs both Python suites and the TypeScript oracle suite;
- records exact result vocabulary and skip reasons;
- computes the minimum evidence level across mandatory checks;
- fails release mode for required skips, unexpected warnings, dirty source,
  or unexplained scratch output;
- performs contract-copy and source-of-truth drift checks;
- prevents archived Prompt 12 evidence from being reported as current;
- validates the current work-log entry and overlap-map invariants.

### WS0 machine acceptance

- Part A reports are internally consistent and source-lock verification ran.
- After human input, the baseline verifier runs from the selected root.
- Report counts match independent recounts of raw test output.
- No skip lacks a reason.
- No unexplained modified/untracked compiler path remains.
- Retained local-data code and tests are tracked together.
- Evidence level is the minimum across mandatory checks.
- Overlap-map and work-log checks pass.

### WS0 non-goals

- No registry design, AI prompt changes, RACI, hazard register, clinical
  approval, deployment claim, baseline repair, TypeScript rewrite, or
  TypeScript source edit.

### WS0 hard stop

Do not begin WS1 while the authoritative root, source digest, local-data fate,
prior-prompt disposition, or Release 1 candidate workflow is unset. A failing
mandatory baseline is also a hard stop until a separately authorized repair WS
returns it to the declared baseline.

Expected ceiling: E0-E1. A mandatory test failure limits the overall result to
E0 even if other suites pass E1 checks.

## WS1 - Minimum viable contracts

### Precondition

WS0 Part B is complete, human decisions are recorded, and the baseline is
reproducible without mandatory failures.

### Objective

Define only enough contract surface to compile the WS2 tracer. This is a
contract spike, not the full governance model.

### Scope bound

The capability contract has exactly these fields:

`id`, `version`, `content_digest`, `family`, `operation`, `inputs` (named,
ordered, typed, unit-bearing, cardinality-bearing), `outputs` (named, typed,
unit-bearing, with technical binding path), `status_set`, `supported_domain`,
`rounding`, `determinism`, `side_effects`, `implementation_binding`,
`evidence_status`, `supported_target_profiles`, and `subject_scope`.

Adding a field the WS2 tracer does not exercise is a specification violation.
There is no data dictionary, approval state, signature, FHIR field, channel
policy, or consent field in WS1.

### Named outputs

- `compiler/contracts/registry-set.schema.json`;
- `compiler/contracts/capability-registry.schema.json`;
- `compiler/contracts/target-profile.schema.json`;
- positive and negative fixtures under `compiler/contracts/examples/tracer/`;
- `compiler/src/chw_navigator/registry_set.py`;
- the `CHWN-` catalogue in `compiler/src/chw_navigator/diagnostics.py`;
- `compiler/tests/test_registry_set.py`;
- `compiler/tests/test_target_profile.py`;
- `compiler/tests/test_subject_scope.py`.

### Required semantics

- Registry sets are content-addressed from member digests.
- A schema-valid candidate capability cannot resolve. Schema validity never
  implies approval.
- Target profiles identify exact CHT Core, `cht-conf`, form-engine, extension
  support, and required local-data features.
- Unsupported target profiles fail resolution.
- Subject scope is an enum. Release 1 accepts `current_contact` only.
  `household`, `service_area`, and `cohort` fail with `CHWN-SCOPE-001`, which
  states that group obligations require a separate model.
- Unknown fields are rejected or deliberately preserved; never dropped.

### Machine acceptance

- Positive fixtures validate; each negative fixture emits a stable diagnostic.
- Missing unit, version, digest, subject scope, and target feature produce
  distinct codes.
- Mutating any locked source changes the registry-set digest.
- A schema-valid candidate fails resolution.
- All three disallowed group scopes emit `CHWN-SCOPE-001`.
- Every declared diagnostic is emitted and tested.

### Non-goals

No full data dictionary, approval workflow, signatures, AI-generated registry,
FHIR, messaging, or extra fields.

### Abort criterion

If the contracts cannot represent WS2 without placing Python or CHT
implementation details inside clinical IR, stop, identify the leaking field,
and revise the contracts before governance.

Evidence ceiling: E0-E1.

## WS2 - Early tracer bullet

### Precondition

WS1 is complete and its contracts represent the tracer without implementation
leakage.

### Objective

Compile one deliberately narrow hand-written case:

```text
hand-written IR -> registry resolution -> CHT form/task bundle -> local harness
```

Finding a contract defect is a successful tracer outcome. No AI or approval
machinery is involved.

### Tracer workflow

Use gestational age from last menstrual period rather than native
weight-for-age `z-score()`. Native WFA depends on a deployment-controlled chart
document whose bytes and version are not supplied or verified; pinning a
reference-data label cannot prove equivalence.

The tracer contains:

- one registered local read of the most recent `lmp_date` for
  `current_contact`;
- one gestational-age invocation;
- explicit missing and stale branches;
- one clinical endpoint;
- one single-contact follow-up task;
- no FHIR, messaging, group scope, AI, or approval machinery.

### Function specification

- ID: `technical.gestational-age.naegele`.
- Inputs: `lmp_date` and `reference_date`, both dates.
- Outputs: `technical.ga_weeks` integer,
  `technical.ga_days_remainder` integer, and `technical.edd` date.
- Rule: EDD equals LMP plus 280 days.
- Supported domain: 0 through 44 completed weeks.
- Determinism: deterministic; side effects: none.
- Reference convention: `naegele@1.0.0`.
- Required statuses: `ok`, `input_missing`, `input_invalid`,
  `outside_supported_domain`, `reference_data_unavailable`,
  `numeric_failure`, `version_mismatch`, and `execution_failure`.
- `reference_date` before LMP is `input_invalid`; more than 44 weeks is
  `outside_supported_domain`.

The function never classifies preterm, term, post-term, overdue, or any
clinical category. Follow-up timing belongs to the decision table.

Reference vectors are hand-derived calendar arithmetic and say so. Include
leap-year, month-boundary, exact-280-day, day-zero, and domain-edge cases.

### Named outputs

- `compiler/examples/tracer/tracer.ir.json`;
- `compiler/examples/tracer/registry-set.json`;
- `compiler/examples/tracer/target-profile.json`;
- `compiler/examples/tracer/existing-tasks.js` with unrelated rules;
- `compiler/scripts/run_tracer.py`;
- `compiler/tests/test_tracer_slice.py`;
- `compiler/tests/test_tracer_composition.py`;
- `compiler/integration/typescript_oracle_runner.py`;
- git-ignored `compiler/reports/tracer-evidence-manifest.json`.

### Machine acceptance

#### Build and references

- One root-level command builds from clean inputs without manual editing.
- Every IR reference resolves; unresolved references emit stable codes.
- Only referenced extensions are emitted.
- An unreferenced function is absent.

#### Generated artifacts

- The form binds the registered local read and function output to `technical.*`.
- All eight function statuses have explicit caller branches; removing one
  makes the build fail.
- Task trigger, subject, due date, and deduplication identity are deterministic.
- Due date comes from the decision table, not the function. Changing the
  clinical interval changes the due date without changing function output.

#### Composition and rollback

- Compose into `existing-tasks.js` without altering unrelated rules, proven by
  structural/byte comparison rather than inspection.
- Recomposition is idempotent.
- Managed rules are namespaced.
- A rollback artifact restores the fixture byte-for-byte.

#### Determinism

- The evidence manifest separates deterministic digests from environment data.
- Two clean builds produce byte-identical deterministic sections.

#### Oracle

- Comparable overlap-map cases execute in Python and TypeScript and agree after
  normalization.
- Non-comparable cases are counted separately with reasons.
- The tracer adds at least one comparable case.

#### Harness

- The local Node/form harness records `pass`, `fail`, or `not_run`.
- If unavailable, record `not_run` and cap evidence at E2.
- Exact CHT 4.22/5.2 sandbox execution is a separate E4
  `[EXTERNAL EVIDENCE]` gate and is not fabricated by this WS.

### Non-goals

No deployment claim, arbitrary report-history search, group obligations,
native WFA, general framework, plugin system, or configuration for cases the
tracer does not exercise.

### Hard stops

- If real `tasks.js` composition fails, revise contracts before WS3.
- If clinical IR needs implementation details, stop and report.
- If only E2/E3 exists, deployment readiness remains false.
- If Release 1 requires group scope, descope the pilot or design a separate
  group-obligation model before continuing.

Evidence: E2, or E3 only when the official local harness actually executes.

## After WS2

Write WS3 through WS9 only after reading the WS2 work log and tracer findings:

- WS3: contract hardening and approval mechanics;
- WS4: Prompt B and mini-manual tests;
- WS5: canonical IR bridge and deterministic resolver;
- WS6: CHT productionization, including stale topology and queued-offline rules;
- WS7: FHIR mappings;
- WS8: messaging and external effects;
- WS9: release evidence and claim ceilings.

WS4 is not a hard dependency of WS5. WS5 accepts human-authored capability
needs. Later queued operations carry `snapshot_digest`, `resolved_at`, and a
maximum age, re-resolve at execution/sync/assignment/send, and enter
`blocked_stale_topology` if no fresh topology exists.
