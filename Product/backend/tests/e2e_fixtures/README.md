# Synthetic End-to-End Fixture Corpus

This corpus is an engineering test asset. It is not a clinical protocol and
must never be used for patient care. The manuals contain deliberately simple,
synthetic rules so that a failed extraction, conversion, topology lookup, or
missing-data guard has a small and reviewable counterexample.

Each file under `packages/` is a complete fixture package. It contains the
three source pages, the independent source/behavior oracle, a reference to the
synthetic deployment world, patient encounter inputs, and expected results.
`build_manual_pdfs.py` produces two derived files for each package:

- `manual.pdf`: the exact three-page manual used for ingestion tests.
- `guide.json`: a deterministic three-page guide fixture for pipeline replay.

The package file and its oracle must not be given to an extraction model. A
live run receives only `manual.pdf` (or its derived `guide.json`); the harness
uses the independent oracle afterwards.

## Registry, local effects, and clarifications

`common/extension-registry.json` is the single registry for the test lab's
native functions, Prompt 9 lookup, Prompt 10 planning, local task type, and
local message types.  It makes a deliberate capability gap visible:
`calendar-exact@1.0.0` is unavailable, so the calendar fixture must block.
There is no assumed generic `extension-lib`.

`local_extensions.py` is the only effect-like implementation in this corpus.
It writes a structured notice to standard output or run-local JSONL files and
rejects delivery-shaped fields.  It has no SMS, email, HTTP, provider, queue,
scheduler, or production task adapter.

`clarifying_memos/` contains fictional NOG clinical and operations memos.
They are attached explicitly by ID to a narrow set of eligible or deliberately
unsupported fixtures.  No source-blocked fixture may cite a memo, so an
underspecified manual cannot be repaired silently.

## Function profiles

The corpus does not assume a generic extension library exists. Every package
declares one of the following execution boundaries:

- `native_expression`: arithmetic and comparison that the clinical IR should
  express without a provider or plug-in.
- `topology_lookup`: an approved Prompt 9 relation/capability lookup.
- `prompt10_planning`: a version-locked Prompt 10 planning request only; no
  transport, provider receipt, or delivery is allowed.
- `unsupported_extension`: an explicit function requirement that the current
  pipeline cannot claim to implement. It must result in a release-blocking
  finding rather than a guessed calculation.

## Deployment-world fixtures

`common/topology-package.json` is a synthetic, valid Prompt 9 topology with
two facilities, one active CHW, one supervisor, one caregiver, and neutral
test-patient identifiers. Package setup may apply a small, declarative patch
to create an invalid or ambiguous deployment condition. The data contain no
real people, contact details, secrets, or provider destinations.

## Expected result vocabulary

- `eligible_for_artifact_and_behavior_test`: the manual and setup have enough
  information for extraction and behavior comparison.
- `manual_review_required`: a source omission, contradiction, or unassigned
  responsibility must block release. The system must not invent a threshold,
  owner, timing, or destination.
- `setup_validation_blocked`: the manual is sufficient, but a required local
  deployment fact is absent or invalid. No patient workflow may start.
- `extension_not_available`: the manual needs a named function outside the
  current supported function set. It is a declared gap, not a silent fallback.

## Generation and verification

Run from `Product/` with the bundled Python environment:

```powershell
& "C:\Users\levine\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" `
  backend/tests/e2e_fixtures/build_manual_pdfs.py
```

The generator verifies the page count and page text of every derived PDF. The
normal Python regression test validates package structure, source-oracle
separation, declared function-profile coverage, and the common topology.
PDF fixtures are declared binary in the repository attributes so Git cannot
normalize their line endings during staging or checkout.

## Runnable pipeline lab

`run_fixture_pipeline.py` has two explicit modes:

- Default deterministic mode runs all 10 packages through source/setup and
  extension admission, the independent raw-input oracle, Prompt 9/10 planning
  logic, and local-only task/message recording.  It reports expected blocked
  cases rather than trying to extract them.
- `--live <fixture-id>` invokes the configured Gen 8 clinical extraction only
  for a complete eligible manual.  The live run still has no real-world effect
  adapter, and verification can be run separately after artifact review.

The live run receives only the derived guide; it never receives the oracle,
patient cases, registry, memos, or expected output as model input.  In all
paths, an absent input remains `unknown`; it must not be coerced to `False`.
