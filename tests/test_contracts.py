from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_schema_ids_are_versioned_and_unique(self) -> None:
        schema_ids: list[str] = []
        for path in sorted((ROOT / "contracts").glob("*.schema.json")):
            schema = json.loads(path.read_text(encoding="utf-8"))
            schema_ids.append(schema["$id"])
            self.assertRegex(schema["$id"], r"/v[0-9]+$")
            self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")

        self.assertGreaterEqual(len(schema_ids), 4)
        self.assertEqual(len(schema_ids), len(set(schema_ids)))


if __name__ == "__main__":
    unittest.main()
