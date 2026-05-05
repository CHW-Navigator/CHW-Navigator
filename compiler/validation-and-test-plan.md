# Validation and Test Plan for the DMN, XLSForm, Z3, and Mermaid Compiler

## Purpose

This document defines the validation strategy for a compiler that lowers clinical logic into DMN-backed execution, XLSForm, Z3 models, and Mermaid audit diagrams.

The goal is not only to verify that each backend runs, but to show that all supported backends preserve the same semantics under a shared canonical logic model.

## Core Validation Principle

The validation harness should compare execution results across:

- the Clinical IR reference interpreter
- DMN evaluation
- Z3-derived expected outcomes
- XLSForm execution

Mermaid is not an execution engine and should not be treated as a semantic oracle. Instead, Mermaid should be checked as a structural projection of the canonical rule graph.

## Canonical Comparison Loop

1. Generate or select a patient case.
2. Materialize the patient as typed variable assignments plus missingness state.
3. Run the case through the Clinical IR reference interpreter.
4. Run the case through DMN evaluation.
5. Evaluate the corresponding expectations from the Z3 model.
6. Run the case through the generated XLSForm in a controlled execution environment.
7. Compare all observable results.
8. Separately validate that the Mermaid graph matches the same decision structure as the canonical IR.

## Why the Reference Interpreter Is Required

Cross-comparing compiled artifacts is not enough. If DMN, Z3, and XLSForm all share the same lowering bug, they may agree while still being wrong.

The Clinical IR reference interpreter should be treated as the primary semantic oracle for supported logic. Every backend result should be compared against it.

## What to Compare

Validation should compare more than final recommendations.

For each patient case, capture:

- input variable values
- input missingness state
- normalized predicate truth values
- decision tables reached
- rule IDs fired
- output values
- message or recommendation keys
- diagnostics triggered if applicable

Comparisons should be exact unless a documented backend limitation justifies a known difference.

## Mermaid Validation Scope

Mermaid should be validated structurally, not semantically.

Check that Mermaid reflects:

- the same predicate and decision nodes
- the same edges
- the same rule priority order
- the same else branches
- the same terminal outputs

If Mermaid diverges from the canonical dependency or decision graph, that is a generation bug even if execution backends still agree.

## Test Categories

The harness should combine deterministic golden scenarios with Z3-generated synthetic patients.

### 1. Unit tests

These test isolated semantic components:

- expression parsing
- AST normalization
- type checking
- missingness handling
- predicate evaluation
- decision evaluation
- topological evaluation order

### 2. Golden clinical scenarios

These are clinician-approved patient examples with expected outputs and rationale.

They serve as stable regression tests and should be small in number but high in trust.

### 3. Backend conformance tests

These compare the same case across:

- Clinical IR reference interpreter
- DMN
- Z3 expectation
- XLSForm execution

### 4. Differential tests

These look for disagreements between backends and produce compact counterexample reports.

### 5. Negative tests

These verify that unsupported constructs, invalid types, bad references, and unsafe missingness cases fail loudly and precisely.

## Z3-Generated Patient Types

Z3 should not produce only random satisfiable cases. It should produce targeted classes of patient cases designed to expose logic errors.

### Boundary patients

Patients at variable boundaries:

- minimum values
- maximum values
- just below threshold
- exactly at threshold
- just above threshold

Examples:

- age exactly 12 months
- respiratory rate exactly 50
- weight at minimum allowed domain

### Rule-trigger patients

At least one patient per rule whose purpose is to fire that rule under valid conditions.

These confirm that every intended rule is actually reachable.

### Rule-separation patients

Patients constructed so that one rule fires while nearby competing rules do not.

These help detect overlaps, wrong priority ordering, and threshold mistakes.

### Overlap patients

Patients that satisfy two or more rule guards simultaneously when overlap should not happen, or when overlap is only safe under a particular hit policy.

These are useful for detecting hidden ambiguity in decision tables.

### Gap patients

Patients that satisfy no explicit non-else rule and therefore test exhaustiveness and fallback behavior.

### Missingness patients

Patients with strategically absent values:

- missing visible required value
- missing optional value
- hidden therefore missing value
- missing input to a critical predicate

These expose unsafe assumptions such as silently treating unknown data as false.

### Contradiction patients

Cases sought from the solver to show that a predicate, rule, or endpoint is impossible to satisfy under the stated domains and constraints.

These identify dead logic.

### Adversarial patients

Cases intentionally generated to stress confusing parts of the rule set:

- threshold boundaries across multiple inputs
- conflicting symptoms
- unusual but valid combinations
- domain extremes with partial missingness

### Counterexample patients

When an invariant fails, Z3 should return a concrete patient demonstrating the failure.

Examples:

- two incompatible outputs both true
- no terminal output when one is required
- referral not triggered despite a danger sign

### Coverage patients

Small optimized sets of patients chosen to cover:

- all predicates
- all decision branches
- all outputs
- all major combinations of endpoint categories

These help keep regression suites compact.

## Z3 Query Families

The validation harness should support solver queries for:

- satisfiability of each predicate
- satisfiability of each rule guard
- rule overlap
- decision gaps
- unreachable outputs
- invariant violations
- unsafe missingness combinations
- backend disagreement witnesses if encoded

Each positive or negative answer should be convertible into a human-readable report.

## Comparison Semantics

Define comparison semantics up front.

### Exact match expectations

The following should typically match exactly across supported backends:

- predicate truth assignments
- fired rule IDs
- terminal outputs
- message keys

### Explicitly documented exceptions

If a backend cannot represent some construct exactly, the limitation should be:

- documented
- tested
- surfaced in generated diagnostics

No silent approximation should be accepted.

## Failure Reporting

When a test fails, the harness should emit a compact differential report containing:

- patient ID
- input assignment
- missingness state
- expected results from the Clinical IR interpreter
- observed results per backend
- first divergence point
- source provenance for implicated rules

This makes failures debuggable for both engineers and clinical reviewers.

## Regression Strategy

Every resolved bug should add at least one regression case to the suite.

The suite should include:

- stable golden clinician scenarios
- a compact deterministic Z3-generated coverage set
- known edge-case patients from prior counterexamples

## Performance Strategy

Validation should be staged so that fast checks run frequently and expensive searches run on demand or in CI.

Suggested tiers:

- parser and unit tests on every change
- conformance tests on key conditions in CI
- larger Z3 search campaigns on nightly or release validation

## Release Gate

A condition should not be considered release-ready unless:

- all supported backend conformance checks pass
- all required clinician golden scenarios pass
- no unexplained backend disagreements remain
- no critical invariant violations remain
- Mermaid audit output matches the canonical graph

## Bottom Line

The validation system should treat Z3 as both:

- a proof and counterexample engine
- a synthetic patient generator

But the overall oracle must remain the canonical Clinical IR semantics. The strongest test harness is one that compares every executable backend against that semantic core while using Mermaid as an auditable structural view of the same logic.
