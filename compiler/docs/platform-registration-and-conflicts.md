# Platform registration and mutable-conflict integration

## What is integrated

Prompt 13 and Prompt 14 now have Python-owned platform contracts in the
authoritative compiler package:

- `src/chw_navigator/person_identity.py` owns the `Create x Person` decision;
- `contracts/identity-providers.json` registers the deterministic fixture provider;
- `src/chw_navigator/mutable_conflicts.py` owns correction events and the pure
  conflict resolver; and
- `contracts/conflict-policies.json` assigns a policy to each currently registered
  person/administrative field.

These services are outside clinical IR. Candidate lists are never inputs to clinical
decision tables, and correction ordering never changes clinical evidence.

## Person registration boundary

`resolve_person_identity(...)` returns exactly one of `resolved_existing`,
`created_new`, `registration_deferred`, or `registration_blocked`. It filters records
by authorization scope before comparison, returns only the minimal candidate shape,
and makes automatic merge unreachable.

The included provider is deliberately a deterministic fixture. Exact registered
identifiers may resolve one authorized person. Household, registered name, compatible
age, and compatible sex produce candidates for an explicit disposition; they never
prove identity. Offline scope remains part of every result.

Confirmed-new registration requires append-only provenance whose candidate list,
search scope, and offline limitation agree with the actual search. A deliberate-new
decision with candidates creates a `possible_duplicate_of` administrative event.

## Mutable conflict boundary

`resolve_mutable_field_conflicts(...)` is clock-free, network-free, and independent
of input order. It preserves every distinct assertion, collapses only byte-equivalent
redelivery, and diagnoses divergent reuse of an event ID. Resolution considers, in
order:

1. explicit supersession;
2. registered source authority;
3. authorized correction workflow;
4. platform receipt time; and
5. stable event ID as a mechanical tie-break.

Assertion and effective device times are retained as evidence but do not establish
authority. A deterministic display projection does not erase an unresolved conflict
or its `not_queued` review obligation. Append-only clinical evidence is rejected from
the mutable-field registry. The resolver also rejects reordered policy precedence and
cross-person supersession, so an administrative event cannot acquire authority over
another person's assertion by referring to its event ID.

CHT losing-revision and FHIR 409/412 functions are fixture translators only. They do
not claim live CouchDB or FHIR synchronization.

## Verification and evidence boundary

`tests/test_person_identity.py` covers authorization exclusion, exact identifiers,
ambiguous twins, order independence, minimal disclosure, deliberate-new provenance,
offline scope, and no-merge behavior. `tests/test_mutable_conflicts.py` covers field
policy completeness, authority and supersession, clock skew, missing predecessors,
idempotent delivery, divergent IDs, permutations, and local CHT/FHIR fixture
translation.

The normal diagnostic coverage gate requires all `PSR-ID-001` through `PSR-ID-005`
and `PSR-CONFLICT-001` through `PSR-CONFLICT-005` codes to be both emitted and
explicitly asserted.

The target repository has no live field-registration, CouchDB synchronization, FHIR
backend, or supervisor-review queue to wire into yet. Production matching accuracy,
live authorization, exact target synchronization, and queue execution therefore
remain external deployment gates rather than implied implementation claims.
