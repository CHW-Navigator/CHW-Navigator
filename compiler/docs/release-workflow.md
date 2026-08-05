# Release Workflow

This workflow is the minimum review path before a compiled artifact is treated as approved for use.

## 1. Source Intake

Required authored inputs:

- metadata
- variable catalog
- predicate catalog
- phrase bank
- DMN
- optional explicit patient suite

Required checks:

- `preflight-source` for each artifact
- `preflight-bundle` across the full authored set

## 2. Compile And Validate

Required generated artifacts:

- compiled IR
- XLSForm
- Mermaid
- SMT/Z3 artifacts

Required checks:

- `lint-ir`
- backend-specific lint for XLSForm, Mermaid, and SMT/Z3
- compare reports for explicit cases and/or derived suites

## 3. Evidence Bundle

Every candidate release should have a bundle that includes:

- copied inputs
- generated outputs
- lint reports
- compare reports
- artifact hashes
- provenance metadata

The bundle is the review record. Do not treat raw terminal output as the durable approval artifact.

## 4. Clinical Review

Clinical reviewers should inspect:

- bundle README
- top lint findings
- Mermaid review graph
- changed explicit patient cases
- any change-review package if the release differs from a prior approved version

Questions to answer:

- does the logic reflect the guideline?
- do changed cases look intended?
- are any warnings acceptable, or do they require fixes?

## 5. Technical Review

Technical reviewers should confirm:

- no blocking validation/lint errors
- cross-engine agreement on the supported cases
- mutation checks still fail when artifacts are intentionally altered
- no unsupported constructs slipped through as approximations

## 6. Signoff States

Suggested states:

- `draft`
- `ready_for_clinical_review`
- `needs_source_fix`
- `approved_for_release`
- `superseded`

## 7. Versioning

For each approved release, record:

- guideline ID
- authored source versions or hashes
- compiler version
- bundle path
- release date
- approving reviewers

## 8. If A Problem Is Found After Review

1. identify the owning authored artifact
2. fix the source artifact
3. rerun compile, lint, and compare
4. create a new bundle or change-review package
5. mark the prior candidate as superseded rather than silently overwriting it
