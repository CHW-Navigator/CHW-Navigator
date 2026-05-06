# CHW Navigator To Do

Last updated: 2026-05-05

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

- Add: given birthday, compute age.
  - prefer age derivation from date of birth over stale age snapshots
  - make this explicit in contracts and IR guidance

- Create a short authoring guide with examples.
  - good and bad JSON, CSV, and DMN examples
  - common failures and where they should be fixed

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

- Add more golden clinical examples beyond pneumonia and the current router example.

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

- Decide the final fate of the temporary `gen7` bridge.
  - review and keep briefly
  - or discard after the short compatibility window
