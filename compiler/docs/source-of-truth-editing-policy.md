# Source Of Truth Editing Policy

This policy exists to stop the team from fixing generated artifacts while leaving the authored clinical sources inconsistent.

## Authoritative Inputs

The authored clinical source of truth is:

- variable catalog
- predicate catalog
- DMN decision tables
- phrase bank

Clinical IR is the compiled semantic representation produced from those artifacts.

## Rule

When a reviewer finds a logic problem, fix it in the authored source that owns the problem.

Typical ownership:

- variable catalog:
  - variable names
  - units
  - domains
  - missingness allowance
  - optional MOH re-measure / don't-allow thresholds
- predicate catalog:
  - Boolean logic
  - helper expressions
  - predicate-level missingness handling
- DMN:
  - routing among decisions
  - rule order
  - output assignment
  - explicit fallback rows
- phrase bank:
  - question labels
  - output messages
  - guidance text
  - multilingual wording

## What Not To Do

Do not:

- patch compiled IR as the final fix
- patch generated XLSForm as the final fix
- patch Mermaid as the final fix
- patch SMT/Z3 text as the final fix

Those artifacts may be edited temporarily for debugging or mutation tests, but the lasting correction must go back to the authored source.

## Exception: System Defaults

If the compiler or review workflow adds a fail-safe rule such as a default referral path, mark it explicitly with structured technical provenance.

Examples:

- `source_id: SYSTEM_DEFAULT`
- `kind: system_failsafe`

This makes the exception visible in:

- compiled IR
- Mermaid review views
- evidence bundles
- QA reports

## Review Loop

When a bundle or comparison report shows a defect:

1. identify which authored artifact owns the issue
2. correct that source artifact
3. rerun compose/import
4. rerun staged lint
5. rerun compare and mutation checks
6. preserve the new evidence bundle
