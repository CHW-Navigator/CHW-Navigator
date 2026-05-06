# Overnight Work Plan

Last updated: 2026-05-05

## Priority Order

1. Checkpoint workspace and roadmap cleanup
2. Source artifact preflight lint
3. IR and generated-artifact lint/report commands
4. Bundle/report hashing and provenance carry-through
5. Authoring guide and runbook hardening
6. Change-control cutoff example
7. DOB -> age guidance
8. Headless form-runner investigation

## Dependencies

- Source preflight should land before authoring-guide examples so the guide can point at real commands.
- IR/backend lint commands should land before bundle hashing/report updates so the bundle can store those reports.
- Cutoff-diff example should run after report/hashing patterns are in place.
- Headless form runner can be deferred if external tooling blocks progress.

## Risks

- External runner integration may block on missing local tooling or network access.
- DMN subset lint must stay aligned with the documented v1 contract.
- Generated-artifact lint should remain lightweight and not duplicate full semantic comparison.

## Execution Sequence

1. Create and maintain checkpoint files.
2. Reorganize `docs/todo.md` and add a DMN intake runbook.
3. Add source-preflight and staged lint/report commands.
4. Add backend lint reports for IR, XLSForm, Mermaid, and SMT/Z3.
5. Add artifact hashing to bundles and generated outputs.
6. Add authoring-guide examples and explicit DOB/age guidance.
7. Add cutoff-shift change-control example and tests.
8. Investigate headless form runner, store blocker notes if needed, and move on.
