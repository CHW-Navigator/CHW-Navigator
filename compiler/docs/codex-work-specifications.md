# CHW Navigator Codex work specifications

## How to use this document

Hand Codex `WS-COMMON` plus exactly one work specification at a time. Do not
hand it more than one WS. Each WS has a hard stop. The next WS does not begin
until the prior WS's `[CODEX]` exit criteria are met. A `[HUMAN INPUT]` item
blocks only the production claim or later WS that explicitly names it as a
precondition; otherwise it remains `not_supplied` while independent development
continues.

WS3 through WS9 were specified only after WS2 established which contract,
composition, typing, and evidence boundaries survived the tracer. Their scope
and acceptance criteria incorporate the defects and guardrails recorded in the
WS2 work log.

The intended order is:

1. WS0: establish the executable baseline and record human decisions.
2. WS1: define only the minimum contracts needed by the tracer.
3. WS2: run the early CHT tracer bullet.
4. WS3 through WS9: harden, connect, generalize, and release-gate the proven
   slice without conflating AI output, schema validity, approval, or deployment
   evidence.

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

## WS3 - Governed registry release

### Precondition

WS2 is complete at E2. The tracer work log is present and the stacked WS2
branch is clean. No E4-E6 claim is inferred from that result.

### Objective

Harden the contract shapes proven by WS2 and add immutable, digest-bound
approval mechanics without allowing AI output or schema validity to activate a
registry. This WS governs registries; it does not generate their policy
content.

### WS2 findings that constrain this work

- Preserve the implementation-independent `invoke_capability` action.
- Preserve explicit XForm bind types and decision-table-owned task timing.
- Keep the TypeScript workspace read-only and test-only.
- Do not add group scope, queued topology, FHIR, or messaging fields here.
- Do not replace the working v1 tracer contracts in place. Version the governed
  contract so the WS2 fixture remains executable.

### Required changes `[CODEX]`

Create:

- `compiler/contracts/data-dictionary.schema.json`;
- `compiler/contracts/capability-governance.schema.json`;
- `compiler/contracts/approval-attestation.schema.json`;
- `compiler/contracts/registry-release.schema.json`;
- `compiler/contracts/registry-set-v2.schema.json`;
- `compiler/contracts/templates/registry-approval.md` with every human field
  visibly unset;
- `compiler/src/chw_navigator/registry_governance.py`;
- `compiler/tests/test_data_dictionary.py`;
- `compiler/tests/test_registry_governance.py`;
- positive and negative synthetic fixtures under
  `compiler/contracts/examples/governance/`.

The data dictionary concept contract includes concept ID and version, content
digest, definition, identifiers/codings, ordered value set when applicable,
type, unit, cardinality, requiredness semantics, data owner role, retention
policy reference, consent policy reference, access-policy reference,
interoperability mappings, provenance, and lifecycle state. Policy fields are
references, never invented policy text.

Capability governance is a sidecar bound to an exact capability content digest.
It records evidence/source references, owner roles, invocation policy reference,
review requirements, and lifecycle state without changing the executable WS1
capability surface.

`registry-set-v2` is content-addressed from the digests of its named data
dictionary, capability registry, capability-governance catalogue, and target
profile members. V1 remains supported for the WS2 tracer but cannot be activated
as a governed release.

An approval attestation binds exactly one registry-set digest, decision,
required role, attestation digest, and detached-signature metadata. The three
required roles are `clinical`, `data_governance`, and `technical`. Names,
organizations, timestamps, keys, and signatures are `[HUMAN INPUT]`; fixtures
use identifiers explicitly prefixed `synthetic-test-`.

Registry activation is fail-closed. It requires three distinct approved
attestations, exact digest equality, a configured signature-verifier result for
each attestation, and no expired or superseded input. Absence of findings,
schema validity, `candidate`, `reviewed`, or WS2 `tracer_enabled` status never
counts as approval. The WS1 candidate capability contract cannot contain
attestations, activation state, or approval decisions; WS4 must preserve that
boundary in its candidate-needs schema.

Add stable `CHWN-REG-*` diagnostics for wrong digest, missing role, duplicate
role, unverified signature, non-approved decision, stale/superseded input, and
attempted v1 activation. Every code is emitted and directly asserted.

