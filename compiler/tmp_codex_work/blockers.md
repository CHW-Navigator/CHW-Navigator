# Blockers

## 2026-05-06: DOB -> age day-serial path implemented; calendar-date path still deferred

- Completed path:
  - integer day-serial DOB/as-of variables now work end to end through evaluator, Z3, generated XLSForm runtime, headless runner, and generated XLSForm re-import
  - supported helper calls in this path:
    - `is_missing(...)`
    - `date_diff_days(...)`
    - `age_months_from_date(...)`
    - `floor(...)`
- Remaining limitation:
  - this is a numeric day-serial path, not a free-form ISO calendar-date path
  - `age_months_from_date(...)` currently uses integer `floor((visit_day - birth_day) / 30)` semantics
- Recommended next step:
  - keep using the day-serial path for compiled logic
  - open a separate future task if exact calendar-month arithmetic is clinically required
