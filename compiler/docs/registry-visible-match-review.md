# Registry-visible match proposals

This implements the optional second AI stage between Prompt B and the existing
WS5 human-reviewed binding. It is an authoring aid, not an approval or an
executable resolution.

## Boundary

```text
manual
  -> registry-blind Prompt B candidate
  -> registry-visible AI match proposal
  -> deterministic match review package
  -> human-authored reviewed WS5 binding
  -> existing exact WS5 resolver
  -> capability resolution lock
```

The second AI receives one candidate need, Product variables, the allowed
existing local-action IDs, and a read-only catalogue projected from the exact
governed capability registry and registered local-data bindings. The catalogue
omits implementation code. The model
can return only:

- `unique_match`;
- `ambiguous`;
- `no_match`; or
- `needs_clarification`.

For a proposed match, the model supplies an existing `entry_ref`, parameter to
variable mappings, alternatives, unresolved questions, rationale, and advisory
confidence. It cannot supply family, operation, registry parameter contracts,
status sets, target profiles, or implementation fields. Those fields are copied
from the selected structured catalogue entry by deterministic code.

## Hard checks

`evaluate_registry_match_proposal(...)` binds the proposal to the exact source
candidate, catalogue, Product-variable, and complete Product binding-context
digests and then checks:

- the selected entry exists and has the same need kind;
- only one catalogue entry has the complete semantic signature;
- inputs and outputs are mapped one-to-one;
- candidate, registry, and Product variable types agree;
- stated units agree exactly and unstated units request clarification;
- subject scope agrees exactly;
- candidate failure cases exist in the registry status contract;
- the technical status variable contains the complete ordered registry status set;
- local-data fail behavior agrees with the proposed fail mode;
- a local-data action ID is copied from the supplied allow-list, never invented;
- freshness-limited local reads map their recorded-at value; and
- every alternative is an actual catalogue entry.

Any hard conflict yields `no_match`. Missing source facts yield
`needs_clarification`. Duplicate complete signatures yield `ambiguous`.
Neither confidence nor catalogue order can override those outcomes.

## Confidence and human review

The review package shows the model's self-reported top confidence, the highest alternative,
and the margin. It also reports the example display rule discussed during
design: top confidence at least 90 percent and the second candidate at most 5
percent. If no alternative is supplied, the display is `not_evaluable`, never a
threshold pass. This rule only adds a reviewer warning. It is explicitly marked
`authoritative: false` and never changes deterministic eligibility.

Every package contains:

```json
{
  "human_review": {
    "required": true,
    "decision": "not_supplied"
  },
  "executable_eligible": false
}
```

A `unique_match` package contains a proposed technical WS5 need or local-data
adapter binding. A human must review the source quotation, alternatives, all
mappings, all checks, and the advisory score before authoring the existing
content-addressed WS5 reviewed artifact. The package itself cannot be changed
to `approved`; its strict parser rejects such a mutation.

## Command

The committed tracer proposal is synthetic and exercises the same gestational
age slice as WS5:

```powershell
$env:PYTHONPATH='compiler/src'
python -m chw_navigator.cli build-registry-match-review `
  compiler/examples/ws5/candidate-capability-needs.json `
  compiler/examples/ws5/registry-match-proposal.json `
  compiler/examples/ws5/product-clinical-logic.json `
  compiler/contracts/examples/governance/valid-registry-set-v2.json `
  compiler/examples/tracer/local-data-bindings.json `
  compiler/generated/ws5/registry-match-review.json
```

The output is deterministic and content-addressed after strict type
normalization. It remains non-executable even when every hard check passes.

## Catalogue completion

The catalogue now carries supported limits, rounding, reference-data identity
and digest, semantic rules, local-read freshness, and sources with the exact
claim each source supports. If those facts are missing, send the plain-language
[Ministry/NGO completion request](prompts/ministry-catalogue-completion-prompt.md).
The AI must preserve `NOT DECIDED`; it may not complete a Ministry fact itself.

The pilot catalogue can represent this richer information, but the governed
production capability source does not yet carry every parameter value set,
requiredness rule, ownership field, or reference-data identity. In particular,
the current production projection leaves technical `reference_data` empty.
Production use is blocked until those source contracts are extended and the
facts are supplied and approved; the matcher must not fill them.

## Mini-manual result

The three earlier mini-manuals are now passed through this boundary in tests.
Their original registry-blind outputs do not auto-match even when the proposal
claims 99 percent confidence: missing units and unresolved scope force
clarification or no match. When explicit clarifications supply the exact units
and subject scope, all three reach `unique_match` review packages—but still
remain non-executable and await human review.

The separate [three-case synthetic pilot](synthetic-registry-pilot.md) replays
one registry-blind model's retained needs and a second model's retained matches
against a nine-entry catalogue with obvious and same-shape decoys. A separately
frozen synthetic answer key checks the complete selection and mappings. It is
E2 software evidence only.

## Evidence limits

Tests establish deterministic contract behavior and recorded synthetic
mini-manual behavior only. There is still no configured production model
adapter, approved deployment entries for the three illustrative functions,
human approval, exact-target execution, or deployment authorization.
