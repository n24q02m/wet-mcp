"""Unit tests for _get_pip_command in searxng_runner."""

import sys
from unittest.mock import patch
import pytest
from wet_mcp.searxng_runner import _get_pip_command

@patch("shutil.which")
@patch("sys.executable", "/usr/bin/python3")
def test_get_pip_command_uv(mock_which):
    """Test uv pip selection when uv is available."""
    def which_side_effect(name):
        if name == "uv":
            return "/path/to/uv"
        return None

    mock_which.side_effect = which_side_effect

    cmd = _get_pip_command()
    assert cmd == ["/path/to/uv", "pip", "install", "--python", "/usr/bin/python3"]

@patch("shutil.which")
@patch("sys.executable", "/usr/bin/python3")
def test_get_pip_command_pip(mock_which):
    """Test pip selection when uv is missing but pip is available."""
    def which_side_effect(name):
        if name == "pip":
            return "/path/to/pip"
        return None

    mock_which.side_effect = which_side_effect

    cmd = _get_pip_command()
    assert cmd == ["/path/to/pip", "install"]

@patch("shutil.which")
@patch("sys.executable", "/usr/bin/python3")
def test_get_pip_command_fallback(mock_which):
    """Test fallback to python -m pip when both uv and pip are missing."""
    mock_which.return_value = None

    cmd = _get_pip_command()
    assert cmd == ["/usr/bin/python3", "-m", "pip", "install"]
