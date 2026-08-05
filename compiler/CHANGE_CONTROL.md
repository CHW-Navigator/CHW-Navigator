# Change-Control Workflow

This document is the operator manual for introducing clinical deltas into CHW Navigator.

The goal is to make modifications:

- explicit
- reviewable by clinicians
- mechanically checked
- separable from the core compiler

## Core Principle

Treat each clinical modification as a patch to a named baseline, not as free-form prose and not as direct executable logic.

The workflow is:

1. baseline artifacts exist
   - memo/manual
   - DMN
   - Clinical IR
   - generated XLSForm / Mermaid / Z3 outputs
2. a new memo of intent describes the delta
3. the memo is reviewed for gaps and ambiguities
4. updated DMN / predicates / phrases / IR are produced
5. the change-review package is generated
6. clinicians review the delta
7. QA checks the delta
8. release is approved or blocked

## What Lives Outside the Compiler

The following are treated as a separate change-control layer:

- memo templates
- memo review and gap tracking
- delta package generation
- semantic diff reports
- XLSForm / Mermaid / patient-case delta reports
- clinician sign-off artifacts
- release gate checklists

## What Still Uses the Compiler

The change-control layer consumes compiler artifacts and APIs:

- Clinical IR loading and validation
- XLSForm lowering
- Mermaid lowering
- reference interpreter
- comparison harness
- bundle-style artifact writing

This keeps the implementation mostly separable.

## Required Inputs

At minimum the change-review workflow expects:

- a normalized change memo
- a baseline Clinical IR
- an updated Clinical IR

Optional but recommended:

- patient cases
- baseline DMN
- updated DMN

The memo contract is defined in:

- [contracts/change-memo.contract.md](<C:\Users\levine\Dropbox\PC (2)\Documents\Codex\CHW Navigator\contracts\change-memo.contract.md>)

## Recommended Review Artifacts

Every change package should show:

- the memo itself
- a concise change summary
- semantic delta by section
- variable delta
- predicate delta
- output delta
- decision/rule delta
- Mermaid before/after plus diff summary
- XLSForm before/after plus row-level diff
- case-level before/after behavior for explicit patient examples
- validation/lint summary for baseline and updated documents
- optional DMN delta if DMN files are provided

## Review Questions

Clinicians should be able to answer:

- what changed
- what stayed unchanged
- which patients now behave differently
- whether danger-sign and urgent-referral behavior is preserved
- whether missingness and stockout branches are safe
- whether operational burden increased

## Release Gates

A change should be blocked if:

- the updated IR fails validation
- lint has `ERROR` findings
- unresolved memo ambiguities remain without explicit waiver
- explicit comparison cases show unexpected differences
- safety invariants fail
- new pathways have no endpoint

## Current Implementation Boundary

The current implementation provides:

- a structured change memo contract
- a change-review package builder
- semantic diff artifacts
- impact-map artifacts
- XLSForm row-diff artifacts
- workflow-burden summaries
- Mermaid before/after artifacts and line-based diff summary
- baseline/updated CHT adapter stubs for history reads, task specs, and appearance defaults
- case-delta reports using explicit patient cases
- validation/lint summaries for baseline and updated IR

It does not yet provide:

- automated LLM memo red-teaming
- direct DMN semantic diffing beyond file-copy / optional textual diff
- clinician sign-off workflow state
- waiver tracking
- automatic release approval logic

## CLI

The change-review package is created with:

```powershell
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m chw_navigator.cli build-change-review `
  examples\change_memos\pneumonia_covid_no_test.memo.json `
  examples\pneumonia.ir.json `
  examples\pneumonia_covid_no_test.ir.json `
  generated\change_reviews `
  --patients examples\pneumonia_covid_no_test.cases.json
```

The output is a timestamped review folder under the requested root.

## Evidence Folder Convention

Evidence folders are immutable and intentionally accumulate over time.

Change-review packages now use a stable layout:

- `inputs/`
- `outputs/review/`
- `outputs/baseline_xlsform/`
- `outputs/updated_xlsform/`
- `outputs/baseline_cht/`
- `outputs/updated_cht/`
- `tests/explicit/`
- `tests/validation/`
- `metadata.json`
- `README.md`

The main review sequence is:

1. `outputs/review/change_summary.md`
2. `outputs/review/semantic_diff.json`
3. `outputs/review/impact_map.md`
4. `outputs/review/xlsform_delta.md`
5. `outputs/review/workflow_burden.md`
6. `tests/explicit/case_delta.md`
7. `tests/validation/safety_report.json`
