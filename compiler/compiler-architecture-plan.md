# Unified Compiler Architecture for DMN, XLSForm, Z3, and Mermaid

## Purpose

This document defines the architecture and build plan for a compiler toolkit that converts structured clinical logic into:

- XLSForm for execution in ODK/CHT
- Mermaid diagrams for clinician audit
- Z3 models for formal checking and counterexample generation
- QA-ready internal representations and diagnostics

The system assumes the clinical manual has already been transformed into:

- DMN decision tables
- a variable catalog
- a predicate table
- a phrase bank

The core design principle is to build a compiler around a shared semantic core rather than a collection of pairwise translators.

## Objective

The toolkit must support two major workflows.

### Forward compilation

Inputs:

- DMN decision tables
- variable catalog
- predicate table
- phrase bank

Outputs:

- XLSForm
- Mermaid diagrams
- Z3 model
- QA diagnostics and source maps

### Legacy form analysis

Inputs:

- existing hand-authored XLSForms

Outputs:

- normalized internal representation
- analyzable logic graph
- Z3-backed QA diagnostics

## Architectural Principle

Do not build separate pipelines such as:

- DMN -> XLSForm
- DMN -> Z3
- XLSForm -> Z3

Instead build:

- source inputs -> normalized internal representations
- normalized internal representations -> backend-specific lowerings

This keeps semantics centralized, reduces duplicated logic, and makes correctness easier to reason about.

## Recommended Representation Layers

One monolithic IR is likely to bloat. The architecture should use explicit layers.

### 1. Source IR

Faithful parsed representations of inputs:

- DMN source model
- predicate-table source model
- variable-catalog source model
- phrase-bank source model
- XLSForm source model

Each node should retain provenance such as source file, sheet, row, XML element, page, section, or table reference.

### 2. Clinical IR

The canonical semantic layer for clinical logic.

It should contain:

- typed variables
- constants
- predicates
- decisions
- outputs
- invariants
- source references

This layer is the semantic ground truth for rule evaluation.

### 3. Form IR

The canonical semantic layer for questionnaire mechanics.

It should contain:

- questions
- groups and repeats if supported
- relevance conditions
- requiredness
- constraints
- calculations
- choice lists
- display text keys

This layer captures form behavior that is not itself clinical decision logic.

### 4. Backend Lowerings

Derived artifacts from the canonical layers:

- XLSForm rows and sheets
- Z3 terms and assertions
- Mermaid decision graphs
- diagnostics and reports

## Why Separate Clinical IR from Form IR

Clinical logic and form mechanics overlap, but they are not the same thing.

Clinical IR should answer:

- what facts are collected
- what predicates are true
- what decisions fire
- what outputs are produced

Form IR should answer:

- what is shown
- what is required
- what is constrained
- what is calculated
- in what order form expressions are evaluated

Keeping them separate avoids turning the IR into a general-purpose programming language while still supporting real XLSForm behavior.

## Semantic Constraints

The initial system should enforce a narrow, auditable subset.

### DMN constraints

- Support `FIRST` hit policy initially
- Require explicit rule priority order
- Prefer explicit `else` coverage for every decision
- Restrict outputs to a typed subset supported by downstream backends

### Predicate discipline

- Clinical decision logic should primarily consume named predicates
- Direct use of raw variables inside decision rules should be normalized into predicates during ingest
- Predicate definitions must declare inputs and missingness behavior

### Expression subset

Support a shared core expression language with:

- `and`, `or`, `not`
- `=`, `!=`, `<`, `<=`, `>`, `>=`
- `+`, `-`, `*`, `/`
- `if(cond, a, b)`
- `selected(x, 'choice')`

Reject unsupported XPath and unsupported FEEL constructs. Fail loudly and specifically.

## Data Model Expectations

### Variable catalog

Each variable should carry:

- stable identifier
- type
- domain
- unit if applicable
- allowed missingness
- collection mode
- provenance

