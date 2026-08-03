"""Regression checks for the synthetic end-to-end fixture corpus."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from backend.operational import validate_topology_package
from backend.tests.e2e_fixtures.reference_oracle import evaluate_fixture_case


FIXTURE_ROOT = Path(__file__).parent / "e2e_fixtures"
PACKAGE_ROOT = FIXTURE_ROOT / "packages"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _packages() -> list[tuple[Path, dict]]:
    return [(path, _load(path)) for path in sorted(PACKAGE_ROOT.glob("*.json"))]


class TestSyntheticE2EFixtureCorpus(unittest.TestCase):
    def test_common_topology_is_a_valid_deployment_fixture(self):
        topology = _load(FIXTURE_ROOT / "common" / "topology-package.json")
        errors = [
            item
            for item in validate_topology_package(topology, deployment=True)
            if item["severity"] == "error"
        ]
        self.assertEqual(errors, [])

    def test_packages_are_complete_three_page_source_contracts(self):
        packages = _packages()
        self.assertEqual(len(packages), 10)
        expected_statuses = {
            "complete",
            "extension_blocked",
            "setup_blocked",
            "source_blocked",
        }
        for path, package in packages:
            self.assertEqual(package["schema_version"], "1.0", path)
            self.assertIn(package["fixture_status"], expected_statuses, path)
            self.assertEqual(
                [page["page"] for page in package["manual_pages"]],
                [1, 2, 3],
                path,
            )
            for page in package["manual_pages"]:
                self.assertTrue(page["title"].strip(), path)
                self.assertGreaterEqual(len(page["sections"]), 3, path)
                self.assertTrue(all(section.strip() for section in page["sections"]), path)
            self.assertGreaterEqual(len(package["patient_cases"]), 2, path)
            for case in package["patient_cases"]:
                self.assertTrue(case["id"].strip(), path)
                self.assertIn("patient_id", case["inputs"], path)
                self.assertIn("status", case["expected"], path)

    def test_source_oracles_are_independent_of_and_traceable_to_manual_text(self):
        for path, package in _packages():
            manual_text = "\n".join(
                section
                for page in package["manual_pages"]
                for section in page["sections"]
            )
            oracle = package["source_oracle"]
            for quote in oracle["must_include"]:
                self.assertIn(quote, manual_text, f"{path}: missing source oracle quote")
            for forbidden in oracle["must_not_invent"]:
                # A source can explicitly prohibit an output (for example,
                # "do not include a phone number").  The later artifact
                # runner, not a literal source scan, must enforce that the
                # output is absent while preserving the prohibition itself.
                self.assertTrue(forbidden.strip(), path)
            self.assertIn(
                oracle["expected_integration_status"],
                {
                    "eligible_for_artifact_and_behavior_test",
                    "manual_review_required",
                    "setup_validation_blocked",
                    "extension_not_available",
                },
                path,
            )

    def test_function_profile_mix_and_negative_paths_are_explicit(self):
        packages = {package["fixture_id"]: package for _, package in _packages()}
        function_kinds = {package["function_profile"]["kind"] for package in packages.values()}
        self.assertTrue(
            {"native_expression", "topology_lookup", "prompt10_planning", "unsupported_extension"}
            .issubset(function_kinds)
        )
        self.assertEqual(
            packages["exact-calendar-extension"]["source_oracle"]["expected_integration_status"],
            "extension_not_available",
        )
        self.assertEqual(
            packages["missing-chw-identity"]["fixture_status"],
            "setup_blocked",
        )
        self.assertEqual(
            packages["underspecified-responsibility"]["source_oracle"]["required_finding"],
            "underspecified_responsibility",
        )
        self.assertEqual(
            packages["incomplete-threshold"]["source_oracle"]["required_finding"],
            "missing_age_band_threshold",
        )
        self.assertEqual(
            packages["conflicting-disposition"]["source_oracle"]["required_finding"],
            "conflicting_dispositions",
        )

    def test_derived_guides_match_the_three_source_pages(self):
        for package_path, package in _packages():
            derived = package_path.parent / package_path.stem / "guide.json"
            self.assertTrue(derived.exists(), f"Run build_manual_pdfs.py for {package_path.name}")
            guide = _load(derived)
            self.assertEqual(guide["metadata"]["fixture_id"], package["fixture_id"])
            self.assertEqual(guide["metadata"]["page_count"], 3)
            self.assertEqual(set(guide["pages"]), {"1", "2", "3"})
            for page in package["manual_pages"]:
                section = guide["sections"][f"page_{page['page']}"]
                self.assertEqual(section["title"], page["title"])
                self.assertEqual(section["page_start"], page["page"])
                self.assertEqual(section["page_end"], page["page"])

    def test_reference_oracle_matches_every_declared_patient_case(self):
        """Fixtures assert raw-input behavior without precomputed predicates."""
        for path, package in _packages():
            for case in package["patient_cases"]:
                actual = evaluate_fixture_case(package, case["inputs"])
                for field, expected_value in case["expected"].items():
                    if field == "forbidden_outputs":
                        for forbidden in expected_value:
                            self.assertNotIn(forbidden, actual.values(), f"{path}: {case['id']}")
                    else:
                        self.assertEqual(
                            actual.get(field),
                            expected_value,
                            f"{path}: {case['id']} field {field}",
                        )


if __name__ == "__main__":
    unittest.main()
