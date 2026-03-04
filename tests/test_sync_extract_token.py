"""Tests for _extract_token in sync module."""

from wet_mcp.sync import _extract_token


def test_extract_token_valid():
    """Test extracting a valid token from rclone authorize output."""
    output = (
        "Paste the following into your remote machine config\n"
        "--------------------\n"
        '{"access_token":"abc123","token_type":"Bearer"}\n'
        "--------------------\n"
    )
    result = _extract_token(output)
    assert result == '{"access_token":"abc123","token_type":"Bearer"}'


def test_extract_token_no_token():
    """Test with output that has no token."""
    output = "Some random rclone output\nwithout any token"
    result = _extract_token(output)
    assert result is None


def test_extract_token_empty_string():
    """Test with an empty string."""
    result = _extract_token("")
    assert result is None


def test_extract_token_fallback_no_markers():
    """Test fallback regex when dashed markers are absent."""
    output = 'Some prefix {"access_token":"xyz","token_type":"Bearer"} some suffix'
    result = _extract_token(output)
    assert result == '{"access_token":"xyz","token_type":"Bearer"}'
