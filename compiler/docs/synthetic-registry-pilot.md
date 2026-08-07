# Three-case registry-matching software pilot

> SYNTHETIC SOFTWARE PILOT ONLY - NOT FOR PATIENT CARE OR DEPLOYMENT

This pilot answers one narrow question: after a registry-blind AI states the
need, can a second AI that sees a read-only catalogue select and map the right
entry? It does not test the clinical calculation, prove that an extension
exists, approve a catalogue, or authorize deployment.

## Cases

The pilot covers:

1. read the current person's local date of birth;
2. select WHO 2006 standing height-for-age for the stated age range; and
3. select end-exclusive elapsed days between two Bikram Sambat dates.

The simulated catalogue contains nine entries: each intended entry, an obvious
nearby entry, and a harder same-shape decoy. The hard decoys are estimated date
of birth, standing height-for-age for the wrong age range, and Bikram Sambat
inclusive day counting. Real CHT, WHO, and Medic sources are shown with the
limited background claim each supports. Those claims are labelled
`not_verified_in_run`. The invented interface names, exact limits,
reference-data digests, implementation existence, Ministry response, and review
are labelled `synthetic_assumption`.

## Retained evidence

- `simulated-ministry-response.md` is the simulated answer to the catalogue
  completion request and binds every synthetic catalogue claim by SHA-256.
- `clarified-mini-manuals.md` contains no registry entry names. A first AI saw
  only this file and produced the retained `independent-blind-candidates.json`.
- `independent-model-proposals.json` records a separate AI's catalogue-visible
  proposals, exact unchanged blind candidates, Product variables, allowed local
  action IDs, and request and normalized-response digests. Unavailable run
  metadata is reported as unavailable.
- `predeclared-expected-results.json` is a content-addressed synthetic answer key
  frozen before the final registry-visible run. It binds the complete catalogue,
  manual, ordered list of blind candidate artifacts (not mutable wrapper
  metadata), matcher prompt, selected-entry projections, Product
  logic (including the local-action allow-list), mappings, and complete proposed
  bindings. The matcher task was not
  allowed to inspect it. This is a recorded procedure in one uncommitted work
  session, not independently timestamped proof of blindness.
- `simulated-ministry-catalogue.json` is a strict, content-addressed nine-entry
  pilot catalogue with a separate digest for every complete entry projection.
- `PILOT-NO-CLINICAL-USE.txt` remains beside the standalone source files so a
  copied or detached pretend catalogue is still plainly marked as non-clinical.

Every source quotation must be exact text within its cited section of the bound
mini-manual. The registry-visible matcher may not alter the first AI's artifact.
The blind-evidence wrapper binds the raw Markdown bytes; each Prompt B candidate
separately binds the complete normalized three-section manual supplied to the
Product parser. These two digests intentionally cover different representations.
Every proposal must reproduce from the retained source, Product variables,
allowed local-action list, prompt, and catalogue. A local-data action ID must be
copied from that list; an empty list requires clarification. The runner repeats
all deterministic checks, then checks the complete selected entry, complete
Product binding context, and mappings
against the frozen answer key. It never trusts a stored `unique_match` result.
For this three-case pilot, the second AI must score every unselected catalogue
entry. Omitting a same-shape decoy stops the case; the confidence display is
accepted only when it is evaluable after that exhaustive comparison. Confidence
remains a non-authoritative reviewer aid.

## Run it

From the repository root:

```powershell
$env:PYTHONPATH='compiler/src'
.\.venv\Scripts\python -m chw_navigator.cli run-synthetic-registry-pilot `
  compiler/examples/pilot/simulated-ministry-catalogue.json `
  compiler/generated/synthetic-registry-pilot
```

The command writes only `PILOT-ONLY.txt`, `pilot-input.json`, and
`pilot-report.json`. Every output is watermarked, fixes clinical and deployment
permission to false, and uses a schema that production review and activation
parsers reject.

## Fail-closed tests

The tests cover exact three-case completeness, source-section and digest
tampering, catalogue member digests, stale and subtly changed Product variables,
a wrong same-shape entry, a changed complete entry projection, swapped same-type
date mappings, strict Boolean approval fields, post-check synthetic
attestations, production-parser rejection, and UTF-8 output. Synthetic review is
descriptive before the run; only the runner can issue a digest-bound software
pilot decision, and stopped cases receive `not_accepted`.

## What a passing result means

A pass means the three retained proposals can be reproduced, checked against a
predeclared synthetic answer key, and shown to a reviewer without becoming
executable. The evidence ceiling is E2.
It is not an estimate of model reliability: there are only three positive
cases and one retained run per case. A later evaluation needs fresh repeated
runs, paraphrases, absent and duplicate correct entries, prompt-injection
attempts, and predeclared scores for abstention and false matches.

The production compiler still requires real catalogue content, real approvals,
real implementation and reference-data verification, exact CHT sandbox tests,
and clinical, privacy, security, and deployment gates.

The governed production capability schema also cannot yet carry all of the
structured parameter value sets, missing-value rules, ownership facts, and
reference-data identity demonstrated by this richer pilot catalogue. Its
projection currently leaves technical `reference_data` empty. That is a
production blocker, not a field the AI may infer from prose.
