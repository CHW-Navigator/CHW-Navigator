from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chw_navigator.clinical_ir import ClinicalIRDocument
from chw_navigator.dmn import DMNImportError, import_dmn_decisions
from test_support import create_test_run, reset_suite_runs


EXAMPLES = ROOT / "examples"


class DmnFailLoudTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        reset_suite_runs("dmn_fail_loud")

    def setUp(self) -> None:
        self.base_document = _load_document(EXAMPLES / "pneumonia.ir.json")
        self.good_dmn = (EXAMPLES / "pneumonia.dmn").read_text(encoding="utf-8")
        self.test_run = create_test_run(
            suite_name="dmn_fail_loud",
            test_name=self.id().split(".")[-1],
            purpose="Negative DMN importer tests that verify unsupported or unsafe DMN inputs fail loudly.",
            input_paths=(EXAMPLES / "pneumonia.ir.json", EXAMPLES / "pneumonia.dmn", EXAMPLES / "state_prefix.ir.json"),
        )

    def test_rejects_missing_decision_table(self) -> None:
        self._assert_import_fails(
            self.good_dmn.replace("<decisionTable hitPolicy=\"FIRST\">", "<decisionContext>")
            .replace("</decisionTable>", "</decisionContext>"),
            "decisionTable",
        )

    def test_rejects_unsupported_hit_policy(self) -> None:
        self._assert_import_fails(
            self.good_dmn.replace('hitPolicy="FIRST"', 'hitPolicy="COLLECT"'),
            "unsupported hit policy",
        )

    def test_rejects_missing_input_expression(self) -> None:
        broken = self.good_dmn.replace(
            """<input id="input_danger">
        <inputExpression id="ie_danger" typeRef="boolean">
          <text>p_danger_sign</text>
        </inputExpression>
      </input>""",
            '<input id="input_danger"></input>',
        )
        self._assert_import_fails(broken, "missing inputExpression")

    def test_rejects_unsupported_input_expression(self) -> None:
        self._assert_import_fails(
            self.good_dmn.replace("<text>p_danger_sign</text>", "<text>p_danger_sign and p_fast_breathing</text>", 1),
            "unsupported DMN input expression",
        )

    def test_rejects_missing_input_prefix(self) -> None:
        self._assert_import_fails(
            self.good_dmn.replace("<text>p_danger_sign</text>", "<text>danger_sign</text>", 1),
            "explicit v_/st_/p_/o_ prefix",
        )

    def test_rejects_missing_output_identifier(self) -> None:
        broken = self.good_dmn.replace(
            '<output id="out_referral" name="o_referral" typeRef="boolean" />',
            '<output typeRef="boolean" />',
        )
        self._assert_import_fails(broken, "missing a usable identifier")

    def test_rejects_invalid_output_prefix(self) -> None:
        self._assert_import_fails(
            self.good_dmn.replace('name="o_referral"', 'name="referral"'),
            "explicit o_ prefix",
        )

    def test_rejects_mismatched_input_count(self) -> None:
        broken = self.good_dmn.replace(
            '<inputEntry id="r1_i2"><text>-</text></inputEntry>\n',
            "",
            1,
        )
        self._assert_import_fails(broken, "input entries")

    def test_rejects_mismatched_output_count(self) -> None:
        broken = self.good_dmn.replace(
            '<outputEntry id="r1_o3"><text>false</text></outputEntry>\n',
            "",
            1,
        )
        self._assert_import_fails(broken, "output entries")

    def test_rejects_unsupported_input_cell(self) -> None:
        self._assert_import_fails(
            self.good_dmn.replace("<text>true</text>", "<text>>= 50</text>", 1),
            "supported values are true, false, and -",
        )

    def test_rejects_unsupported_output_expression(self) -> None:
        self._assert_import_fails(
            self.good_dmn.replace(
                '<outputEntry id="r1_o1"><text>true</text></outputEntry>',
                '<outputEntry id="r1_o1"><text>1 + 2</text></outputEntry>',
            ),
            "unsupported DMN output cell",
        )

    def test_rejects_unsafe_dtd_xml(self) -> None:
        dangerous = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [ <!ELEMENT foo ANY > <!ENTITY xxe SYSTEM "file:///etc/passwd" > ]>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="defs_pneumonia" name="pneumonia">
  <decision id="d_triage" name="Triage">
    <decisionTable hitPolicy="FIRST">
      <input id="input_danger">
        <inputExpression id="ie_danger" typeRef="boolean">
          <text>p_danger_sign</text>
        </inputExpression>
      </input>
      <output id="out_referral" name="o_referral" typeRef="boolean" />
      <rule id="r1">
        <inputEntry id="r1_i1"><text>true</text></inputEntry>
        <outputEntry id="r1_o1"><text>true</text></outputEntry>
      </rule>
      <rule id="r2">
        <inputEntry id="r2_i1"><text>-</text></inputEntry>
        <outputEntry id="r2_o1"><text>false</text></outputEntry>
      </rule>
    </decisionTable>
  </decision>
</definitions>
"""
        self._assert_import_fails(dangerous, "unsafe or invalid DMN XML")

    def test_accepts_state_variable_prefix_in_input_expression(self) -> None:
        stateful_document = _load_document(EXAMPLES / "state_prefix.ir.json")
        dmn_text = """<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="https://www.omg.org/spec/DMN/20191111/MODEL/" id="defs_stateful" name="stateful">
  <decision id="d_state_router" name="State Router">
    <decisionTable hitPolicy="FIRST">
      <input id="input_state_done">
        <inputExpression id="ie_state_done" typeRef="boolean">
          <text>st_fever_done</text>
        </inputExpression>
      </input>
      <output id="out_seen" name="o_seen_before" typeRef="boolean" />
      <rule id="r_seen_yes">
        <inputEntry id="r_seen_yes_i1"><text>true</text></inputEntry>
        <outputEntry id="r_seen_yes_o1"><text>true</text></outputEntry>
      </rule>
      <rule id="r_seen_else">
        <inputEntry id="r_seen_else_i1"><text>-</text></inputEntry>
        <outputEntry id="r_seen_else_o1"><text>false</text></outputEntry>
      </rule>
    </decisionTable>
  </decision>
</definitions>
"""
        path = self.test_run.outputs_dir / "state_input_ok.dmn"
        path.write_text(dmn_text, encoding="utf-8")

        imported = import_dmn_decisions(stateful_document, str(path))
        self.assertIn("d_state_router", imported.decisions)
        self.assertEqual("r_seen_yes", imported.decisions["d_state_router"].rules[0].id)

    def _assert_import_fails(self, dmn_text: str, expected_message: str) -> None:
        path = self.test_run.outputs_dir / "bad_input.dmn"
        path.write_text(dmn_text, encoding="utf-8")
        with self.assertRaises(DMNImportError) as ctx:
            import_dmn_decisions(self.base_document, str(path))
        self.assertIn(expected_message, str(ctx.exception))


def _load_document(path: Path) -> ClinicalIRDocument:
    return ClinicalIRDocument.from_dict(json.loads(path.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
