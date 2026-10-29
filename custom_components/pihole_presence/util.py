"""Input normalization shared by setup and the configuration flows."""

from __future__ import annotations

import ipaddress

from yarl import URL


def normalize_host(value: str) -> str:
    """Accept a host or web UI URL, preserving any reverse proxy prefix."""
    value = value.strip()
    if not value:
        raise ValueError("Enter the Pi-hole host or URL")
    if "://" not in value:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            pass
        else:
            if address.version == 6:
                value = f"[{address}]"
        value = f"http://{value}"
    try:
        url = URL(value)
        if (
            url.scheme not in ("http", "https")
            or not url.host
            or any(char.isspace() for char in url.host)
            or url.user is not None
            or url.password is not None
        ):
            raise ValueError
        # Accessing port validates malformed/out-of-range port numbers too.
        _ = url.port
    except (ValueError, TypeError) as err:
        raise ValueError(
            "Enter an HTTP or HTTPS URL without embedded credentials"
        ) from err
    path = url.path.rstrip("/")
    for suffix in ("/admin/index.php", "/admin", "/api"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return str(url.with_path(path).with_query(None).with_fragment(None)).rstrip("/")
