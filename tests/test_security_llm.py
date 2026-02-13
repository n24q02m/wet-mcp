"""Security tests for LLM integration."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.config import settings
from wet_mcp.llm import analyze_media


@pytest.fixture
def mock_settings(tmp_path):
    """Mock settings with a safe download directory."""
    original_keys = settings.api_keys
    original_download_dir = settings.download_dir

    settings.api_keys = "provider:key"
    safe_dir = tmp_path / "safe_downloads"
    safe_dir.mkdir()
    settings.download_dir = str(safe_dir)

    yield

    settings.api_keys = original_keys
    settings.download_dir = original_download_dir


@patch("wet_mcp.llm.acompletion")
def test_analyze_media_path_traversal(mock_completion, mock_settings, tmp_path):
    """Test that analyze_media blocks access to files outside download_dir."""
    # Create a file outside the safe directory
    secret_file = tmp_path / "secret.txt"
    secret_file.write_text("SUPER_SECRET_DATA")

    # Attempt to analyze it
    result = asyncio.run(analyze_media(str(secret_file)))

    # Expect access denied error
    assert "Error: Access denied" in result

    # Ensure acompletion was NOT called for the unsafe file
    # Note: mock_completion might be called later for safe file, so check call history carefully if needed
    # But here we just check if result is error, implying it returned early.

    # Verify safe file works
    safe_file = Path(settings.download_dir) / "safe.txt"
    safe_file.write_text("Safe content")

    mock_response = MagicMock()
    mock_response.choices[0].message.content = "Analysis complete"
    mock_completion.return_value = mock_response

    result = asyncio.run(analyze_media(str(safe_file)))
    assert result == "Analysis complete"
