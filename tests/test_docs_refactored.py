import sys
from unittest.mock import MagicMock, patch
import unittest

# This is a bit complex due to the environment issues,
# but I'll try to add a clean test file that follows the project structure
# while handling missing dependencies if run in this restricted environment.

try:
    from wet_mcp.sources.docs import _score_result, _get_registry_tasks, discover_library
    IMPORT_SUCCESS = True
except ImportError:
    IMPORT_SUCCESS = False

class TestDocsRefactored(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        if not IMPORT_SUCCESS:
            self.skipTest("Dependencies not available for direct import")

    def test_score_result_logic(self):
        # Exact name match
        res = {"name": "test-lib", "homepage": "https://example.com"}
        self.assertEqual(_score_result(res, "test-lib"), 10 + 5 + 3)

        # ReadTheDocs boost
        res = {"name": "test-lib", "homepage": "https://testlib.readthedocs.io"}
        # 10 (name) + 5 (hp) + 3 (custom domain) + 3 (name in domain) + 2 (RTD) = 23
        # Wait, netloc is testlib.readthedocs.io.
        # "github.com" not in netloc: True.
        # "docs.rs" or "pkg.go.dev" in netloc: False.
        # score += 3.
        # lib_norm = "testlib".
        # host_norm = "testlibreadthedocsio".
        # lib_norm in host_norm: True -> score += 3.
        # "readthedocs" in netloc: True.
        # subdomain = "testlib".
        # subdomain == lib_norm: True -> score += 2.
        # Total: 10 + 5 + 3 + 3 + 2 = 23.
        self.assertEqual(_score_result(res, "test-lib"), 23)

    async def test_discover_library_well_known_numpy(self):
        res = await discover_library("numpy")
        self.assertEqual(res["registry"], "well_known")
        self.assertIn("numpy.org", res["homepage"])

if __name__ == "__main__":
    unittest.main()
