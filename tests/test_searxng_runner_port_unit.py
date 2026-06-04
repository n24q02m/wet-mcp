from unittest.mock import MagicMock, patch

import pytest

from wet_mcp.searxng_runner import _find_available_port


def test_find_available_port_success_first_try():
    """Test that the function returns the first port it successfully binds to."""
    with (
        patch("socket.socket") as mock_socket,
        patch("random.shuffle", side_effect=lambda x: x),
    ):  # Keep order deterministic for test
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock

        # Success on first try
        mock_sock.bind.return_value = None

        port = _find_available_port(8000, max_tries=10)

        assert port == 8000
        mock_sock.bind.assert_called_once_with(("127.0.0.1", 8000))


def test_find_available_port_success_after_failures():
    """Test that the function tries multiple ports until it finds an available one."""
    with (
        patch("socket.socket") as mock_socket,
        patch("random.shuffle", side_effect=lambda x: x),
    ):  # Keep order: 8000, 8001, 8002...
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock

        # Fail on 8000 and 8001, succeed on 8002
        mock_sock.bind.side_effect = [
            OSError("Address in use"),
            OSError("Address in use"),
            None,
        ]

        port = _find_available_port(8000, max_tries=10)

        assert port == 8002
        assert mock_sock.bind.call_count == 3
        mock_sock.bind.assert_any_call(("127.0.0.1", 8000))
        mock_sock.bind.assert_any_call(("127.0.0.1", 8001))
        mock_sock.bind.assert_any_call(("127.0.0.1", 8002))


def test_find_available_port_exhaustion():
    """Test that the function raises RuntimeError when all ports are in use."""
    max_tries = 5
    with (
        patch("socket.socket") as mock_socket,
        patch("random.shuffle", side_effect=lambda x: x),
    ):
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock

        # Always fail
        mock_sock.bind.side_effect = OSError("Address in use")

        with pytest.raises(
            RuntimeError, match="No available port found in range 8000-8004"
        ):
            _find_available_port(8000, max_tries=max_tries)

        assert mock_sock.bind.call_count == max_tries


def test_find_available_port_randomization():
    """Verify that the function randomizes the search order."""
    start_port = 8000
    max_tries = 10

    # We want to see that random.shuffle is called with the offsets
    with patch("socket.socket") as mock_socket, patch("random.shuffle") as mock_shuffle:
        mock_sock = MagicMock()
        mock_socket.return_value.__enter__.return_value = mock_sock

        # Define a specific shuffled order: index 2 first (8002)
        def mock_shuffle_impl(offsets):
            offsets[0], offsets[2] = offsets[2], offsets[0]

        mock_shuffle.side_effect = mock_shuffle_impl
        mock_sock.bind.return_value = None

        port = _find_available_port(start_port, max_tries=max_tries)

        # It should have tried the first element of the shuffled offsets
        assert port == start_port + 2
        mock_shuffle.assert_called_once()
        # Verify the list passed to shuffle was [0, 1, ..., 9]
        shuffled_list = mock_shuffle.call_args[0][0]
        assert sorted(shuffled_list) == list(range(max_tries))
