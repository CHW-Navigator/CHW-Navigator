# Can the AI find the registry's exact names?

## Short answer

It can identify the need, but it cannot reliably guess exact names from a registry it cannot see. In this recorded trial, the AI found all three requested needs, but guessed **0 of 3** hidden registry IDs exactly.

When shown a small catalogue, it selected all three exact entries after the matching assumptions were made clear. It also returned `no_match` when the right entry was removed and `ambiguous` when two entries had the same meaning. This supports catalogue-visible suggestions with deterministic checking. It does not support free-text guessing.

## Mini-manuals used

The trial used three new synthetic excerpts:

1. Read the current person's stored date of birth and stop if it is missing.
2. Use the WHO height-for-age standard in CHT to calculate a height-for-age z-score from sex, birth date, measurement date, and standing height in centimeters.
3. Use a CHT extension to calculate elapsed days between two Bikram Sambat dates and stop for a missing or invalid date.

The exact manuals and recorded outputs are in `Product/backend/tests/prompt_b_fixtures/registry_match_trials.json`.

## Results

| Trial | Result | Meaning |
|---|---:|---|
| Registry-blind Prompt B, strict parser | 3/3 needs found; 3/3 outputs valid | The AI can produce useful, source-grounded candidate needs for these examples. |
| Guess exact names without seeing the catalogue | 0/3 exact IDs | Exact local names and versions are not inferable from prose. |
| Visible catalogue, assumptions not clarified | 1 match; 2 abstentions | Scope and approval wording can cause safe but unnecessary abstention. |
| Visible catalogue, matching assumptions clarified | 3/3 exact IDs copied | The AI can propose a match when it is allowed to inspect the actual choices. |
| Selected entries supplied as structured JSON | 3/3 complete entry objects copied exactly | Machine-readable input and output constraints prevent field-name drift. |
| Correct entry removed | `no_match` | The AI did not substitute a nearby but wrong entry. |
| Duplicate equivalent entry added | `ambiguous` | The AI did not choose arbitrarily between two matches. |

The hidden guesses also changed other exact fields, not only the IDs. Examples included different family and operation names, `coded_string` instead of the registered `code`, a calendar encoded as a data type instead of a unit, and incomplete status sets.

## Architecture consequence

Prompt B should remain registry-blind. Its job is to say what the manual requires and cite the source. It should not be judged on whether it guesses local registry words, because exact local labels and versions are unknowable without the catalogue.

The safe boundary is:

```text
manual
  -> registry-blind candidate need
  -> optional AI suggestion that can see a read-only catalogue
  -> human review of the proposed parameter, unit, scope, status, and variable mapping
  -> deterministic exact matching
  -> zero matches or multiple matches stop the build
```

The optional AI step may copy an entry and explain the field-by-field comparison. It cannot approve the entry, change the catalogue, activate a release, invent missing fields, or make a fuzzy match executable. The existing WS5 reviewed semantic binding and exact resolver remain the authority.

This boundary is now implemented by `registry_match.py`. The model proposes an
existing entry reference and parameter mappings; deterministic code copies the
structured entry, runs the hard checks, and produces a review-only package.
See `registry-visible-match-review.md`.

## Hardened three-case pilot

The follow-up pilot keeps the two model stages separate and adds a nine-entry
catalogue with one obvious and one same-shape distractor for each case. The
registry-visible model selected all three intended entries, mapped every
parameter, and assessed all eight unselected entries per case. Deterministic
replay found zero hidden-answer mismatches. The date-of-birth case also proved
that a local action name must come from an explicit Product allow-list; without
that list the matcher now requests clarification, and an invented action ID
fails.

This is still only a three-case synthetic software pilot. Its 3/3 result is not
a reliability estimate and provides no clinical or deployment evidence. See
`synthetic-registry-pilot.md` for the retained inputs, output, and limits.

The field-copy trial initially changed shapes when the catalogue had been presented as prose, such as changing `outputs` to `output` and `target_profile` to `target`. It copied all fields exactly when given the structured JSON catalogue. Production code should perform that copy deterministically after a reviewed selection; there is no benefit in asking the model to retype it.

## What the next test set should contain

Repeat each concept with paraphrases and with deliberately difficult neighbours:

- birth date versus registration date, estimated date of birth, and caregiver-reported age;
- height-for-age versus weight-for-age and weight-for-height;
- Gregorian versus Bikram Sambat dates, inclusive versus exclusive day counts, and local-date conversion versus elapsed-day calculation;
- current contact versus household or group scope;
- centimeters versus meters and days versus completed days;
- missing, inactive, wrong-version, wrong-target, and duplicate entries;
- malicious manual text that tries to name or approve a function.

Measure these separately:

- candidate-need precision and recall;
- strict-format pass rate;
- exact full-signature match rate when the catalogue is visible;
- correct `no_match` and `ambiguous` rates;
- false executable match rate, whose required threshold is zero.

Run multiple fresh model calls and keep the expected entries hidden from the registry-blind stage. A recorded single run is useful regression evidence, but it is not a deployment-quality estimate.

## Evidence limits

The first experiment used one isolated model run per condition against a
synthetic six-entry catalogue. The hardened follow-up used a separate retained
blind extraction and registry-visible run against nine synthetic entries. Both
are recorded E2 evidence for narrow software mechanics only. Neither used the
Product live-model adapter, an approved ministry registry, an exact CHT runtime,
or human clinical/governance approval. Those remain `not_run` or `not_supplied`.
