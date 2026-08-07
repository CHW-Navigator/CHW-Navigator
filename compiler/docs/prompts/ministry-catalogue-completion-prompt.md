# Ministry/NGO catalogue completion request

Use this request after the first AI has described a need but the catalogue does
not contain enough information for a safe match. This is a pilot form. Completing
it does not approve clinical logic or authorize deployment.

## Request to the Ministry or NGO

Please complete one section for each local-data read or calculation that the
software may use. If a fact is not yet decided, write `NOT DECIDED`. Do not ask
the AI to guess it.

1. **What is the function or local-data read called?**
   Give it a stable name and version. State whether it already exists in the
   target CHT deployment or is only planned.

2. **What exactly does it do?**
   Give a short plain-language description. Distinguish nearby operations—for
   example, height-for-age versus weight-for-age, or elapsed days versus date
   conversion.

3. **What information goes in?**
   For every input, give its exact name, meaning, data type, unit, allowed codes,
   whether it is required, and what a missing or invalid value means.

4. **What comes out?**
   For every output, give its exact name, meaning, data type, unit, and any
   rounding rule.

5. **Which records may it use?**
   State whether it applies to the current person, household, facility, or
   another group. For local data, give the exact CHT location, the form contexts
   where it is available, whether it can become stale, and which timestamp is
   used to judge freshness. Separately list the exact existing Product or
   compiler action IDs that the mapper is allowed to use for this read. If no
   action exists, write `NOT DECIDED`; the matching AI must not invent one.

6. **What limits apply?**
   Give the supported ages, dates, measurements, calendar years, and other
   boundaries. State what happens outside those limits.

7. **Which standard or reference data apply?**
   Give the standard name and version, the local adaptation if any, the exact
   reference-data file or chart version, and its SHA-256 digest. For growth
   calculations, state the age basis, sex codes, measurement method,
   interpolation, and implausible-value rules.

8. **Which date rules apply?**
   Name the calendar for every date. State whether counting includes or excludes
   each endpoint, what the same date returns, whether reversed dates are allowed,
   the supported year range, and the version and digest of any lookup table.

9. **Which result statuses can be returned?**
   List every success, missing-input, invalid-input, out-of-range,
   missing-reference-data, version-mismatch, and execution-failure result in the
   exact order used by the implementation. State what the workflow must do for
   each one.

10. **What evidence supports each fact?**
    For every source, provide title, publisher, version or date, section, URL or
    durable local location, retrieval date, content digest when available, and
    the exact claim it supports. Mark separately any fact that is an assumption
    made only for this software pilot.

11. **Who owns and reviews it?**
    Name the responsible clinical, data, technical, and operational roles. Do
    not enter an approval unless those people have actually reviewed it.

12. **Write one complete matcher-ready requirement.**
    Restate the supplied answers for this one entry in one contiguous paragraph.
    Include its exact meaning, inputs, outputs, units, scope, limits, missing and
    error behavior, reference-data version, and boundary rules. Do not add an
    undecided fact. This paragraph lets the first AI cite one exact passage
    without stitching together or silently rewriting separate bullets.

## Required response labels

Every pilot response must include these statements:

```text
Response type: SIMULATED FOR SOFTWARE PILOT
Clinical approval: NO
Deployment authorization: NO
Patient-care use: PROHIBITED
Unknown facts: listed explicitly; none inferred by AI
```

The AI may organize the supplied facts and point out conflicts. It may not fill
an undecided value, claim that a planned implementation exists, or turn this
response into an approval.
