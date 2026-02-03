"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture
def sample_url():
    """Sample URL for testing."""
    return "https://example.com"


@pytest.fixture
def sample_query():
    """Sample search query."""
    return "test query"