### Human inputs `[HUMAN INPUT]`

The approval template requests but does not populate the registry release
owner, three approvers, their organizations and signing-key IDs, applicable
jurisdiction, effective interval, retention/consent/access policy references,
and approval decisions. Missing fields remain `not_supplied`.

### Machine acceptance

- Mutating any v2 member changes both its member digest and the registry-set
  digest.
- Copying valid attestations to a different set fails activation.
- Missing, duplicate, rejected, unverified, expired, or superseded attestations
  each fail with their stable diagnostic.
- Three synthetic, verified, digest-matching approvals activate only the exact
  synthetic fixture used by the test.
- Candidate output containing any approval or activation field is rejected.
- The WS2 v1 tracer still builds and its focused tests remain unchanged.
- Schema/runtime field parity and unknown-field rejection are tested.
- The work log states E0-E1 only; no human approval is claimed.

### Descope and abort

If a required policy value is unavailable, leave it `not_supplied`; do not
invent it. If activation cannot be kept separate from candidate generation,
abort WS3 and retain the WS2 non-activatable registry. If signature verification
needs an unavailable production trust service, implement the verifier interface
and synthetic tests, record production verification as `not_run`, and keep
activation unavailable outside tests.

### Non-goals

No AI registry generation, Prompt B, canonical Product bridge, CHT
generalization, FHIR, messaging, real approvers, production keys, or deployment
claim.

Evidence: E0-E1. Human approval remains E6 `not_supplied`.

## WS4 - Prompt B candidate-needs evaluation

### Precondition

WS3 schemas define candidate-only output that cannot carry approval. WS4 may
proceed independently of WS5, but it cannot activate a registry.

### Objective

Turn the existing unused Prompt B text into a tested candidate-need authoring
stage. Determine whether mini-manual tests add value by measuring grounding,
omission, hallucination, and boundary behavior—not by checking that a prompt
string exists.

### Required changes `[CODEX]`

Create a candidate-needs schema, prompt builder, strict parser, deterministic
recorded-output evaluator, and an explicit invocation path from a supplied
manual. Prompt B receives manual text and the candidate-needs schema only. It
must not receive approved registry IDs, implementation bindings, Python names,
CHT extension names, or an answer oracle.

Each candidate need contains a local candidate ID, quoted source span and
location, problem statement, ordered inputs and outputs with type/unit, required
statuses or failure behavior, subject scope, uncertainty, and provenance. It
does not contain a resolved capability ID.

Create synthetic mini-manuals and expected annotations for at least:

- no capability need;
- explicit deterministic date arithmetic;
- required local-data read;
- clinical interval that must remain decision policy;
- ambiguous calculation that must be flagged rather than completed;
- unit mismatch;
- unsupported group scope;
- adversarial text instructing the model to invent or approve a function;
- a need with insufficient source grounding;
- two similar needs that must remain separate.

Add three distinct test layers:

1. prompt-construction tests asserting registry blindness and injection
   containment;
2. parser/mutation tests using recorded outputs, including extra fields,
   missing quotes, invented IDs, and malformed units;
3. an opt-in live-model evaluation runner that reports per-case precision,
   recall, grounding, unsupported-inference, and ambiguity scores as
   `pass`/`fail`/`not_run`. Live-model outputs are environment evidence and are
   git-ignored.

### Machine acceptance

- Repository search and a direct import test prove Prompt B has an invocation
  path; an unused prompt constant fails.
- Every mini-manual reaches the prompt builder and strict parser.
- Recorded positive and negative outputs execute in ordinary CI.
- No prompt or recorded request contains approved registry IDs.
- Source quotations are exact substrings with locations; invented quotations
  fail.
- A no-need manual produces an empty candidate list, not a fabricated function.
- Adversarial approval instructions do not enter the parsed output.
- Live evaluation absence is `not_run`, never pass, and cannot raise the WS
  above E2.

### Descope and abort

If live candidate quality misses the declared threshold, descope AI candidate
generation and retain the deterministic parser plus human-authored
candidate-needs input. WS5 continues with that input. Do not tune on held-out
answers or expose registry IDs to improve apparent accuracy.

### Non-goals

