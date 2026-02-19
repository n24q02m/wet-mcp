import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

from loguru import logger


def is_safe_path(path: str | Path, allowed_dirs: list[str | Path]) -> bool:
    """
    Check if a path is safe (within allowed directories).
    Prevents path traversal attacks.
    """
    try:
        # Resolve path to absolute, handling symlinks and ..
        # Note: strict=False allows checking paths that don't exist yet (for writes)
        # But for writes, we want to ensure the parent exists or is safe.
        # However, .resolve() on a non-existent file works as long as the directory exists?
        # No, pathlib.Path.resolve() on non-existent path behavior depends on python version.
        # In 3.10+, .resolve() works even if file doesn't exist (on Windows it might be strict by default prior to 3.10?).
        # Wait, in 3.10 resolve() is strict=False by default.
        # We are targeting 3.12+.

        target_path = Path(path).expanduser().resolve()
    except Exception as e:
        logger.warning(f"Error resolving path {path}: {e}")
        return False

    for allowed in allowed_dirs:
        try:
            allowed_path = Path(allowed).expanduser().resolve()
            # Check if target_path is allowed_path or inside it
            if target_path == allowed_path or allowed_path in target_path.parents:
                return True
        except Exception:
            continue

    logger.warning(f"Blocked unsafe path access: {target_path}")
    return False


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
