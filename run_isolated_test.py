import sys
from unittest.mock import patch, MagicMock
sys.modules["web_core"] = MagicMock()
sys.modules["loguru"] = MagicMock()
sys.modules["wet_mcp.sources.docs"] = MagicMock()
import pytest
pytest.main(["tests/test_db.py", "tests/test_docs_coverage.py"])
