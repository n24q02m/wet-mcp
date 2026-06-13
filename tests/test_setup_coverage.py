from unittest.mock import patch

from wet_mcp.setup import (
    _find_searx_package_dir,
    patch_searxng_version,
    patch_searxng_windows,
)


def test_find_searx_package_dir_exception_coverage():
    """Ensure _find_searx_package_dir returns None on Exception."""
    with patch("importlib.util.find_spec", side_effect=Exception("mocked error")):
        assert _find_searx_package_dir() is None


def test_find_searx_package_dir_attribute_error_coverage():
    """Ensure _find_searx_package_dir returns None on AttributeError when accessing spec."""

    class BadSpec:
        @property
        def submodule_search_locations(self):
            raise AttributeError("mocked error")

    with patch("importlib.util.find_spec", return_value=BadSpec()):
        assert _find_searx_package_dir() is None


def test_patch_searxng_windows_exception_coverage():
    """Ensure patch_searxng_windows catches and logs exceptions."""
    with patch("platform.system", return_value="Windows"):
        with patch(
            "wet_mcp.setup._find_searx_package_dir",
            side_effect=Exception("mocked error"),
        ):
            # Should not raise
            patch_searxng_windows()


def test_patch_searxng_version_exception_coverage():
    """Ensure patch_searxng_version catches and logs exceptions."""
    with patch(
        "wet_mcp.setup._find_searx_package_dir", side_effect=Exception("mocked error")
    ):
        # Should not raise
        patch_searxng_version()
