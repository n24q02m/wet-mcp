import ipaddress
import socket
from urllib.parse import urlparse

from loguru import logger


def resolve_safe_url(url: str) -> tuple[str, str, str]:
    """
    Resolve a URL to a safe IP address, preventing DNS rebinding.
    Returns (ip_url, original_hostname, resolved_ip).
    ip_url: The URL with the hostname replaced by the IP (and brackets for IPv6).
    original_hostname: The hostname from the original URL.
    resolved_ip: The IP address string.

    Raises ValueError if unsafe.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL: {url}") from e

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked unsafe scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("No hostname in URL")

    port = parsed.port

    # Block localhost explicitly
    if hostname.lower() in ("localhost", "localhost.localdomain", "127.0.0.1", "::1"):
        raise ValueError(f"Blocked localhost: {hostname}")

    # Resolve
    try:
        # Use getaddrinfo to support IPv4/IPv6
        results = socket.getaddrinfo(
            hostname,
            port or (443 if parsed.scheme == "https" else 80),
            proto=socket.IPPROTO_TCP,
        )
    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for {hostname}") from e

    # Check IPs
    safe_ip = None
    for res in results:
        # res[4] is sockaddr. (ip, port) or (ip, port, flowinfo, scopeid)
        ip_str = res[4][0]

        # Handle IPv6 scope ID
        if "%" in ip_str:
            ip_str = ip_str.split("%")[0]

        try:
            ip_obj = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
        ):
            # Fail immediately if any resolved IP is unsafe (conservative approach)
            raise ValueError(f"Blocked private/unsafe IP: {ip_str} for host {hostname}")

        if safe_ip is None:
            safe_ip = ip_str

    if not safe_ip:
        raise ValueError(f"No valid IP resolved for {hostname}")

    # Construct IP-based URL
    # Need to handle IPv6 brackets
    if ":" in safe_ip:
        netloc = f"[{safe_ip}]"
    else:
        netloc = safe_ip

    if port:
        netloc = f"{netloc}:{port}"

    ip_url = parsed._replace(netloc=netloc).geturl()

    return ip_url, hostname, safe_ip


def is_safe_url(url: str) -> bool:
    """
    Check if a URL is safe to fetch (prevent SSRF).
    Blocks private IPs, loopback, link-local, and non-http schemes.
    """
    try:
        resolve_safe_url(url)
        return True
    except ValueError as e:
        logger.warning(f"Blocked unsafe URL: {e}")
        return False
    except Exception as e:
        logger.error(f"Error validating URL {url}: {e}")
        return False
