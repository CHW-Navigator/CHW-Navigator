# CHW Navigator testing map

`Product/backend/tests/e2e_fixtures/` is the canonical home for the current
synthetic end-to-end test lab.  It contains ten intentionally small,
three-page manuals; synthetic people, facilities, and relationships; patient
edge cases; the independent behavior oracle; function and effect registries;
and the runnable fixture harness.  Nothing in that directory is real patient,
staff, contact, credential, or clinical-policy data.

Start there for current integration and release work:

- `README.md` explains the fixture contract and expected block conditions.
- `common/extension-registry.json` states exactly which test functions, local
  task types, and message types are available.  A function not listed as
  available cannot be assumed to exist.
- `clarifying_memos/` holds fictional NOG Clinical and Operations memoranda.
  A memo is usable only when a fixture explicitly cites it; it cannot repair an
  incomplete or contradictory manual.
- `run_fixture_pipeline.py` produces a run-local record of each stage.  Its
  task and message outputs go only to the console and local JSONL files.  It
  has no SMS, email, HTTP, provider, queue, or delivery adapter.

The `Aaron/`, `Angelina/`, and `Gigi/` folders are older focused prototypes.
They remain useful as historical or component-level checks, but are not the
authoritative current end-to-end corpus.

## Suggested checks

From the repository root, run the deterministic lab first:

```powershell
$env:PYTHONPATH = 'Product'
& "C:\Users\levine\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" `
  backend/tests/e2e_fixtures/run_fixture_pipeline.py --output-dir backend/tests/e2e_fixtures/runs/deterministic
```

Then run the ordinary regression checks:

```powershell
$env:PYTHONPATH = 'Product'
& "C:\Users\levine\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest `
  backend.tests.test_synthetic_e2e_fixtures
```

The harness has a separate live-extraction mode.  It accepts only complete,
eligible manuals and requires an already configured Anthropic key.  It does
not authorize real-world messaging or task delivery.

The selected Python environment must also have the project-declared
`anthropic`, `rlms`, and `z3-solver` packages installed.  The harness checks that before it
starts a live run and reports an environment-readiness block rather than
misclassifying a manual or silently downgrading the pipeline.

On Windows, the RLM compiler can start a child Python process.  That child
must use a runtime with the same declared compiler dependencies.  Local test
artifact generation deliberately does **not** require a generated Prisma
client or a reachable database: database persistence remains best-effort and
is loaded only when an application run elects to persist an artifact.
