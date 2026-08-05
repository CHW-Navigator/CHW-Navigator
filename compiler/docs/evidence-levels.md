# Evidence levels and result semantics

## Result vocabulary

| Result | Meaning | Satisfies a mandatory check? |
| --- | --- | --- |
| `pass` | Executed and succeeded | Yes |
| `fail` | Executed and failed | No |
| `skipped` | Deliberately not executed, with reason | No |
| `not_run` | Environment/tool/hardware unavailable | No |
| `not_supplied` | Required human input absent | No |
| `not_comparable` | No defined cross-implementation semantics | No |

An aggregate containing a mandatory non-pass result cannot be reported as
green or deployment-ready.

## Evidence ladder

| Level | Evidence |
| --- | --- |
| E0 | Schema, lint, source lock, or other static validity |
| E1 | Deterministic local unit/property execution |
| E2 | Generated artifact, golden, differential, or mutation execution |
| E3 | Official tool or isolated official harness execution |
| E4 | Exact target-version sandbox execution |
| E5 | Representative offline/sync, server, device, or provider behavior |
| E6 | Clinical, governance, privacy/security, and deployment approval |

The overall level is the minimum across mandatory checks. A higher-level check
does not compensate for a lower-level mandatory failure. Exact CHT 4.22.0 or
5.2.0 sandbox execution is E4, not E2 or E3.

## Current claim boundary

Compiler and Product tests can establish local behavior. The isolated CHT
harness can establish only the behavior it actually executes. The current
source lock records that exact target CHT runtime, live CouchDB/offline-device
behavior, production identity/reconciliation, and staffed conflict review have
not been executed. No generated JSON or archived report overrides those limits.
