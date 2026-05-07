# Start Here

## If you are new to this repo

Read these in order:

1. [README.md](../README.md)
2. [Authoring guide](./authoring-guide.md)
3. [User types manual](./user-types-manual.md)
4. [Contribute DMN for testing](./contribute-dmn.md)
5. [DMN intake runbook](./dmn-intake-runbook.md)

That sequence gives you:

- what the compiler is for
- what files it accepts
- what kind of contributor you are
- how to hand in DMN and related source artifacts
- how those artifacts get tested and bundled

## Repo map

### Core source

- `src/chw_navigator/clinical_ir.py`
  - typed Clinical IR data model
- `src/chw_navigator/pydantic_models.py`
  - structural/schema validation
- `src/chw_navigator/validator.py`
  - semantic validation
- `src/chw_navigator/lint.py`
  - IR lint for coverage/hygiene/review guidance
- `src/chw_navigator/staged_lint.py`
  - source, IR, and backend-specific staged lint

### Authoring ingest

- `src/chw_navigator/catalogs.py`
  - variable/predicate/phrase catalog ingest
- `src/chw_navigator/dmn.py`
  - DMN import and DMN source preflight
- `src/chw_navigator/xlsform_import.py`
  - supported XLSForm import back into IR

### Backends and proof

- `src/chw_navigator/xlsform_backend.py`
  - IR to XLSForm
- `src/chw_navigator/xlsform_runtime.py`
  - generated XLSForm runtime
- `src/chw_navigator/headless_runner.py`
  - independent headless XLSForm execution
- `src/chw_navigator/mermaid_backend.py`
  - Mermaid generation
- `src/chw_navigator/z3_backend.py`
  - Z3 lowering, analysis, and witness generation
- `src/chw_navigator/compare.py`
  - cross-engine comparison
- `src/chw_navigator/xlsform_proof.py`
  - XLSForm round-trip proof package
- `src/chw_navigator/change_control.py`
  - change-review packages
- `src/chw_navigator/bundles.py`
  - immutable intake/test evidence bundles

### CLI

- `src/chw_navigator/cli.py`
  - all user-facing commands

### Contracts and examples

- `contracts/`
  - team-facing input/output contracts
- `examples/`
  - reference source artifacts, gold examples, and patient suites
- `examples/catalogs/`
  - standalone variable/predicate/phrase catalog examples
- `examples/external_suites/`
  - externally designed patient-suite examples

### Tests

- `tests/`
  - regression coverage
- most useful starting tests:
  - `tests/test_staged_lint.py`
  - `tests/test_change_control.py`
  - `tests/test_xlsform_import.py`
  - `tests/test_xlsform_proof.py`
  - `tests/test_golden_examples.py`

## Common tasks

### I want to validate one IR file

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli validate examples\pneumonia.ir.json
```

### I want to preflight one DMN file

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli preflight-source dmn examples\pneumonia.dmn
```

### I want to preflight a full authoring bundle

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli preflight-bundle examples\catalogs\pneumonia.metadata.json examples\catalogs\pneumonia.variables.csv examples\catalogs\pneumonia.predicates.json examples\catalogs\pneumonia.phrases.csv --dmn examples\pneumonia.dmn
```

### I want to compile catalogs plus DMN into IR

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compose-ir examples\catalogs\pneumonia.metadata.json examples\catalogs\pneumonia.variables.csv examples\catalogs\pneumonia.predicates.json examples\catalogs\pneumonia.phrases.csv --output generated\pneumonia.base.ir.json
```

Then:

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli import-dmn generated\pneumonia.base.ir.json examples\pneumonia.dmn --output generated\pneumonia.full.ir.json
```

### I want to compare all engines on a patient suite

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli compare examples\pneumonia.ir.json --dmn examples\pneumonia.dmn --patients examples\pneumonia.cases.json
```

### I want to prove an XLSForm round trip

```bash
$env:PYTHONPATH='src'; .\.venv\Scripts\python -m chw_navigator.cli prove-xlsform generated\pneumonia\survey.csv generated\pneumonia\choices.csv generated\xlsform_proof --reference-ir examples\pneumonia.ir.json --patients examples\pneumonia.cases.json
```

## If something fails, where do I fix it?

- variable meaning, domain, units, measurement limits:
  - fix the variable catalog
- clinical condition logic:
  - fix the predicate catalog
- routing/table logic:
  - fix the DMN
- labels/messages/guidance text:
  - fix the phrase bank
- compiled IR only:
  - do not patch it as the primary source unless the task is explicitly about compiler internals

## Best files for orientation by role

### Clinical author / reviewer

- [Contribute DMN for testing](./contribute-dmn.md)
- [Authoring guide](./authoring-guide.md)
- `contracts/`

### Engineer working on compiler logic

- `src/chw_navigator/clinical_ir.py`
- `src/chw_navigator/pydantic_models.py`
- `src/chw_navigator/validator.py`
- `src/chw_navigator/compare.py`
- `src/chw_navigator/z3_backend.py`

### QA / evidence reviewer

- `src/chw_navigator/bundles.py`
- `src/chw_navigator/change_control.py`
- `src/chw_navigator/xlsform_proof.py`
- `examples/pneumonia_rr_cutoff_plus1.cases.json`
