import ipaddress
import socket
from urllib.parse import urlparse

from loguru import logger


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
        # This resolves DNS, which is necessary to detect if a domain points to a private IP.
        # Use getaddrinfo to handle both IPv4 and IPv6 and multiple records.
        # We only need the address.
        results = socket.getaddrinfo(hostname, None)

        for res in results:
            ip_str = res[4][0]
            try:
                # Remove scope ID for IPv6 link-local (e.g., fe80::1%eth0)
                if "%" in ip_str:
                    ip_str = ip_str.split("%")[0]

                ip = ipaddress.ip_address(ip_str)

                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
                    logger.warning(f"Blocked private/unsafe IP: {ip} for host {hostname}")
                    return False
            except ValueError:
                continue

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
