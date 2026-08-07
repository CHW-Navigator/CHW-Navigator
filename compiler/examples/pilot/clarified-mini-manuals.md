# Clarified mini-manuals for the registry-matching software pilot

> SYNTHETIC SOFTWARE PILOT ONLY - NOT FOR PATIENT CARE OR DEPLOYMENT

These three excerpts are synthetic. They contain no registry entry names,
function IDs, implementation bindings, or expected matches.

## Prior information

Before assessment, read `date_of_birth` from the current person's CHT contact
document in either contact or task context. It is an immutable Gregorian
`YYYY-MM-DD` date. If it is absent, stop and report `missing`.

## Growth assessment

For the current person in a CHT form or task, calculate the WHO 2006
standing-height-for-age z-score at 730 through 1825 completed days from sex
(`male` or `female`), Gregorian birth date, Gregorian measurement date, and
standing height in centimeters. Use synthetic pilot reference table
`WHO_CHILD_GROWTH_2006_HEIGHT_FOR_AGE`, standard version `2006`, data version
`synthetic-pilot-placeholder-0.1`, SHA-256
`cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc`.
Perform no additional rounding, and do not classify when an input or reference
table is missing, invalid, outside the supported range, or has the wrong version.

## Calendar calculation

In the current person's workflow, calculate integer elapsed days between two
Bikram Sambat dates for BS years 2000 through 2089 as end minus start, excluding
the end date from any additional count. The same date returns zero; reversed
dates are invalid. Use synthetic pilot conversion table
`MEDIC_BIKRAM_SAMBAT_TABLE`, standard version `pilot-assumption`, data version
`synthetic-pilot-placeholder-0.1`, SHA-256
`eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee`, without
rounding. Stop for missing, invalid, out-of-range, or wrong-version input or
reference data.