Recommended identifier discipline:

- use `v_` for encounter-time input variables
- use `st_` for workflow or carry-forward state variables such as `st_fever_done`

Current implementation note:

- `st_` state variables are supported as ordinary scalar variables today
- list-valued state such as "completed modules" is not yet first-class and should be represented as flags or enums until multivalue state is implemented

### Predicate table

Each predicate should carry:

- stable identifier
- typed expression AST
- inputs used
- missingness policy
- provenance

### Phrase bank

The phrase bank should hold presentation content, not logic.

Logic should emit:

- output identifiers
- message keys
- recommendation keys

The current implementation can surface recommendation notes and guidance notes, but it does not yet have a first-class action or task-schedule model.

Presentation resolution should happen at the UI or form-generation layer.

## Provenance and Auditability

Provenance is a first-class requirement, not a convenience.

Every meaningful node in the system should retain:

- source artifact
- source location
- normalized identifier
- transformation history

The compiler should be able to explain:

- which source rule produced a predicate
- which DMN row produced an output branch
- which phrase-bank entry was attached to a recommendation

This is essential for clinician review, debugging, and governance.

## Missingness Model

Missingness is a central semantic concern and must not be hidden inside ad hoc defaults.

At minimum the system should model:

- present
- missing
- not applicable

If needed for safety-sensitive conditions, the model may later expand to include unknown or indeterminate states. Predicate definitions must specify how missing inputs are handled, rather than silently collapsing all missingness to false.

The current codebase partially models unknown values, but it does not yet implement a fully first-class distinction between unknown and not-applicable across every backend.

## Diagnostics the Compiler Should Support

The compiler should surface structured diagnostics such as:

- undefined references
- type errors
- domain mismatches
- cyclic dependencies
- unsupported expressions
- unreachable outputs
- overlapping decision rules
- uncovered decision space
- unsafe missingness handling
- provenance gaps

Diagnostics should be machine-readable and human-readable.

For safety-critical holes, the QA report should be written so it can be shown directly to clinical authorities. If a missing-path condition could leave a child untreated, the report should say so plainly and identify the source gap instead of hiding it inside a generic compiler error.

## Mermaid Role

Mermaid is an audit projection, not an execution backend.

Its role is to help humans inspect:

- decision sequence
- rule priority
- branching structure
- coverage and else behavior

It should be generated from canonical logic rather than authored independently.

## XLSForm Generation Principles

The XLSForm backend should be conservative and deterministic.

### Survey generation

Generate rows for:

- questions
- predicate calculations
- decision calculations
- output calculations
- note or message surfaces where needed

### Choice generation

Generate normalized choice lists from the variable catalog and form metadata.

### Backend limitations

- avoid external writes
- use a minimal verified XPath subset
- preserve deterministic evaluation order
- keep generated forms analyzable

## Legacy XLSForm Ingest

Reverse compilation from XLSForm should be explicitly subset-based.

Initial support should focus on:

- `relevant`
- `required`
- `constraint`
- `calculation`
- `selected()`
- simple groups

The goal is not to support all XLSForm behavior. Unsupported constructs should generate precise diagnostics.

Production forms with custom appearances, media annotations, repeats, or connector-specific extensions should be expected to fail subset validation until explicit support is added.

## Build Plan

### Phase 0. Semantic Contract

Define:

- core type system
- expression grammar
- missingness semantics
- evaluation order
- supported backend subset

This phase should settle the semantic contract before implementation fragments diverge.

### Phase 1. Parser and Validation Foundations

Build:

- expression parser
- AST definitions
- symbol table
- type checker
- dependency graph builder
- provenance model

Validation should catch schema and semantic errors early.

### Phase 2. Clinical IR and Reference Interpreter

Build the canonical Clinical IR and a deterministic evaluator for it.

This evaluator becomes the semantic ground truth against which backends are checked.

