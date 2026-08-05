# Validation Layers

This project now uses three validation layers on purpose. Each layer has a
different job. Keeping those jobs separate makes the compiler easier to extend,
debug, and audit.

## Overview

1. `pydantic_models.py`
   - Question: "Is this structurally valid data?"
   - Use for schema and local contract checks.

2. `validator.py`
   - Question: "Is this Clinical IR semantically valid for the supported compiler subset?"
   - Use for type checking, decision semantics, and runtime-facing correctness.

3. `lint.py`
   - Question: "Is this artifact set suspicious, incomplete, or risky even if it is technically valid?"
   - Use for cross-artifact checks, hygiene, and authoring feedback.

These layers are complementary. They are not replacements for one another.

## What Goes Where

### Put a check in `pydantic_models.py` when it is about:

- required fields
- allowed enums
- identifier prefixes like `v_`, `p_`, `o_`
- embedded key/id consistency
- local object invariants
  - numeric domains must have `min/max`
  - enum domains must have `values`
  - expression shapes like `if` needing `cond/then/else`
- forbidding unknown extra fields

Rule of thumb:
- If the check can be decided by looking at one object payload in isolation,
  it probably belongs in Pydantic.

### Put a check in `validator.py` when it is about:

- expression type inference
- operator compatibility
- variable, predicate, constant, and output symbol resolution during semantic evaluation
- decision rule semantics
- output assignment typing
- invariant typing
- predicate dependency cycles
- supported-subset restrictions required by the current evaluator, XLSForm backend, or Z3 backend

Rule of thumb:
- If the check needs the full `ClinicalIRDocument` and is part of compiler
  correctness, it probably belongs in `validator.py`.

### Put a check in `lint.py` when it is about:

- suspicious architecture choices
  - predicates referencing outputs
- dead code
  - unused predicates
  - unused variables
- phrase coverage
- weak phrase bindings
- age-normalization warnings such as neonatal month-based thresholds
- authoring completeness warnings
- cross-artifact hygiene that should be fast and easy to understand

Rule of thumb:
- If the artifact can still run but the author should probably fix something,
  it probably belongs in `lint.py`.

## Current Fail Policy

- Pydantic failures: hard fail
- `validator.py` failures: hard fail
- `lint.py` `ERROR`: hard fail
- `lint.py` `WARNING`: report, but do not fail

This keeps the compiler strict on correctness while still providing useful
non-blocking feedback.

## Examples

### Pydantic examples

- Reject a variable with an unexpected extra field
- Reject a predicate with malformed expression shape
- Reject an output id that does not start with `o_`

### Validator examples

- Reject `p_fast_breathing` if its expression returns `int` instead of `bool`
- Reject a decision assignment that writes a string into a boolean output
- Reject cyclic predicate dependencies

### Lint examples

- Warn when a variable has no label phrase
- Warn when an output lacks message/guidance coverage
- Warn when `< 2 months` logic should probably use age-in-days normalization
- Error when a predicate expression references an `o_` output

## Adding New Checks

When adding a new check, ask these questions in order:

1. Can this be decided from one payload object alone?
   - If yes, prefer `pydantic_models.py`.

2. Is this part of semantic correctness or backend correctness?
   - If yes, prefer `validator.py`.

3. Is this mainly authoring hygiene, coverage, or a risky pattern?
   - If yes, prefer `lint.py`.

4. Is this deep logical reasoning rather than fast validation?
   - If yes, prefer Z3 or backend-specific analysis instead of any of the three above.

## Things To Avoid

- Do not duplicate the same check in all three layers.
- Do not put complex theorem-proving logic into Pydantic.
- Do not let lint become a second semantic validator.
- Do not let validator accumulate schema-only checks that Pydantic already handles.

## Practical Workflow

Typical flow:

1. Authoring artifact loaded
2. Pydantic validates shape
3. IR dataclasses are built
4. `validator.py` checks semantic correctness
5. `lint.py` reports cross-artifact warnings/errors
6. Backends run
   - evaluator
   - XLSForm
   - Mermaid
   - Z3

This separation is intentional. It gives faster feedback, clearer error
messages, and a cleaner place to add new checks over time.
