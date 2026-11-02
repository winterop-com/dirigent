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


def counted_as(host: str) -> str:
    """What a count of one machine is keyed on: an address, or for IPv6 the /64 one host is usually handed whole."""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is None:
        return str(ipaddress.ip_network(f"{address}/64", strict=False))
    return str(address.ipv4_mapped if isinstance(address, ipaddress.IPv6Address) else address)
