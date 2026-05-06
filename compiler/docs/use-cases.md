# Compiler Use Cases

## Purpose

This note captures practical use cases for the compiler beyond "turn one guideline into one XLSForm". It is meant to help the team decide which capabilities matter now, which are future platform work, and which are mainly review or teaching workflows.

## Current Strong Use Cases

### 1. Authoring QA for one guideline

- ingest variable catalog, predicate catalog, phrase bank, and DMN
- lint the source artifacts before compile
- compile to IR, XLSForm, Mermaid, and Z3
- generate explicit and Z3-derived patient suites
- compare IR, DMN, XLSForm runtime, headless runner, and Z3
- package the result as a review bundle with hashes and provenance

This is the strongest supported path today.

### 2. Change review for a small clinical edit

- keep a baseline source bundle
- make one bounded change in predicates or DMN
- rebuild outputs
- generate a change-review package
- show changed cases, semantic deltas, Mermaid deltas, and evidence hashes

This is the right workflow for cutoff shifts, referral-logic edits, and other narrow policy changes.

### 3. External patient-suite review

- accept patient cases designed by clinicians, students, or external reviewers
- run the same suite through IR, DMN, XLSForm, headless runner, and Z3
- store the run as evidence

This is useful when a team wants to challenge the system with hand-designed edge cases rather than only compiler-derived ones.

### 4. Supported XLSForm quality proof

- take a supported XLSForm subset
- import it back into IR
- compare the imported IR against the original generated behavior
- use Z3 and explicit cases to surface gaps

This is useful for proving that the generated or imported XLSForm subset stays semantically aligned with the compiler core.

### 5. Guideline teaching and review meetings

- show Mermaid flowcharts
- show a few patient cases
- show changed outcomes after a proposed edit
- keep the authored source artifacts visible, not just the compiled IR

This is a human-review use case, not just a software test use case.

## Near-Term Useful Use Cases

### 6. Source onboarding for new authors

- teach authors how to write variable catalogs, predicate catalogs, phrase banks, and DMN
- run preflight before they hand work to the compiler team
- give them targeted "fix this source file, not the compiled IR" guidance

### 7. Regression watch across releases

- keep a library of golden examples and external patient suites
- rerun them whenever the compiler changes
- track whether any outputs, predicates, or rule hits move unexpectedly

### 8. Clinical equivalence review on bounded suites

- compare two authored source sets on an explicit case suite
- report whether they are equivalent on outputs only, or on full predicates/outputs/rule hits

This is already supported in bounded form and should not be overstated as whole-proof-space equivalence.

## Future / Platform Expansion Use Cases

### 9. Multi-platform publishing

- compile the same semantic core to:
  - CHT / XLSForm
  - CommCare-like targets
  - OpenSRP-oriented targets

This remains future work and should stay separate from the current CHT-first hardening path.

### 10. Guideline migration and normalization

- import legacy or heterogeneous source artifacts
- normalize them into the compiler contracts
- compare old vs new semantics

This is valuable, but only after the current contracts and review workflow are stable.

### 11. Training and assessment

- use the compiler plus patient suites to teach guideline logic
- ask learners to predict outputs or propose edits
- compare their expectations to the compiled behavior

### 12. Multi-country or multi-version policy comparison

- keep two source bundles from different jurisdictions or editions
- show where they diverge on explicit patient suites
- support a structured review discussion rather than an unbounded textual comparison

## Anti-Use-Cases

These are cases the current compiler should not pretend to solve yet:

- arbitrary legacy XLSForm import
- whole-proof-space clinical equivalence for two authored source sets
- multi-platform publish with one stable union IR
- full temporal/history reasoning beyond the current naming and helper layer
- rich care-plan/task orchestration beyond the current limited action model

## Suggested Priorities

If the team wants to invest in use cases beyond the current path, the best order is:

1. strengthen authoring QA and review bundles
2. broaden external patient-suite review
3. improve bounded equivalence and regression workflows
4. only then start multi-platform publishing work
