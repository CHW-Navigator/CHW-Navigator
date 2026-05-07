# Contribute DMN For Testing

## Who this is for

Use this guide if you want to hand the compiler a new or revised DMN decision table set for review, testing, or conversion.

This is the right path for:

- clinicians or students proposing a new table
- authors revising a current table
- reviewers sending a guideline change for QA

## What to hand in

Minimum useful submission:

1. a DMN XML file
2. the matching predicate catalog
3. the matching variable catalog
4. the matching phrase bank

Strongly recommended:

5. a small patient-case suite
6. a short note describing what changed or what question the team should answer

## Folder locations

The canonical examples live under:

- `compiler/examples/`
- `compiler/examples/catalogs/`
- `compiler/examples/external_suites/`
- `compiler/examples/change_memos/`

If you are preparing a new submission, the safest pattern is:

- create a new example family under `compiler/examples/`
- create matching catalog files under `compiler/examples/catalogs/`
- add any hand-designed patient suites under `compiler/examples/external_suites/`

## Required source artifacts

### Variable catalog

See:

- `compiler/contracts/variable-catalog.contract.md`

Typical file:

- `compiler/examples/catalogs/pneumonia.variables.csv`

### Predicate catalog

See:

- `compiler/contracts/predicate-catalog.contract.md`

Typical file:

- `compiler/examples/catalogs/pneumonia.predicates.json`

### Phrase bank

See:

- `compiler/contracts/phrase-bank.contract.md`

Typical file:

- `compiler/examples/catalogs/pneumonia.phrases.csv`

### DMN

See:

- `compiler/contracts/dmn.contract.md`

Typical file:

- `compiler/examples/pneumonia.dmn`

## Important DMN rules in this repo

Current DMN subset:

- `FIRST` hit policy only
- keep DMN cells simple
- do not use `AND`, `OR`, `NOT`, or parentheses in authored DMN cells by default
- put compound clinical logic in predicates instead

If your DMN needs more than that:

- do not force it into the table cells
- add or revise predicates in the predicate catalog

## If you want your DMN tested

Run source preflight first:

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli preflight-source dmn examples\your_file.dmn
```

Then run full bundle preflight:

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli preflight-bundle examples\catalogs\your.metadata.json examples\catalogs\your.variables.csv examples\catalogs\your.predicates.json examples\catalogs\your.phrases.csv --dmn examples\your_file.dmn
```

Then compile:

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compose-ir examples\catalogs\your.metadata.json examples\catalogs\your.variables.csv examples\catalogs\your.predicates.json examples\catalogs\your.phrases.csv --output generated\your.base.ir.json
```

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli import-dmn generated\your.base.ir.json examples\your_file.dmn --output generated\your.full.ir.json
```

Then compare engines:

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compare generated\your.full.ir.json --dmn examples\your_file.dmn --patients examples\your_cases.json
```

If you do not have a patient suite yet, the compiler can still derive a Z3-based suite for comparison.

## If you changed an existing guideline

Use the change-review flow instead of only recompiling silently.

Good examples:

- `compiler/examples/catalogs/pneumonia_rr_cutoff_plus1.predicates.json`
- `compiler/examples/change_memos/pneumonia_rr_cutoff_plus1.memo.json`
- `compiler/examples/pneumonia_rr_cutoff_plus1.cases.json`

This pattern is for changes like:

- new cutoffs
- changed referral logic
- added fallback paths
- changed module routing

## Where to fix common failures

If preflight or compare fails:

- bad field names, units, measurement limits:
  - fix the variable catalog
- compound logic or threshold logic:
  - fix the predicate catalog
- rule ordering or routing:
  - fix the DMN
- labels/messages/guidance:
  - fix the phrase bank
- patient-case ambiguity:
  - fix the case JSON, not the compiler

## What not to do

- do not patch only the compiled IR as the main fix for authoring mistakes
- do not put complex boolean logic into DMN cells when predicates can express it more clearly
- do not use free-text provenance when a structured provenance record is available
- do not represent missing inputs by putting `null` into patient `values`; use the `missing` list

## Best companion docs

- [Start here](./start-here.md)
- [Authoring guide](./authoring-guide.md)
- [User types manual](./user-types-manual.md)
- [DMN intake runbook](./dmn-intake-runbook.md)
- [Source-of-truth editing policy](./source-of-truth-editing-policy.md)
