from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Prompt12ADeadDeclarationTests(unittest.TestCase):
    def test_dead_implementation_checksum_contract_is_not_introduced(self) -> None:
        authoritative_roots = (ROOT / "src", ROOT / "contracts")
        occurrences: list[str] = []
        forbidden = "implementation" + "Checksum"
        for authoritative_root in authoritative_roots:
            for path in authoritative_root.rglob("*"):
                if path.is_file() and path.suffix.lower() in {".py", ".json", ".md"}:
                    if forbidden in path.read_text(encoding="utf-8"):
                        occurrences.append(str(path.relative_to(ROOT)))
        self.assertEqual([], occurrences)


if __name__ == "__main__":
    unittest.main()
