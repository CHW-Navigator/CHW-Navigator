from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class ChoiceRow:
    list_name: str
    name: str
    label: str


@dataclass(slots=True)
class SurveyRow:
    type: str
    name: str
    label: str = ""
    relevant: str = ""
    calculation: str = ""
    required: str = ""
    constraint: str = ""
    role: str = ""


@dataclass(slots=True)
class XLSFormWorkbook:
    title: str
    form_id: str
    survey: list[SurveyRow] = field(default_factory=list)
    choices: list[ChoiceRow] = field(default_factory=list)

    def survey_headers(self) -> list[str]:
        return ["type", "name", "label", "relevant", "calculation", "required", "constraint"]

    def choice_headers(self) -> list[str]:
        return ["list_name", "name", "label"]


def load_xlsform_workbook(survey_path: str, choices_path: str) -> XLSFormWorkbook:
    survey_rows: list[SurveyRow] = []
    choice_rows: list[ChoiceRow] = []

    with Path(survey_path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _require_headers(reader.fieldnames or [], XLSFormWorkbook("", "").survey_headers(), survey_path)
        for row in reader:
            survey_rows.append(
                SurveyRow(
                    type=row.get("type", ""),
                    name=row.get("name", ""),
                    label=row.get("label", ""),
                    relevant=row.get("relevant", ""),
                    calculation=row.get("calculation", ""),
                    required=row.get("required", ""),
                    constraint=row.get("constraint", ""),
                )
            )

    with Path(choices_path).open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        _require_headers(reader.fieldnames or [], XLSFormWorkbook("", "").choice_headers(), choices_path)
        for row in reader:
            choice_rows.append(
                ChoiceRow(
                    list_name=row.get("list_name", ""),
                    name=row.get("name", ""),
                    label=row.get("label", ""),
                )
            )

    title = Path(survey_path).parent.name or Path(survey_path).stem
    return XLSFormWorkbook(title=title, form_id=title, survey=survey_rows, choices=choice_rows)


def _require_headers(actual: list[str], expected: list[str], path: str) -> None:
    missing = [header for header in expected if header not in actual]
    if missing:
        raise ValueError(f"XLSForm CSV '{path}' is missing required headers: {missing}")