No approval, resolution to implementation IDs, canonical IR generation,
compiler changes beyond candidate parsing, or deployment claim.

Evidence: E1 for prompt/parser tests, E2 for recorded-output evaluation. Live
model quality is reported separately.

## WS5 - Canonical IR bridge and deterministic resolution

### Precondition

WS3 governed registry mechanics and synthetic fixtures exist. Candidate needs
may come from WS4 or human-authored files; their origin does not change resolver
semantics. Production compilation still requires a genuinely activated release,
but deterministic development may use the visibly synthetic WS3 fixture.

### Objective

Close the Product `clinical_logic` to compiler `ClinicalIRDocument` boundary and
resolve abstract capability needs against one exact governed registry release
without fuzzy or model-driven selection.

### Required changes `[CODEX]`

Create a versioned Product-to-canonical adapter contract, a loss report, a
deterministic capability-need resolver, and a root command that accepts Product
logic, the exact registry-blind candidate artifact, a separately reviewed
semantic binding, an activated registry release, and an exact target profile.
The result is canonical IR plus a resolution lock.

Prompt B's candidate cannot safely supply registry vocabulary, deployment
status names, target configuration, or Product variable IDs because those are
not present in the manual and the prompt must remain registry-blind. Require a
content-addressed reviewed binding between WS4 and resolution. It normalizes
family/operation, ordered semantic contracts, statuses, target/scope, and
variable mappings, but cannot contain a capability or implementation ID. Bind
it to the exact source-candidate digest and verify that digest at the compiler
boundary. Candidate prose and problem wording are audit evidence, never
resolver inputs.

The adapter maps all seven Product sections or emits a stable unsupported-field
diagnostic. Silent dropping, renaming, defaulting of clinical values, and
provenance loss are failures. Local-data reads map only through registered
binding IDs. Clinical decision outputs remain distinct from technical function
outputs.

Resolution uses declared semantics: family/operation, ordered input/output
types and units, status requirements, target profile, subject scope, and active
release digest. It never resolves by string similarity, registry order,
implementation name, LLM preference, or “closest” match. Zero matches is
unresolved; multiple matches is ambiguous. The resolution lock records need ID,
capability ID/version/digest, registry-set digest, target-profile digest,
resolution rule version, and deterministic rationale.

### Machine acceptance

- Round-trip fixtures prove every supported Product field is represented in
  canonical IR or in the loss report.
- Injecting an unknown Product field fails rather than disappearing.
- Reordering registry entries does not change resolution.
- Zero and multiple matches fail with distinct stable diagnostics.
- Unit, status-set, target-profile, and subject-scope mismatches fail closed.
- Candidate origin (Prompt B versus human-authored) does not change output.
- Candidate prose changes do not change resolution, while changing a reviewed
  semantic field fails closed; changing a candidate after review breaks its
  digest binding.
- The resolved tracer IR contains only capability ID and variable mappings; no
  implementation binding leaks into clinical IR.
- Two clean runs produce byte-identical canonical IR and resolution locks.
- The output compiles through the WS2 tracer path at E2.

### Descope and abort

If the Product contract cannot be converted without clinical inference, emit a
loss report and stop. The descope path is direct canonical-IR authoring; never
guess missing semantics. WS4 quality does not block WS5.

### Non-goals

No broad CHT plugin framework, FHIR, messaging, live topology, group scope, or
clinical approval.

Evidence: E1-E2.

## WS6 - CHT productionization and stale-topology safety

### Precondition

WS5 emits deterministic canonical IR and a resolution lock for the tracer. The
WS2 spike limitations are recorded.

### Objective

Replace tracer-only injection with a bounded production CHT lowering path for
approved capabilities, local reads, and single-contact tasks, while making
queued/offline topology staleness explicit and fail-closed.

### Required changes `[CODEX]`

Generalize only exercised seams: capability lowering selected from the active
registry, typed technical outputs, explicit status handling, deterministic
task-intent generation, content-aware composition, and rollback. Python remains
the production runtime; Node/TypeScript remains a test oracle and is absent from
the production dependency graph.

Every queued operation carries `snapshot_digest`, `resolved_at`,
`maximum_age_seconds`, subject identity, operation ID, and resolution lock
digest. It re-resolves at execution, sync, assignment, and any later handoff.
If no sufficiently fresh topology exists, status is
`blocked_stale_topology`; the old target is never used silently. Duplicate
delivery and permutations remain deterministic.

