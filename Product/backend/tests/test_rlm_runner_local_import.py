"""Regression guard for local Gen 8 artifact runs without a generated database client."""

from __future__ import annotations

import unittest


class TestRlmRunnerLocalImport(unittest.TestCase):
    def test_import_does_not_require_generated_prisma_client(self):
        # The local fixture pipeline writes artifacts to disk.  Importing its
        # RLM helper must not require the production Prisma client to have
        # been generated; a later best-effort persistence attempt may do so.
        import backend.rlm_runner as rlm_runner

        self.assertTrue(callable(rlm_runner._set_gen7_cached_context))


if __name__ == "__main__":
    unittest.main()
