# Blockers

## 2026-05-06: DOB -> age execution support is incomplete

- Intended task:
  - standardize "given birthday, compute age" as a working compiled path
- What I found:
  - `validator.py` and `lint.py` know about helper names like `date_diff_days` and `age_months_from_date`
  - I did not find matching end-to-end execution support yet in the interpreter, XLSForm lowering/runtime, and Z3 lowering
- Why I stopped:
  - documenting these helpers as fully supported would overpromise
  - implementing them safely is a broader semantic change than a quick overnight patch
- Partial work saved:
  - this blocker note
  - follow-up docs work will treat DOB guidance as a preferred future path, not current guaranteed execution support
- Recommended next step:
  - add explicit helper semantics across evaluator, Z3 backend, and XLSForm lowering/runtime before promoting DOB-derived age as a compiled feature
