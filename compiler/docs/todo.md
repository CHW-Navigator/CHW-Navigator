# CHW Navigator To Do

Last updated: 2026-05-06

Execution rule:

- if one workstream blocks, save the partial work, write a blocker note, and continue with the next independent item

## Now

- Finalize the DMN contract.
  - Keep `FIRST` hit policy only.
  - Keep authored DMN cells simple in v1.
  - Do not allow `AND`, `OR`, `NOT`, or parentheses in authored DMN cells by default.

- Expand staged linting.
  - source artifact preflight lint
  - compiled IR validation + lint
  - backend-specific lint after XLSForm, Mermaid, and SMT/Z3 generation

- Add preflight validators for each authoring input.
  - variable catalog
  - predicate catalog
  - phrase bank
  - DMN
  - patient case JSON

- Keep provenance in all new artifacts.
  - preserve structured provenance through translation, compilation, QA logs, Mermaid, and bundles
  - do not fall back to free-text-only provenance

- Hash each artifact.
  - include artifact hashes in bundle metadata
  - use hashes to support diffing, reproducibility, and review

- Test the diff process end to end.
  - example: change pneumonia respiratory-rate cutoff by `1`
  - confirm the diff is visible in source artifacts, compiled IR, Mermaid, Z3-derived cases, comparison logs, and bundle metadata

- Define and test the mutation process.
  - keep mutation tests for DMN, IR, XLSForm, Mermaid, and SMT/Z3 artifacts
  - decide which mutations are routine regression versus one-off review

- Extend DOB-derived age support beyond the current day-serial path.
  - the compiler now supports integer day-serial DOB/as-of values and helper calls such as `date_diff_days(...)` and `age_months_from_date(...)`
  - future expansion, if needed, is calendar-exact date handling rather than the current day-serial convention

- Create a short authoring guide with examples.
  - good and bad JSON, CSV, and DMN examples
  - common failures and where they should be fixed

- Write a manual for user types.
  - especially authors adding DMN, predicate catalogs, phrase banks, and related XLS-based source artifacts
  - include clear pointers to the input rules and where each kind of fix belongs

- Define the intake runbook for "new DMN arrives".
  - where files go
  - which commands run
  - what bundle is produced
  - who reviews failures

- Define the source-of-truth editing policy.
  - specify exactly which authored artifacts must be updated when logic changes
  - prevent “fixing only the compiled IR”

## Next

- Run test patients through a real headless form runner.
  - target something Enketo-like or equivalent
  - compare the same patients across IR interpreter, DMN, generated XLSForm runtime, headless form runner, and Z3

- Build a differential review example from a slightly changed authored source set.
  - create a second DMN/predicate/phrase/source bundle with a small clinical change
  - regenerate compiler outputs, Mermaid, and evidence
  - prove the diff workflow is understandable to reviewers

- Strengthen the XLSForm-to-IR-to-Z3 proof path.
  - take XLSForm artifacts back into IR
  - use Z3 to prove consistency and surface gaps
  - make this part of the quality case for supported XLSForm ingest

- Run externally designed patient suites through all engines.
  - accept patient cases designed by others
  - compare results across DMN, Z3, IR, and XLSForm
  - store those runs as reviewable evidence bundles

- Remove low-value syntax burden from LLM prompts where the compiler or lint can enforce it instead.
  - keep prompts focused on content extraction and structured authoring
  - move mechanical contract enforcement into code

- Teach upstream authors the contracts.
  - variable catalog
  - predicate catalog
  - phrase bank
  - DMN
  - simulated patient data
  - engine/log outputs

- Keep CHT-specific elements distinct from core compiler logic.
  - core compiler should stay platform-neutral where possible
  - CHT-specific lowering, preload/history, and execution details should stay in clearly separated modules

## Later

- Build JSON Schema and stronger machine-checked contracts for all inputs.
  - initial JSON Schema export now exists for the JSON-shaped artifact families backed by Pydantic
  - remaining work is broader coverage, CSV/header validation, and team adoption

- Add more golden clinical examples beyond pneumonia and the current router example.
  - initial second small golden example now exists as `fever_basic`
  - remaining work is more condition families and richer real-world examples

- Standardize recommended Z3 numeric domains and scaling rules.
  - use scaled integers instead of floating point
  - keep Z3 domains broad enough to include bad-but-possible inputs
  - do not use WHO remeasurement/data-quality flags as proof-domain limits
  - keep validation logic separate from clinical logic
  - generate `cutoff - 1`, `cutoff`, and `cutoff + 1` synthetic cases in stored units

- Refine clinician-facing Mermaid labels further.
  - diagnosis/treatment phrasing
  - optional abbreviated labels for review meetings

- Define a release workflow for approved compiled artifacts.
  - review gates
  - signoff
  - versioning

- Add a clinical-equivalence report.
  - given two authored source sets such as DMN + predicate catalogs
  - report whether they are clinically identical over the supported proof space
  - distinguish “textually different but clinically equivalent” from “clinically changed”

## Maybe

- Add a first-class action/care-plan layer instead of encoding everything as outputs.
  - referral
  - follow-up timing
  - treatment plan
  - counseling/task outputs

- Add fuller missingness semantics end to end.
  - distinguish `present`, `unknown`, and `not_applicable`

- Add temporal/history support beyond the current naming and guidance layer.
  - carry-forward values
  - freshness windows
  - prior visit reasoning

- Expand Form IR further.
  - groups
  - repeats
  - broader legacy XLSForm subset

- Add additional target backends beyond CHT/XLSForm.
  - compile into CommCare format
  - compile into OpenSRP-oriented format

- Survey the feature set across likely CHW platforms.
  - find all possible CHT features relevant to this compiler
  - find likely features needed for FHIR-compliant CHW software, especially CommCare- and OpenSRP-style deployments
  - separate common clinical/workflow features from platform-specific execution or UI features

- Define the union model across target platforms.
  - create syntax, schemas, conventions, and IR coverage for the union of supported platform capabilities
  - keep platform-specific lowering distinct from the shared semantic core
  - be able to compile from the shared semantic core into all supported target formats

- Formalize the clinician review loop.
  - how Mermaid and QA findings get corrected upstream in DMN/predicate artifacts

- Survey additional practical use cases for the compiler.
  - beyond current CHT/XLSForm/Z3 review flows
  - include teaching, guideline migration, regression review, and multi-platform publishing scenarios

- Decide the final fate of the temporary `gen7` bridge.
  - review and keep briefly
  - or discard after the short compatibility window
