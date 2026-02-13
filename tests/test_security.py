import socket
from unittest.mock import patch

from wet_mcp.security import is_safe_url


def test_ssrf_basic():
    # Loopback
    assert not is_safe_url("http://127.0.0.1")
    assert not is_safe_url("http://localhost")
    assert not is_safe_url("http://[::1]")
    assert not is_safe_url("http://0.0.0.0")  # Often resolves to localhost

    # Private IPv4
    assert not is_safe_url("http://192.168.1.100")
    assert not is_safe_url("http://10.0.0.1")
    assert not is_safe_url("http://172.16.5.5")

    # Link-local IPv4
    assert not is_safe_url("http://169.254.169.254")

    # Private/Link-local IPv6 (literals)
    # unique local address (fc00::/7)
    assert not is_safe_url("http://[fc00::1]")
    # link-local address (fe80::/10)
    assert not is_safe_url("http://[fe80::1]")

    # Schemes
    assert not is_safe_url("ftp://example.com")
    assert not is_safe_url("file:///etc/passwd")
    assert not is_safe_url("javascript:alert(1)")

    # With port
    assert not is_safe_url("http://127.0.0.1:8080")
    assert not is_safe_url("http://localhost:5000")


def test_mixed_case_schemes():
    # Mixed case scheme - should be allowed if http/https
    # urlparse lowercases scheme, so Http:// should be valid scheme-wise
    # But we need to mock DNS to make it pass the IP check
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 80))
        ]
        assert is_safe_url("Http://example.com")
        assert is_safe_url("HTTPS://example.com")


def test_ssrf_dns_rebinding_simulation():
    # Simulate a domain resolving to 127.0.0.1
    with patch("socket.getaddrinfo") as mock_dns:
        # Mock return value structure: list of (family, type, proto, canonname, sockaddr)
        # sockaddr is (address, port) for AF_INET
        mock_dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))
        ]

        assert not is_safe_url("http://malicious-rebinding.com")


def test_ssrf_ipv6_dns_rebinding():
    # Simulate a domain resolving to ::1
    with patch("socket.getaddrinfo") as mock_dns:
        mock_dns.return_value = [
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 80, 0, 0))
        ]
        assert not is_safe_url("http://malicious-ipv6.com")


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


def test_malformed_urls():
    assert not is_safe_url("not-a-url")
    assert not is_safe_url("http://")  # No hostname
    # urlparse might handle these differently, ensuring no crash is key
    # http://[invalid-ipv6] usually fails parsing or getaddrinfo
    assert not is_safe_url("http://[invalid-ipv6]")
