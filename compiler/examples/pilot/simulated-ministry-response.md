# Simulated Ministry response for the registry-matching software pilot

> **SYNTHETIC SOFTWARE PILOT ONLY — NOT FOR PATIENT CARE OR DEPLOYMENT**

Response type: **SIMULATED FOR SOFTWARE PILOT**
Clinical approval: **NO**
Deployment authorization: **NO**
Patient-care use: **PROHIBITED**
Implementation status: **SIMULATED; the three named interfaces have not been verified in a target deployment**

This response demonstrates what a sufficiently complete Ministry or NGO answer
could look like. The WHO and CHT links are real background sources. The exact
interfaces, reference-data digests, limits, and review are invented for this
pilot and are not endorsed by those sources.

## Date of birth

**Matcher-ready requirement:** Before assessment, read `date_of_birth` from the
current person's CHT contact document in either contact or task context. It is
an immutable Gregorian `YYYY-MM-DD` date. If it is absent, stop and report
`missing`.

- Stable pilot entry: `pilot.local.person.date-of-birth@1.0.0`.
- Read `date_of_birth` from the current person's contact document.
- Treat it as a Gregorian `YYYY-MM-DD` date.
- It is available when a form is opened for the contact or from a task for that
  contact. For this pilot, date of birth is treated as immutable and therefore
  has no freshness timestamp.
- If absent, stop and report `missing`.
- The only allowed existing Product action ID for this synthetic pilot is
  `a_date_of_birth_read`. Its existence in a target deployment is not verified.
- CHT documentation supports contact-field access and shows a `date_of_birth`
  field. The exact deployment path and immutability rule remain pilot assumptions.

## WHO height-for-age

**Matcher-ready requirement:** For the current person in a CHT form or task,
calculate the WHO 2006 standing-height-for-age z-score at 730 through 1825
completed days from sex (`male` or `female`), Gregorian birth date, Gregorian
measurement date, and standing height in centimeters. Use synthetic pilot table
`WHO_CHILD_GROWTH_2006_HEIGHT_FOR_AGE`, standard version `2006`, data version
`synthetic-pilot-placeholder-0.1`, SHA-256
`cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc`.
Perform no additional rounding, and do not classify when an input or reference
table is missing, invalid, outside the supported range, or has the wrong version.

- Stable pilot entry:
  `pilot.technical.growth.who-hfa-standing-24-60m@0.1.0`.
- Run this calculation only for the current person in the CHT form or task
  context; do not infer a household or other-person scope.
- Inputs: sex (`male` or `female`), Gregorian birth date, Gregorian measurement
  date, and standing height in centimeters.
- Output: height-for-age z-score.
- Use the WHO 2006 standing-height-for-age standard only for completed age from
  730 through 1825 days in this pilot.
- Age is measurement date minus birth date in completed days. Use standing
  height, an LMS table lookup, and no additional rounding.
- The reference-data identifier and SHA-256 value in the catalogue are synthetic
  placeholders. They do not contain verified WHO table bytes.
- WHO publishes the underlying 2-to-5-year height-for-age standards. CHT
  documentation supports extension libraries. Neither source establishes that
  this invented interface exists or is clinically equivalent.

## Bikram Sambat elapsed days

**Matcher-ready requirement:** In the current person's workflow, calculate
integer elapsed days between two Bikram Sambat dates for BS years 2000 through
2089 as end minus start, excluding the end date from any additional count. The
same date returns zero; reversed dates are invalid. Use synthetic pilot table
`MEDIC_BIKRAM_SAMBAT_TABLE`, standard version `pilot-assumption`, data version
`synthetic-pilot-placeholder-0.1`, SHA-256
`eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee`, without
rounding. Stop for missing, invalid, out-of-range, or wrong-version input or
reference data.

- Stable pilot entry:
  `pilot.technical.calendar.bikram-sambat-elapsed-days-exclusive@0.1.0`.
- Run this calculation only inside the current person's workflow context for
  this pilot; no household or group scope is authorized.
- Inputs: start date and end date, both in Bikram Sambat.
- Output: integer elapsed days.
- Rule: Gregorian equivalent of end minus Gregorian equivalent of start; the end
  date is not additionally counted. The same date returns zero. A reversed date
  range is invalid.
- Synthetic supported range: BS years 2000 through 2089.
- Medic's `bikram-sambat` repository supports BS month lengths and BS/Gregorian
  conversion. CHT supports extension libraries. The elapsed-day wrapper,
  supported range, table version, and digest are pilot assumptions.

## Deliberate nearby entries

The catalogue also includes registration date, an enrollment-estimated birth
date with the same output shape, WHO weight-for-age, a same-shape HFA entry for
the wrong age domain, Gregorian inclusive-day counting, and same-shape Bikram
Sambat inclusive-day counting. These are intentional distractors. They must not
be selected merely because their parameter types or words are similar.

For this pilot, the six distractors have these exact synthetic meanings:

