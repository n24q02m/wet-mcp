from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.sync.gdrive import check_health


@pytest.mark.asyncio
class TestGDriveHealth:
    """Tests for check_health function in gdrive.py."""

    @patch("wet_mcp.sync.gdrive._get_valid_token")
    async def test_check_health_no_token(self, mock_get_token):
        """Test check_health when no token is available."""
        mock_get_token.return_value = None
        assert await check_health() is False

    @patch("wet_mcp.sync.gdrive._get_valid_token")
    @patch("wet_mcp.sync.gdrive._drive_request")
    async def test_check_health_success(self, mock_request, mock_get_token):
        """Test check_health when API returns 200."""
        mock_get_token.return_value = {"access_token": "valid_token"}
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_request.return_value = mock_response

        assert await check_health() is True

    @patch("wet_mcp.sync.gdrive._get_valid_token")
    @patch("wet_mcp.sync.gdrive._drive_request")
    async def test_check_health_failure_status(self, mock_request, mock_get_token):
        """Test check_health when API returns non-200."""
        mock_get_token.return_value = {"access_token": "valid_token"}
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_request.return_value = mock_response

        assert await check_health() is False

    @patch("wet_mcp.sync.gdrive._get_valid_token")
    @patch("wet_mcp.sync.gdrive._drive_request")
    async def test_check_health_exception(self, mock_request, mock_get_token):
        """Test check_health when _drive_request raises an exception."""
        mock_get_token.return_value = {"access_token": "valid_token"}
        mock_request.side_effect = Exception("API error")

        # This covers the 'except Exception:' block in check_health
        assert await check_health() is False