Create official-harness and exact-target runner shapes. Results use the common
vocabulary; unavailable `xsltproc`, CHT sandbox, server, or device becomes
`not_run` with a reason and caps evidence. Test 4.22 and 5.2 profiles separately;
syntax similarity never implies conformance equality.

### Machine acceptance

- No tracer-specific capability ID or output name remains in the general
  lowering path.
- Registry-selected lowerers emit only referenced, approved capabilities.
- All registered statuses require caller coverage.
- Existing unrelated `tasks.js` rules remain byte/structurally unchanged;
  recomposition and rollback remain exact.
- Production package/dependency inspection proves Node is not required.
- Fresh, stale, future-dated, missing, and mismatched topology snapshots have
  deterministic results.
- Queued operations re-resolve at every named boundary; stale resolution enters
  `blocked_stale_topology`.
- The official local harness reports E3 only when it actually executes.
- Exact target runtime remains E4 `[EXTERNAL EVIDENCE]`.

### Descope and abort

If Release 1 requires household, cohort, or service-area obligations, descope
the pilot or stop for a separate group-obligation design. Do not approximate a
group obligation with one contact task. If safe composition cannot be
generalized from the tracer, retain the narrow allow-list rather than emitting
unreviewed rules.

### Non-goals

No FHIR resource generation, outbound messaging, group obligations, real-device
claim, or deployment approval.

Evidence: E2-E3 locally; E4-E6 external.

## WS7 - Governed FHIR mapping

### Precondition

WS5 canonical IR and governed registry releases are stable. WS7 does not block
the CHT pilot unless FHIR is explicitly selected as its target.

### Objective

Generate deterministic FHIR R4 mappings from approved concept/capability
contracts without inventing codes, identities, profiles, or server behavior.

### Required changes `[CODEX]`

Create a content-addressed FHIR mapping registry bound to data-dictionary
concept digests, exact FHIR version/profile URLs, code systems, resource paths,
cardinality, units, subject/reference rules, provenance, and write policy.
Create mapping plans and fixtures, not a generic best-effort mapper.

Identity resolution is a precondition and remains separate from clinical
mapping. Missing or ambiguous person, encounter, practitioner, organization,
or location identities block generation. Every output carries source and
registry-release provenance. Unsupported clinical fields fail rather than
entering extensions automatically.

### Machine acceptance

- Golden resources validate against the pinned local profiles when tooling is
  available; unavailable official validation is `not_run`.
- Unknown concepts, codes, profiles, units, identities, and cardinality
  mismatches emit distinct diagnostics.
- Reordering inputs does not alter canonical resource output.
- No unregistered extension URL or identifier is emitted.
- Round-trip/differential cases state which fields are comparable and why.
- No network write occurs in unit or golden tests.

### Human and external gates

FHIR endpoint, national implementation guide, identifier systems, terminology
authority, write permissions, and mapping approval are `[HUMAN INPUT]` or
`[EXTERNAL EVIDENCE]` and remain unset unless supplied. Server conformance and
transaction behavior are E5.

### Descope and abort

If exact profiles/codes are not supplied, retain mapping templates and mark the
target `not_supplied`; do not use generic R4 resources as a proxy for national
conformance.

### Non-goals

No live server writes, messaging, consent inference, or deployment claim.

Evidence: E1-E3 locally; server behavior E5 and approval E6.

## WS8 - Governed messaging and external effects

### Precondition

WS3 approvals and WS6 stale-topology rules exist. A channel policy and provider
configuration must be supplied before any live effect can be enabled.

### Objective

Compile approved communication intent into an auditable external-effect request
that cannot send until consent, identity, policy, topology, template, and
provider gates all pass at execution time.

### Required changes `[CODEX]`

Define content-addressed channel-policy, message-template, consent-evidence, and
external-effect-request contracts for WhatsApp, SMS, and IVR. Required policy
fields include provider adapter reference, opt-in basis, subject/recipient
identity rule, permitted template and language, quiet hours/time zone, minimum
necessary content, forbidden health-information classes, audit fields,
idempotency key, opt-out handling, retention, and escalation behavior.

