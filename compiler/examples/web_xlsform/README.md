# Web XLSForm Example

This fixture is based on the official XLSForm.org "tip calculator" example at:

- https://xlsform.org/en/

Source example shown in the documentation:

```text
type     | name   | label                          | calculation
decimal  | amount | What was the price of the meal?|
calculate| tip    |                                | ${amount} * 0.18
note     | display| 18% tip for your meal is: ${tip}|
```

Normalization applied for CHW Navigator import:

- the input field is named `v_amount` instead of `amount` so it satisfies the current variable ID contract
- the calculated field is named `o_tip` instead of `tip` so it becomes an explicit output in the current IR subset
- a minimal `choices.csv` with headers only is included because the local workbook loader expects both survey and choices files