- `pilot.local.person.registration-date@1.0.0`: Read the current contact's
  immutable `registration_date`, a proleptic-Gregorian `YYYY-MM-DD` date, in
  contact context only. It has no input, returns `registration_date` with unit
  `gregorian_date`, and returns exactly `available` or `missing`. It has no
  recorded-at field or maximum age. Its implementation existence is simulated.
- `pilot.local.person.estimated-date-of-birth@1.0.0`: Read the current contact's
  immutable enrollment-estimated `date_of_birth`, a proleptic-Gregorian
  `YYYY-MM-DD` date, in contact or task context. It has no input, returns
  `date_of_birth` with unit `gregorian_date`, and returns exactly `available` or
  `missing`. It has no recorded-at field or maximum age. Its estimate kind is
  `enrollment_estimate`, and its implementation existence is simulated.
- `pilot.technical.growth.who-wfa-0-60m@0.1.0`: For the current contact, take
  required sex (`male` or `female`), Gregorian birth date, Gregorian measurement
  date, and `weight_kg` in kilograms. Return `weight_for_age_z_score` with unit
  `z_score` for 0 through 1825 completed age days. Use LMS-table lookup, no
  additional rounding, and synthetic reference
  `WHO_CHILD_GROWTH_2006_WEIGHT_FOR_AGE`, standard `2006`, data version
  `synthetic-pilot-placeholder-0.1`, SHA-256 equal to 64 `d` characters. Use
  the complete ordered technical status and blocking rules below. Clinical
  equivalence is not verified and implementation existence is simulated.
- `pilot.technical.growth.who-hfa-standing-0-23m-wrong-domain@0.1.0`: For the
  current contact, take required sex (`male` or `female`), Gregorian birth date,
  Gregorian measurement date, and `standing_height_cm` in centimeters. Return
  `height_for_age_z_score` with unit `z_score` only for 0 through 729 completed
  age days. Use standing height, LMS-table lookup, no additional rounding, and
  deliberately wrong synthetic reference
  `WHO_SHAPED_SYNTHETIC_STANDING_HEIGHT_FOR_AGE`, standard
  `wrong-domain-pilot-decoy`, data version `synthetic-pilot-placeholder-0.1`,
  SHA-256 equal to `ab` repeated 32 times. Use the complete ordered technical
  status and blocking rules below. Clinical equivalence is not verified and
  implementation existence is simulated.
- `pilot.technical.calendar.gregorian-elapsed-days-inclusive@0.1.0`: For the
  current contact, take required Gregorian `start_date` and `end_date` and return
  integer `elapsed_days` for Gregorian years 1900 through 2100. Count both
  endpoints, so equal dates return one; reversed dates are invalid. Use no
  reference table and no rounding. Use the complete ordered technical status
  and blocking rules below. Implementation existence is simulated.
- `pilot.technical.calendar.bikram-sambat-elapsed-days-inclusive@0.1.0`: For the
  current contact, take required Bikram Sambat `start_date` and `end_date` and
  return integer `elapsed_days` for BS years 2000 through 2089. Count both
  endpoints, so equal dates return one; reversed dates are invalid. Use no
  rounding and synthetic reference `MEDIC_BIKRAM_SAMBAT_TABLE`, standard
  `pilot-assumption`, data version `synthetic-pilot-placeholder-0.1`, SHA-256
  equal to 64 `e` characters. Use the complete ordered technical status and
  blocking rules below. Implementation existence is simulated.

## Catalogue-wide pilot contract

- Target profile for every entry: `cht-core-5.2@1.0.0`.
- Every listed technical input is required. A missing input returns
  `input_missing`; invalid input returns `input_invalid`; an unsupported age,
  date, or measurement returns `outside_supported_domain`.
- Every technical interface returns statuses in this exact order: `ok`,
  `input_missing`, `input_invalid`, `outside_supported_domain`,
  `reference_data_unavailable`, `numeric_failure`, `version_mismatch`,
  `execution_failure`. The workflow may continue only on `ok`; every other
  status blocks the pilot classification and is shown for review.
- The three local reads return exactly `available` or `missing`. They are
  immutable, so they cannot return `stale` and need no recorded-at field.
- Sex is required and limited to `male` or `female`. Technical outputs use no
  additional rounding. The catalogue's parameter names, units, ranges,
  reference-data identities, boundary rules, and status order are exact
  synthetic interface facts, not verified implementation facts.
- Each `source_entry_digest` is the canonical SHA-256 of a retained descriptor
  containing `authoring_kind=synthetic_catalogue_entry`, the exact entry ID,
  and this response's SHA-256. It is not a digest of deployed code.

## Simulated ownership and review

- Clinical role: `synthetic-role-clinical-reviewer`
- Data role: `synthetic-role-data-steward`
- Technical role: `synthetic-role-cht-engineer`
- Role-play scope: may describe software-pipeline mechanics only; it records no
  decision before the post-check synthetic attestation
- Real clinical, governance, privacy, security, and deployment review: not done