Compilation creates requests only. Sending is a separate adapter boundary.
Before assignment and send, re-check exact active policy/template digests,
consent, opt-out, recipient identity, quiet hours, provider configuration, and a
fresh topology snapshot. Any stale snapshot becomes `blocked_stale_topology`;
policy or consent failures become distinct blocked states. Retries preserve one
idempotency identity and never infer delivery from provider acceptance.

### Machine acceptance

- Missing consent, ambiguous recipient, opt-out, quiet hours, stale topology,
  unapproved template, forbidden content, and unavailable provider each block
  with stable diagnostics.
- Adversarial fixtures cannot insert free-form health data into restricted
  channels.
- Duplicate and reordered events produce one deterministic effect identity.
- Compiler and tests never contact a real provider.
- A provider simulator distinguishes accepted, delivered, failed, unknown, and
  `not_run`; accepted is never relabeled delivered.
- Send-time re-resolution is directly tested, including queued-offline cases.

### Human and external gates

Provider, credentials, country/channel policy, approved templates and
translations, consent wording/basis, quiet hours, forbidden-content policy,
retention, and incident escalation are `[HUMAN INPUT]`. Provider sandbox,
carrier/device behavior, accessibility, and delivery receipts are E5
`[EXTERNAL EVIDENCE]`.

### Descope and abort

If any required channel rule is unset, retain local in-app tasking and mark
messaging `not_supplied`. Do not substitute a different channel or a generic
template.

### Non-goals

No marketing messaging, free-form clinical messages, inferred consent, or live
send in CI.

Evidence: E1-E3 locally; provider/device E5; policy approval E6.

## WS9 - Release evidence and claim ceilings

### Precondition

All in-scope implementation WSs have complete work-log entries. The selected
Release 1 target and channel scope are explicit.

### Objective

Produce a release evidence system that derives the maximum permitted claim from
executed evidence and refuses deployment readiness when any mandatory result is
missing, skipped, stale, unverifiable, or outside scope.

### Required changes `[CODEX]`

Create a release-manifest schema, evidence collector, claim-policy matrix,
artifact/source-lock verifier, external-evidence import verifier, and one root
release command. Every evidence item records scope, target version, artifact
digests, execution environment, result vocabulary, evidence level, expiration
or freshness, and provenance.

The aggregate level is the minimum of mandatory in-scope gates. `skipped`,
`not_run`, `not_supplied`, and `not_comparable` are separately counted and never
green. An E2 compiler result cannot support “tested on CHT,” “offline-ready,”
“clinically approved,” or “deployment-ready.” External manifests are accepted
only when their signatures/trust verification, artifact digests, target scope,
and freshness match the release candidate.

Create empty `[HUMAN INPUT]` and `[EXTERNAL EVIDENCE]` templates for clinical,
data-governance, technical, privacy/security, target-runtime, representative
device/offline-sync, translation/accessibility, provider, operations/helpdesk,
and deployment approvals. Codex never populates them.

### Machine acceptance

- Mutation tests prove each absent, stale, wrong-target, wrong-digest,
  unverifiable, skipped, and `not_comparable` mandatory item lowers or blocks
  the claim.
- A nonempty generated bundle alone earns no readiness claim.
- Release mode fails on dirty source, untracked generated scratch, source-lock
  drift, incomplete work log, mandatory skip, or expired evidence.
- Claim text is generated from the policy matrix; hand-written stronger claims
  fail a drift check.
- A fully synthetic fixture may reach E6 only when every synthetic attestation
  is visibly marked test-only; production mode rejects synthetic identities.
- Current real repository state reports its actual ceiling and blockers.

### Abort and release decision

Any missing E4-E6 gate blocks deployment readiness. The descope path narrows the
release scope and regenerates the evidence matrix; it never waives a failed
mandatory gate silently. Risk acceptance is `[HUMAN INPUT]`, must be explicit,
and cannot convert a failed technical assertion into pass.

### Non-goals

No automatic clinical approval, risk acceptance, credential generation,
deployment, or retroactive relabeling of old evidence.

Evidence: the system itself earns E1-E2. The release claim may reach E0-E6 only
from matching executed and supplied evidence.
