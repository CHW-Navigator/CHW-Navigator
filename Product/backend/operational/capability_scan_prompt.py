"""Prompt text for the non-authoritative capability scan stage."""

CAPABILITY_SCAN_PROMPT = """\
Read source-grounded clinical workflow material and emit only JSON capability
candidates. Every candidate must include id, family, operation, resource,
input_types, output_types, backend, requires_human_review, and source with
document_id, page, section, and an exact quote.\n\n
You may identify possible tasks, lifecycle rules, topology relations, special
functions, and external effects. Do not choose registry IDs, people,
facilities, phone numbers, delivery addresses, credentials, or policy values.
When a required binding is missing or ambiguous, record it as unresolved.
Candidates are proposals only; deterministic resolution and human review hold
the authority to approve them.
"""
