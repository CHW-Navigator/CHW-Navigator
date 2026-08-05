# ADR-001: Python production compiler and TypeScript differential oracle

Status: accepted

Date: 2026-08-05

## Context

The authoritative repository contains a Python compiler. A separately reviewed
TypeScript workspace contains substantial contracts, vectors, diagnostics, and
tests. Deploying both would create two production sources of truth; rewriting
the TypeScript workspace would discard its independence and mature test corpus.

## Decision

- Python is the production compiler.
- The pinned TypeScript implementation is a test-only differential oracle and
  is never a production runtime dependency.
- Do not port the TypeScript implementation wholesale.
- Do not invoke Node as a production subprocess or service.
- Preserve the pinned TypeScript workspace, its tests, reference vectors,
  purity checks, and diagnostic catalogue unmodified.
- Run equivalent canonical cases through both implementations wherever they
  overlap.
- Compare normalized semantic results, not byte-identical output.
- Report unsupported comparisons as `not_comparable`, never as a pass.
- Retirement of the oracle requires protected-vector parity, equivalent
  negative and mutation coverage, and a later explicit ADR.

## Recorded WS0 human decisions

- Authoritative root: `CHW-Navigator-current`.
- Status policy: update nested documentation and mark the outer status/milestone
  instructions non-authoritative.
- Local data: retain the committed registered local-data capability.
- Prior prompts: keep Python Product Prompts 8-10 within their planning-only
  bounds; keep Python translations of Prompts 12A-14 plus task/local-data
  lowering; retarget remaining Prompt 11 gaps to Python; withdraw TypeScript as
  a production interpretation.
- Release 1 candidate: single-contact child-pneumonia assessment and follow-up,
  subject scope `current_contact`.

The gestational-age WS2 workflow is a technical tracer, not Release 1 clinical
policy.

## Consequences

Node remains a test tool only. A missing oracle is `not_run`; unsupported
semantics are `not_comparable`. Neither result satisfies a mandatory
differential gate. Exact CHT runtime, live server/offline behavior, and human
approval remain separate evidence levels.
