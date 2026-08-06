# WS6 bounded CHT production path

WS6 replaces the WS2 tracer-only row injector and TypeScript task-composition
dependency with a bounded Python production path. It still compiles only the
synthetic vertical slice supported by WS5. It is not a general manual compiler
and is not deployment approval.

## What exists now

The `build-cht-production` command accepts canonical IR and the exact WS5
resolution lock, governed registry, activation result, target profile, local
data bindings, task bindings, runtime variable bindings, and the destination
project's existing `tasks.js`.

The build then:

1. rechecks the registry, activation, target, resolution-lock, capability,
   status, type, unit, and subject-scope boundaries;
2. selects a reviewed lowerer from the active capability's implementation
   binding rather than from a tracer capability ID;
3. derives technical output rows and types from the registered output contract;
4. lowers registered local reads and single-contact tasks;
5. composes generated rules into the existing `tasks.js` using Python;
6. preserves the original file byte-for-byte as the rollback artifact;
7. emits strict topology-snapshot and queued-operation schemas; and
8. records pass, fail, skipped, and `not_run` evidence without treating
   unavailable checks as passes.

The reviewed TypeScript package remains a differential oracle in tests. It is
not imported or invoked by the production build.

## Queued and offline work

Each queued operation carries its operation ID, subject ID, assignee role,
resolved target, topology-snapshot digest, resolution time, maximum permitted
snapshot age, resolution-lock digest, and boundary history.

The operation is resolved again at assignment, execution, synchronization, and
handoff. A missing, stale, or future-dated snapshot returns
`blocked_stale_topology`. An absent or ambiguous current assignment returns a
separate blocked result. A fresh replacement snapshot may change the resolved
assignee; the old assignee is never reused silently. Repeated delivery of the
same boundary event is byte-identical, and assignment order does not change the
result.

Only `current_contact`/single-person work is supported. Household, cohort, and
service-area obligations are not approximated as one person's task.

## Evidence

Focused tests cover registry selection, generic output lowering, full status
coverage, target and digest mismatch, task collisions, content preservation,
idempotence, exact rollback, Python-only production dependencies, TypeScript
differential comparison, fresh/stale/future/missing/ambiguous topology, changed
assignments, duplicate delivery, and all four queue boundaries.

On 6 August 2026, the pinned reviewed browser harness executed and passed four
checks for each of CHT 4.22 and 5.2. Those runs support the reviewed
special-function fixtures. They do not execute the newly composed WS6 bundle in
an exact deployment, so the WS6 evidence manifest remains E2. Exact CHT sandbox,
live server, real handset, offline/sync, performance, accessibility,
translation, privacy/security, clinical validation, governance approval, and
deployment authorization remain `not_run` or `not_supplied` external work.

## Current limits

- The Product adapter still rejects nonempty broader rule, module, routing, and
  phrase-bank sections that require clinical inference.
- The only reviewed capability lowerer in this production allow-list is the
  synthetic gestational-age example.
- Runtime variable bindings and all activation inputs are synthetic examples.
- There is no group-obligation model.
- There is no FHIR or outbound messaging path in WS6.
