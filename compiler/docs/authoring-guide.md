# Authoring Guide

This guide is for teams preparing the upstream artifacts that feed the compiler.

Use it together with:

- `contracts/variable-catalog.contract.md`
- `contracts/predicate-catalog.contract.md`
- `contracts/phrase-bank.contract.md`
- `contracts/dmn.contract.md`
- `authoring-json-contracts.md`

## Source Of Truth

Author the clinical logic in:

- variable catalog
- predicate catalog
- DMN decision tables
- phrase bank

Do not treat compiled Clinical IR as the primary place to edit logic. IR is the compiled semantic representation, not the long-term authored source.

## Good vs Bad Patterns

### Variable catalog

Good:

- `v_temp_c_x10`
- `v_weight_g`
- `st_fever_done`
- `v_last_hb_h`

Bad:

- `temp`
- `weight`
- `historyHb`
- `feverDone`

Why:

- IDs should carry the family prefix and, for measured values, usually the stored unit.
- EHR/history-fed values should stay in the same families and may use `_h`.

### Predicate catalog

Good:

- keep compound logic in predicates
- use structured `expression` AST as the executable source
- keep `formal_definition` only as audit text or staging text

Bad:

- storing only a human-readable formula string and expecting the compiler to infer semantics
- duplicating variable units or numeric domains on predicates
- auto-deduplicating predicates by name shape

### Phrase bank

Good:

- use one row per phrase key / entity / role
- keep multilingual text in `text_<lang>` columns
- keep provenance structured

Bad:

- embedding message text directly into DMN or predicate rows
- mixing question labels and output guidance in one ambiguous phrase field

### DMN

Good:

- `FIRST` hit policy only
- input expressions are simple identifiers like `v_has_fever`
- input cells contain only `true`, `false`, or `-`
- use predicates for compound logic
- include an explicit wildcard fallback row when clinically appropriate

Bad:

- putting `AND`, `OR`, `NOT`, or parentheses directly in authored DMN cells for v1
- relying on non-`FIRST` hit policies
- using implicit or unprefixed identifiers

Why:

- authored DMN stays intentionally simple
- predicate tables hold the richer Boolean logic

## Where To Fix Problems

If something is wrong in a generated artifact:

- fix the variable catalog when the issue is about variables, domains, units, missingness, or measurement limits
- fix the predicate catalog when the issue is about computed Boolean logic
- fix the DMN when the issue is decision-table routing or output assignment
- fix the phrase bank when the issue is labels, messages, or multilingual text

Do not "fix only the compiled IR" unless you are doing temporary debugging and also plan to repair the authored source.

## Provenance

Every authored row should carry structured provenance.

Good:

```json
[
  {
    "source_id": "MOH_GUIDE_2026",
    "kind": "predicate_table",
    "page": 18,
    "section": "Respiratory assessment",
    "row": 7
  }
]
```

Bad:

- `WHO 2014 page 22`

Why:

- free-text provenance is hard to audit and compare
- structured provenance survives into compiled outputs and evidence bundles

## DOB and Age

Preferred long-term direction:

- use date of birth as the upstream clinical fact
- derive age fields systematically rather than hand-maintaining stale age snapshots

Current caution:

- helper names such as `date_diff_days` and `age_months_from_date` appear in validation/lint surfaces
- do not assume they are fully supported end to end in every backend until execution support is completed

For now:

- if you need a production-safe path in the current subset, provide the already-derived age variable explicitly, such as `v_age_days` or `v_age_months`
- keep DOB-related plans documented, but do not rely on validator-only helper names as if they are fully executable
