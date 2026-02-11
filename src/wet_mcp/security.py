import ipaddress
import socket
from pathlib import Path
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
            ip_str = str(res[4][0])
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
                    logger.warning(
                        f"Blocked private/unsafe IP: {ip} for host {hostname}"
                    )
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


def is_safe_path(path: str | Path, allowed_dirs: list[str | Path]) -> bool:
    """
    Check if a path is within one of the allowed directories.
    Resolves symlinks and ensures no traversal.
    """
    try:
        # Resolve resolves symlinks and '..' components
        # Note: In Python < 3.10, resolve() might fail if file doesn't exist
        # and strict=True (default False). Here we rely on default loose behavior.
        # But for security checks on paths we intend to create, we often check the parent.
        # If 'path' is intended to be created, check if its parent is safe?
        # But download_media constructs full path. If filename is '..', path is 'dir/..'.
        # Resolve makes it 'parent_of_dir'.
        # is_relative_to('dir') will be False. So it works.

        path_obj = Path(path).resolve()
        allowed = [Path(d).expanduser().resolve() for d in allowed_dirs]

        for d in allowed:
            if path_obj.is_relative_to(d):
                return True

        logger.warning(f"Blocked unsafe path access: {path}")
        return False

    except Exception as e:
        logger.error(f"Error validating path {path}: {e}")
        return False
