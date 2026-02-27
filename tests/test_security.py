import socket
from unittest.mock import patch

from wet_mcp.security import is_safe_url


def test_ssrf_basic():
    # Loopback
    assert not is_safe_url("http://127.0.0.1")
    assert not is_safe_url("http://localhost")
    assert not is_safe_url("http://[::1]")

    # Private
    assert not is_safe_url("http://192.168.1.100")
    assert not is_safe_url("http://10.0.0.1")
    assert not is_safe_url("http://172.16.5.5")

    # Link-local
    assert not is_safe_url("http://169.254.169.254")

    # Schemes
    assert not is_safe_url("ftp://example.com")
    assert not is_safe_url("file:///etc/passwd")

    # With port
    assert not is_safe_url("http://127.0.0.1:8080")
    assert not is_safe_url("http://localhost:5000")


def test_ssrf_dns_rebinding_simulation():
    # Simulate a domain resolving to 127.0.0.1
    with patch("socket.getaddrinfo") as mock_dns:
        # Mock return value structure: list of (family, type, proto, canonname, sockaddr)
        # sockaddr is (address, port) for AF_INET
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]

        assert not is_safe_url("http://malicious-rebinding.com")


def test_safe_urls():
    # Should allow normal domains (mocking DNS to public IP)
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))
        ]
        assert is_safe_url("http://google.com")
        assert is_safe_url("https://example.com/path?q=1")


def test_dns_failure_fallback():
    # If DNS fails, we allow it (connection will fail anyway)
    with patch("socket.getaddrinfo", side_effect=socket.gaierror):
        assert is_safe_url("http://non-existent-domain.com")

def test_extended_ssrf_scenarios():
    """Test additional SSRF scenarios including IPv6 ULA, 0.0.0.0, and mixed-case schemes."""

    # 1. IPv6 Unique Local Address (ULA) - fc00::/7
    # Mock getaddrinfo to return a ULA address
    with patch("socket.getaddrinfo") as mock_dns:
        # Mock IPv6 return: (family, type, proto, canonname, sockaddr)
        # sockaddr for AF_INET6 is (address, port, flowinfo, scopeid)
        mock_dns.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fc00::1", 80, 0, 0))
        ]
        # Note: We use a domain that resolves to ULA, or literal if supported.
        # If we use literal [fc00::1], is_safe_url parses it.
        # But getaddrinfo might be called with the literal.
        assert not is_safe_url("http://[fc00::1]")

    # 2. 0.0.0.0 (Reserved / Current Network)
    # Mock getaddrinfo to return 0.0.0.0
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("0.0.0.0", 80))
        ]
        assert not is_safe_url("http://0.0.0.0")

    # 3. Mixed-case schemes
    # is_safe_url implementation: if parsed.scheme not in ("http", "https"): return False
    # urlparse converts scheme to lowercase, so "HtTp" becomes "http".
    # We need to verify if is_safe_url handles this correctly.
    # We'll mock getaddrinfo to return a safe IP so only the scheme check matters.
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))
        ]
        assert is_safe_url("HtTp://example.com")
        assert is_safe_url("HttPS://example.com")

    # 4. Link-local with scope ID
    # Mock getaddrinfo to return an IPv6 link-local address with scope ID
    # The code splits by '%' so it should handle it.
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fe80::1%eth0", 80, 0, 0))
        ]
        assert not is_safe_url("http://[fe80::1%eth0]")

    # 5. Mixed-case localhost
    # "LoCaLhOsT" -> blocked by hostname.lower() check
    assert not is_safe_url("http://LoCaLhOsT")
