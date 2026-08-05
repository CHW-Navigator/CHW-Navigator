# WS0 human decisions

Instructions: these decisions were confirmed by the user in the Codex task on
2026-08-05. WS0 Part B may proceed.

## Authoritative repository root

Decision: `CHW-Navigator-current` is the authoritative repository root.

Rationale or authority: User accepted the recommended default. This is the
reproducible Git history containing the Product and compiler implementations.

## Conflicting status claims

For each finding in `compiler/reports/ws0-discovery.md`, choose exactly one:
`update`, `archive`, or `mark non-authoritative`.

Decisions:

- Update the nested repository documentation to describe Product as the
  authoring application, Python as the production compiler, and TypeScript as
  a test-only oracle.
- Mark the outer `project_status.md` and its old milestone instruction as
  non-authoritative.
- Replace unqualified `deployment-ready` language with evidence-bounded
  `deployment candidate` language.

## Local-data implementation

Choose exactly one: `retain as an intentional compiler capability` or
`isolate from the implementation branch`.

Decision: `retain as an intentional compiler capability`.

## Prior Codex prompts

State which prior prompts remain in force, which are withdrawn, and which are
retargeted to the Python production compiler.

Decision:

- Keep Product Prompts 8-10 as Python planning/contract work within their
  documented no-live-effect boundaries.
- Keep the Python semantic integrations of Prompts 12A-14, CHT task lowering,
  and registered local-data lowering.
- Retarget remaining Prompt 11 gap-closing work to Python.
- Keep the reviewed TypeScript implementation only as a read-only test oracle;
  withdraw any interpretation of it as the production compiler.

## Candidate Release 1 clinical workflow

Workflow name: `single-contact child-pneumonia assessment and follow-up`.

Subject scope: `current_contact`.

If the subject scope is `household`, `service_area`, or `cohort`, state whether
Release 1 is descoped to `current_contact` or WS1/WS2 must stop for a separate
group-obligation design.

Scope disposition: Release 1 excludes household, service-area, and cohort
obligations. The gestational-age workflow in WS2 is a technical tracer, not the
Release 1 clinical policy.

## Human gate

Decision owner: Confirmed by the user in this Codex task; personal identity is
not recorded in this artifact.

Decision date: `2026-08-05`

Gate status: `pass`
