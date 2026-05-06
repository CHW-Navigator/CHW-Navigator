# CHW Navigator To Do

Last updated: 2026-05-05

This list combines the current team priorities with deferred ideas that should stay visible for later review.

## Now

- Finalize the DMN contract.
  - Make the supported DMN subset explicit for authors.
  - Keep examples next to the contract.

- Keep DMN hit policy to `FIRST` only for now.
  - Fail loudly on any other hit policy.
  - Document why this restriction exists.

- Decide whether authored DMN should permit `AND`, `OR`, `NOT`, and parentheses.
  - Current safe default for authored DMN is to keep table cells simple and push compound logic into the predicate catalog.
  - If we expand the DMN subset, update the contract, importer, lint, and tests together.

- Run test patients through a real headless form runner.
  - Target something Enketo-like or equivalent.
  - Compare the same patients across:
    - IR interpreter
    - DMN
    - XLSForm runtime
    - headless form runner
    - Z3

- Write `lint.py` for authoring syntax and simple semantics.
  - Catch naming issues.
  - Catch unsupported tokens.
  - Catch obvious missing provenance.
  - Catch duplicate IDs and simple dependency mistakes.
  - Keep it stricter than staging sheets, but lighter than full compiler validation.

- Remove low-value syntax burden from LLM prompts where the compiler or lint can enforce it instead.
  - Keep prompts focused on content extraction and structured authoring.
  - Move mechanical contract enforcement into code.

- Test the diff process end to end.
  - Example: change pneumonia respiratory-rate cutoff by `1`.
  - Confirm that the diff is visible in:
    - source artifacts
    - compiled IR
    - Mermaid
    - Z3-derived cases
    - comparison logs
    - bundle metadata

- Define and test the mutation process.
  - Keep mutation tests for DMN, IR, XLSForm, Mermaid, and SMT/Z3 artifacts.
  - Decide which mutations are part of routine regression versus one-off review.

- Keep CHT-specific elements distinct from core compiler logic.
  - Core compiler should stay platform-neutral where possible.
  - CHT-specific lowering, preload/history, and execution details should stay in clearly separated modules.

- Add: given birthday, compute age.
  - Prefer age derivation from date of birth over stale age snapshots.
  - Make this explicit in contracts and IR guidance.

- Keep provenance in all new artifacts.
  - Preserve structured provenance through translation, compilation, QA logs, Mermaid, and bundles.
  - Do not fall back to free-text-only provenance.

- Hash each artifact.
  - Include artifact hashes in bundle metadata.
  - Use hashes to support diffing, reproducibility, and review.

- Teach upstream authors the contracts.
  - Variable catalog
  - Predicate catalog
  - Phrase bank
  - DMN
  - Simulated patient data
  - Engine/log outputs

- Create a short authoring guide with examples.
  - Show good and bad examples for JSON, CSV, and DMN.
  - Show common failures and how lint/compiler errors map back to them.

- Add preflight validators for each authoring input.
  - JSON Schema where useful.
  - CSV header and required-column validation.
  - DMN subset validation before full compile.

- Define the intake runbook for “new DMN arrives”.
  - Where files go
  - Which command sequence runs
  - What bundle is produced
  - Who reviews failures

- Define the source-of-truth editing policy.
  - When logic changes, specify exactly which authored artifacts must be updated.
  - Prevent “fixing only the compiled IR”.

- Push the current local main-branch commits once GitHub connectivity is available.
  - Current local commits to publish:
    - `4202085` `Improve Mermaid readability defaults`
    - `5278e1f` `Document Mermaid updates and branch split`

## Maybe

- Add a first-class action/care-plan layer instead of encoding everything as outputs.
  - Referral
  - Follow-up timing
  - Treatment plan
  - Counseling/task outputs

- Add fuller missingness semantics end to end.
  - Distinguish `present`, `unknown`, and `not_applicable`.

- Add temporal/history support beyond the current naming and guidance layer.
  - Carry-forward values
  - Freshness windows
  - Prior visit reasoning

- Expand Form IR further.
  - Groups
  - Repeats
  - Broader legacy XLSForm subset

- Build JSON Schema and stronger machine-checked contracts for all inputs.

- Add more golden clinical examples beyond pneumonia and the current router example.

- Refine clinician-facing Mermaid labels further.
  - Diagnosis/treatment phrasing
  - Optional abbreviated labels for review meetings

- Formalize the clinician review loop.
  - How Mermaid and QA findings get corrected upstream in DMN/predicate artifacts

- Define a release workflow for approved compiled artifacts.
  - Review gates
  - Signoff
  - Versioning

- Decide the final fate of the temporary `gen7` bridge.
  - Review and keep briefly
  - Or discard after the short compatibility window
