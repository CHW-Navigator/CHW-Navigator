# Phrase Bank Contract v1

## Purpose

Defines multilingual text associated with variables, predicates, outputs, and other auditable entities.

## Preferred Source Format

- CSV

JSON is also accepted, but CSV is preferred when the same phrase table carries multiple languages.

## Identifier Rules

- phrase keys should start with `m_`
- `entity_id` should reference a known entity such as:
  - `v_...`
  - `p_...`
  - `o_...`

If the target entity is an EHR/history-fed variable, keep it in the normal variable family and use the `_h` suffix when appropriate, for example `v_weight_kg_h`.

## Required Fields

- `key`
- `entity_id`
- `role`
- at least one language text
- `provenance`

## Allowed Roles

- `label`
- `hint`
- `message`
- `guidance`

## CSV Columns

Required columns:

- `key`
- `entity_id`
- `role`
- one or more `text_<lang>` columns
- `provenance_source_id`

Optional columns:

- `variable_name` as alias for `entity_id`
- `provenance_kind`
- `provenance_location`
- `provenance_row`
- `provenance_column`
- `provenance_table`
- `provenance_page`
- `provenance_section`
- `provenance_note`

## CSV Example

```csv
key,entity_id,role,text_en,text_fr,provenance_source_id,provenance_kind,provenance_location
m_v_age_months,v_age_months,label,Child age (months),Age de l'enfant (mois),MOH_GUIDE_2026,phrase_bank,row:1
m_o_referral,o_referral,message,Refer urgently to facility.,Referer en urgence a l'etablissement.,MOH_GUIDE_2026,phrase_bank,row:2
m_o_referral_guidance,o_referral,guidance,Explain why urgent referral is needed.,Expliquer pourquoi une reference urgente est necessaire.,MOH_GUIDE_2026,phrase_bank,row:3
```

## JSON Shape

```json
{
  "phrases": [
    {
      "key": "m_v_age_months",
      "entity_id": "v_age_months",
      "role": "label",
      "texts": {
        "en": "Child age (months)",
        "fr": "Age de l'enfant (mois)"
      },
      "provenance": [
        {
          "source_id": "MOH_GUIDE_2026",
          "kind": "phrase_bank",
          "location": "row:1"
        }
      ]
    }
  ]
}
```

## Lowering Semantics

- `role=label` on a variable becomes the XLSForm question label
- `role=message` on an output becomes an output-gated `note`
- `role=guidance` on an output becomes a second output-gated `note`

## Language Guidance

- prefer ISO-like short codes in suffixes such as `text_en`, `text_fr`, `text_sw`
- include `text_en` when possible because current defaults prefer English when selecting one label

## Provenance

Phrase rows must carry structured provenance in the same shape used by the variable catalog contract. Do not collapse provenance into a single unstructured citation string.
