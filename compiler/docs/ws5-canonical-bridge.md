# WS5 canonical bridge and exact capability resolution

WS5 closes one deliberately narrow path from Product `clinical_logic` to
canonical Clinical IR. It is E2 tracer evidence, not deployment approval.

## Does the AI find the registry's words?

No. Prompt B is registry-blind and may describe a manual-grounded need in its
own local words. Those words never select a capability.

The focused mini-manual experiment in
`registry-keyword-mini-manual-evaluation.md` confirms why: an isolated model
found three of three needs but guessed zero of three unseen exact registry
IDs. Catalogue-visible suggestions may assist review, but only the reviewed
semantic binding and deterministic resolver can select executable behavior.

The boundary is:

```text
manual
  -> Prompt B candidate (source-grounded, registry-blind)
  -> optional registry-visible AI proposal (entry ref + variable mappings only)
  -> deterministic non-executable match review package
  -> reviewed semantic binding (content-addressed, still no capability ID)
  -> exact deterministic resolver
  -> capability ID + resolution lock
  -> canonical IR
```

The optional stage is implemented in `registry_match.py` and documented in
`registry-visible-match-review.md`. Code copies the selected catalogue entry;
the model never rewrites registry fields. Confidence is advisory, all review
packages say `executable_eligible=false`, and the existing human-reviewed
binding remains mandatory.

The reviewed binding records the normalized family and operation, ordered
parameter names/types/units, complete required status set, target profile,
subject scope, and Product variable bindings. Preparing that artifact is a
review task because Prompt B cannot safely infer registry vocabulary, target
configuration, status translation, or Product variable IDs from a manual.
Changing prose cannot change selection. Changing any exact semantic field
causes zero matches or a contract-mismatch diagnostic; multiple exact matches
are ambiguous.

The review is bound to the canonical digest of the exact Prompt B candidate
artifact. A candidate changed after review fails before conversion. The
reviewed schema rejects capability IDs and implementation fields, so a model
cannot smuggle its preferred implementation across the boundary.

## Supported vertical slice

The v1 adapter accounts for all seven Product sections. It converts the
synthetic tracer's variable catalog and empty structural sections. A nonempty
clinical section whose semantics are not already representable without
clinical inference produces a deterministic loss report and stops. Direct
canonical-IR authoring is the explicit descope path.

Local reads require a registered local-data binding ID. Date units remain
explicit as `calendar_date`. Technical capability outputs remain `st_*`
variables and are kept separate from the generated `o_*` usability decision.
The Clinical IR contains the resolved capability ID and variable mappings, but
no Python symbol, JavaScript filename, or other implementation binding.

## Inputs and outputs

The root command accepts, in order:

1. Product `clinical_logic`;
2. the exact registry-blind candidate artifact;
3. a content-addressed Product adapter;
4. registered CHT local-data bindings;
5. the content-addressed reviewed semantic binding;
6. a governed registry set;
7. an activation result produced by the WS3 approval boundary;
8. the exact target profile;
9. an output directory.

Example:

```powershell
$env:PYTHONPATH='compiler/src'
python -m chw_navigator.cli bridge-product `
  compiler/examples/ws5/product-clinical-logic.json `
  compiler/examples/ws5/candidate-capability-needs.json `
  compiler/examples/ws5/product-canonical-adapter.json `
  compiler/examples/tracer/local-data-bindings.json `
  compiler/examples/ws5/reviewed-capability-needs.json `
  compiler/contracts/examples/governance/valid-registry-set-v2.json `
  compiler/examples/ws5/synthetic-activated-release.json `
  compiler/examples/ws5/target-profile.json `
  compiler/generated/ws5
```

A successful run writes `canonical-ir.json`, `loss-report.json`, and
`resolution-lock.json`. If Product conversion is unsafe, it writes only the
blocked loss report. Output is deterministic and contains no timestamps.

The committed activation fixture is visibly synthetic. The bridge consumes an
activation result; it does not recreate signature verification, approval, or
expiry decisions. Production callers must obtain that result from the WS3
activation function using real attestations and a real signature verifier.

## Evidence limits

Automated tests cover unknown fields, coercion, provenance loss, unsupported
sections, local-binding failures, source-candidate mutation, reviewed-artifact
tampering, wording invariance, exact contract mismatches, zero/multiple
matches, registry ordering, target/release mismatch, deterministic output, and
compilation through the WS2 tracer harness and differential oracle.

This earns E1-E2 only. Exact CHT sandbox execution, real device/offline and sync
behavior, clinical approval, governance approval, privacy review, and
deployment authorization remain external E4-E6 work.
