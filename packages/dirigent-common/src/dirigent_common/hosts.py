"""What a host name says about where it reaches."""

import ipaddress


def is_loopback_host(host: str) -> bool:
    """Whether a host names this machine alone: ``localhost`` or a loopback address, and nothing else."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
