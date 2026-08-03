# Operational companion layer: Prompts 8–10

## Purpose

`backend.operational` is the versioned companion to Gen 8 clinical output. It
keeps the existing `clinical_logic.json` contract unchanged: clinical source
extraction, predicates, Boolean decision tables, treatment/referral intent,
and provenance remain clinical artifacts. The companion package holds only
operational intent and never sends a message or writes to a deployment system.

## Boundary

```text
source-grounded clinical pipeline
  -> clinical_logic.json (existing and authoritative for clinical logic)
  -> capability candidates (non-authoritative)
  -> exact registry resolution (deterministic)
  -> operational package (planned only)
  -> topology validation and abstract relation resolution
  -> later CHT / FHIR / external-effect adapters
```

The capability scan may propose needs from quoted source material. It cannot
choose a registry entry. A candidate proceeds only when exactly one active,
approved entry agrees on family, operation, resource, input and output types,
and backend. Missing, ambiguous, inactive, incompatible, or unreviewed needs
block compilation.

Pass a reviewed sidecar to `backend.gen8.pipeline.run` as
`operational_requirements` together with an exact `registry_snapshot`. The
pipeline then emits checksummed `operational_requirements.json`,
`registry_snapshot.json`, `capability_candidates.json`,
`registry_resolution.json`, `lifecycle_definitions.json`,
`operational_version_lock.json`, and `operational_package.json` beside, but independently from,
`clinical_logic.json`. Supplying requirements without the snapshot is an
error; supplying neither retains the established clinical-only behavior.

The public contract shapes live in `backend/operational/schemas/`. The
version lock binds the exact finalized `clinical_logic.json` digest, reviewed
registry snapshot, every resolved capability version, and every lifecycle
definition/predicate/DMN version. A compiler must read the lock rather than
infer versions from mutable deployment configuration.

## Implemented Prompt 8 controls

- Event-sourced episode projection with deterministic causal order.
- Idempotence for identical duplicates and quarantine for conflicting event
  variants, foreign episodes, stale clinical versions, and post-terminal
  events.
- Recovery only from a clinical event with a passing guard evaluated against
  the lifecycle definition's pinned predicate and DMN versions, the exact
  declared guard ID, and an offset-aware timestamp that does not postdate the
  event record.
- Timers, task expiry, silence, and absent synchronization cannot establish
  recovery.
- Malformed events and causal-sequence collisions are quarantined as evidence;
  they cannot change state or make unrelated valid events unreplayable.
- Validation that all states are reachable and every nonterminal state has a
  path to a terminal endpoint.

## Implemented Prompt 9 topology core

Topology is separately versioned deployment configuration, never a property
of a clinical artifact. A reviewed clinical topology need names only one of
the canonical relations: `contact.responsible-area`,
`patient.assigned-chw`, `patient.supervising-entity`, or
`referral.eligible-facilities`. It must name its required cardinality,
technical registry binding, subject class, and source quotation/page; it may
not carry a facility, person, platform, or deployment identifier.

When those typed requirements are present, pass `topology_package` to
`backend.gen8.pipeline.run`. The pipeline validates it before use and writes
checksummed `topology_requirements.json`, `topology_package.json`,
`topology_validation.json`, and `topology_lock.json`. It rejects a topology
package without a reviewed relation need and rejects a relation need without
an exact package. The topology lock binds the entire reviewed package content,
schema, access policy, and capability vocabulary rather than relying on a
mutable package label or version alone.

The first implementation increment validates effective-dated placement trees,
exclusive responsibility, approved assignment and coverage, facility
capability vocabulary, default-deny role/place access, and supported relation
rules. It resolves current or historical relations by the supplied effective
time; it returns `ambiguous` or `unassigned` rather than selecting an array
order or guessing a facility. Access simulation uses only replicated external
IDs and can test persona isolation. It does not contact CHT, FHIR, identity,
replication, facility, or device systems, and it does not create deployment
resources.

## Prompt 10 seam

External effects are planning-only requests that require a source quotation,
abstract recipient relation, template, adapter, and policy version. Direct
phone numbers, addresses, URLs, credentials, and delivery claims are
rejected.

`planned` and `queued` are the only compile-time external-effect states. A
future governed runtime must record provider acceptance, network dispatch,
device delivery, and human acknowledgment as separate append-only evidence.

## Root cause and guardrail

The previous workspace was an uninitialized Git folder containing an older
untracked compiler copy, while the reviewed handoff targeted the repository's
current `Product/backend/gen8` pipeline. Integrating into that folder would
have made review, regression comparison, and provenance claims unreliable.

Guardrail: all operational integration starts from a clean checkout of the
approved baseline SHA, records that SHA in the run manifest, and keeps
clinical artifacts and operational packages as separately checksummed outputs.
Before selecting that baseline, inventory every remote branch and compare each
one with the default branch. The default branch alone is not evidence that it
contains the latest intended work.

At the time this layer was first committed, `codex/recover-best-version` was
30 commits ahead of `main` and one commit behind it. The operational-layer
commit therefore requires an explicit rebase or port onto the selected
baseline before review or release; no claim is made that `main` was the most
complete branch.

The reviewed Prompt 8 archive was verified against all 855 entries in its
internal `SHA256SUMS.txt`; no digest mismatches were found.

## Handoff reading order guardrail

The first integration pass began with technical implementation files instead
of the handoff's prescribed entry documents. That risks treating a conditional
review package as a source-code transplant and missing its claims boundary.

Guardrail: before modifying a reviewed phase, read its package `README.md`,
`CODEX_MASTER_HANDOFF.md`, pipeline-integration prompt, phase prompt, report,
and red-team disposition in that order. Record the resulting implementation
boundary before adding code. Prompt 9 began only after the Prompt 8 version
lock and lifecycle guard evidence controls were present. Its reviewed archive
was checked against all 950 entries in its internal `SHA256SUMS.txt`; no
digest mismatches were found.

## Upstream handoff verification caveat

On Windows, the upstream `npm run prompt8:check` does not currently complete:
its `clean` script invokes POSIX `rm -rf`, and its toolchain fixture launches
`npm` without the Windows `.cmd` shim. The direct TypeScript compilation and
the 25 non-fixture Prompt 8 safety/lifecycle tests completed successfully in a
temporary copy; the four fixture checks could not start. This is not a passing
full release gate. Before adopting the TypeScript package directly, upstream
must make clean-up platform-neutral and invoke `npm.cmd` on Windows (or use
the Node executable path). The project-local Python companion is independent
of that defect and has its own regression tests.