### Phase 3. Variable Catalog and Predicate Ingest

Parse and validate:

- variable catalog
- predicate table
- phrase bank bindings

Normalize expressions into typed AST form and attach provenance.

### Phase 4. DMN Ingest

Parse DMN XML into Source IR and lower it into Clinical IR.

Enforce:

- supported hit policy
- rule ordering
- explicit coverage conventions
- supported output model

### Phase 5. Z3 Backend

Compile Clinical IR into Z3 with explicit handling for:

- variable domains
- predicates
- decisions
- output conditions
- missingness assumptions

This backend supports formal checking and counterexample construction.

### Phase 6. Mermaid Backend

Generate clinician-facing decision graphs from canonical logic and provenance metadata.

### Phase 7. Form IR and XLSForm Backend

Build the Form IR and lower canonical logic plus form metadata into executable XLSForm artifacts.

### Phase 8. Legacy XLSForm Ingest

Parse supported XLSForm constructs into Form IR and, where possible, derive Clinical IR projections for QA and comparison.

## Key Design Decisions

### Predicate-first logic organization

Preferred logical flow:

- variables -> predicates -> decisions -> outputs

This keeps decision tables readable and reusable while preserving a clean normalization target.

### Typed outputs

Do not constrain the architecture to Boolean outputs only.

Canonical outputs should support at least:

- `bool`
- `enum`
- `int`
- `string_key`

Boolean-only outputs may still be used as a lowered representation where appropriate.

That said, typed outputs are still not the same as a full care-plan model. Follow-up actions, task schedules, and longitudinal workflow artifacts should be added as a later semantic layer instead of being overloaded into ad hoc output flags.

### Loud failure on unsupported constructs

The system should deliberately reject unsupported XLSForm, XPath, and FEEL features rather than approximating them silently.

The same rule should apply to unsupported math and lookup semantics in the formal backend: if the Z3 lowering cannot model a construct exactly enough to preserve trust, the compiler should reject it rather than claim verification coverage.

### Explicit fail-safe provenance

If the program team chooses to add a default fallback such as "all else fails -> refer to facility", that fallback must be explicit in the canonical logic and tagged with technical provenance such as:

- `source_id: SYSTEM_DEFAULT`
- `kind: system_failsafe`
- `note: "Fail-safe added by system because source logic left this path undefined"`

That way the Mermaid view, QA report, and downstream artifacts all make the safety intervention visible instead of silently changing the clinical logic.

## Risks

### Semantic drift across backends

If Z3, DMN evaluation, and XLSForm execution do not share a common semantic contract, agreement will be accidental and fragile.

Mitigation:

- define one canonical semantic layer
- lower everything from the same typed representation

### IR bloat

If the canonical representation tries to encode every source-language quirk, it will become unmaintainable.

Mitigation:

- separate Clinical IR from Form IR
- keep both minimal and typed

### Legacy form complexity

Hand-authored XLSForms often include hidden assumptions and unsupported constructs.

Mitigation:

- declare the supported subset
- emit precise diagnostics for the rest

### Clinical source ambiguity

Manuals often contain contradictions or under-specified conditions.

Mitigation:

- represent ambiguity as diagnostics
- keep provenance attached to every rule

## First Delivery Milestone

The first milestone should target a single condition, such as pneumonia, and prove that the architecture works end to end.

Inputs:

- variable catalog
- predicate table
- DMN
- phrase bank

Outputs:

- validated Clinical IR
- Mermaid audit diagram
- executable XLSForm
- Z3 model
- structured diagnostics

Success is not just code generation. Success is a stable semantic pipeline that can be extended to additional conditions without redesign.

## Bottom Line

Build a compiler with:

- explicit semantic layers
- typed canonical logic
- strict subset support
- provenance throughout
- deterministic backend lowering

That architecture gives the best chance of producing forms that are executable, auditable, and formally checkable without duplicating logic across multiple fragile pipelines.
