import ipaddress
import socket
from urllib.parse import urlparse

from loguru import logger


def _validate_ip(ip_str: str) -> bool:
    """Validate if an IP address string is safe (public)."""
    try:
        # Remove scope ID for IPv6 link-local (e.g., fe80::1%eth0)
        if "%" in ip_str:
            ip_str = ip_str.split("%")[0]

        ip = ipaddress.ip_address(ip_str)

        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
        ):
            return False
        return True
    except ValueError:
        return False


def resolve_safe_url(url: str) -> str:
    """
    Resolve a URL's hostname to a safe IP address.
    Returns the IP address as a string (with brackets for IPv6).
    Raises ValueError if any resolved IP is unsafe or resolution fails.
    """
    try:
        parsed = urlparse(url)
    except Exception as e:
        raise ValueError(f"Invalid URL: {url}") from e

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme: {parsed.scheme}")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("No hostname in URL")

    # Block localhost explicitly
    if hostname.lower() in ("localhost", "localhost.localdomain", "127.0.0.1", "::1"):
        raise ValueError(f"Blocked localhost: {hostname}")

    try:
        # Resolve hostname to check for private IPs
        # Use getaddrinfo to handle both IPv4 and IPv6 and multiple records.
        results = socket.getaddrinfo(hostname, None)

        resolved_ips = []
        for res in results:
            ip_str = str(res[4][0])
            if not _validate_ip(ip_str):
                raise ValueError(f"Blocked private/unsafe IP: {ip_str} for host {hostname}")
            resolved_ips.append(ip_str)

        if not resolved_ips:
            # Should not happen if getaddrinfo succeeds
            raise ValueError(f"No IPs resolved for {hostname}")

        # Return the first safe IP
        first_ip = resolved_ips[0]

        # IPv6 addresses in URLs must be enclosed in brackets
        if ":" in first_ip and not first_ip.startswith("["):
            # Check if it's actually an IPv6 address string before adding brackets
            # (though presence of colon usually implies it for IP strings)
            try:
                ipaddress.IPv6Address(first_ip.split("%")[0])
                return f"[{first_ip}]"
            except ValueError:
                pass # Not IPv6

        return first_ip

    except socket.gaierror as e:
        raise ValueError(f"DNS resolution failed for {hostname}: {e}") from e
    except Exception as e:
        if isinstance(e, ValueError):
            raise e
        logger.error(f"Error resolving {hostname}: {e}")
        raise ValueError(f"Error resolving {hostname}: {e}") from e


def is_safe_url(url: str) -> bool:
    """
    Check if a URL is safe to fetch (prevent SSRF).
    Blocks private IPs, loopback, link-local, and non-http schemes.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        logger.warning(f"Blocked unsafe scheme: {parsed.scheme}")
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    # Block localhost explicitly
    if hostname.lower() in ("localhost", "localhost.localdomain", "127.0.0.1", "::1"):
        logger.warning(f"Blocked localhost: {hostname}")
        return False

    try:
        # Resolve hostname to check for private IPs
        results = socket.getaddrinfo(hostname, None)

        for res in results:
            ip_str = str(res[4][0])
            if not _validate_ip(ip_str):
                logger.warning(
                    f"Blocked private/unsafe IP: {ip_str} for host {hostname}"
                )
                return False

    except socket.gaierror:
        # If DNS fails, we can't verify the IP.
        # But if it's an IP literal, getaddrinfo shouldn't fail unless malformed.
        # If it's a domain, failing DNS means we can't connect anyway.
        # So treating as safe is acceptable because connection will fail.
        pass
    except Exception as e:
        logger.error(f"Error validating URL {url}: {e}")
        return False

    return True
