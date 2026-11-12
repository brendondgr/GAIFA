"""This machine's network, as GAIFA sees it (plan lan-access 1.1).

Opening GAIFA to the network means other devices on the same local network (the Wi-Fi, the wired LAN) may sign
in. "Local" is decided by the connecting device's address, never by a header: a private or link-local address in
the subnet of one of this machine's own network interfaces, or in `[hub.lan] allow`. Container bridges (Docker,
Podman, libvirt) and VPNs (Tailscale, WireGuard) don't count unless `allow` names them: a VPN reaches further than
the room, and containers aren't devices.
"""

from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from typing import Iterable

Net = ipaddress.IPv4Network | ipaddress.IPv6Network
Addr = ipaddress.IPv4Address | ipaddress.IPv6Address

#: interfaces that are not this machine's network: containers, virtual machines, VPNs, loopback
SKIP_PREFIXES = ("lo", "docker", "br-", "veth", "podman", "cni", "virbr", "vnet", "tailscale", "wg", "tun", "tap", "zt", "utun",
                 "flannel", "cali", "lxc", "lxd", "kube", "awdl", "llw", "anpi", "bridge", "ham")


@dataclass(frozen=True)
class Iface:
    name: str
    address: Addr
    network: Net


def _parse(addr: str, mask: str | None) -> tuple[Addr, Net] | None:
    try:
        ip = ipaddress.ip_address(addr.split("%")[0])
        if mask and ":" in mask:                                       # IPv6 masks come as ffff:ffff:…: count the bits
            mask = str(bin(int(ipaddress.IPv6Address(mask))).count("1"))
        net = ipaddress.ip_network(f"{ip}/{mask}" if mask else f"{ip}/{ip.max_prefixlen}", strict=False)
    except ValueError:
        return None
    return ip, net


def interfaces(raw: dict[str, list] | None = None) -> list[Iface]:
    """This machine's own network interfaces with a private or link-local address (psutil's view, or `raw` in tests:
    {name: [(family, address, netmask)]})."""
    if raw is None:
        import psutil

        raw = {n: [(a.family, a.address, a.netmask) for a in addrs] for n, addrs in psutil.net_if_addrs().items()}
    out: list[Iface] = []
    for name, addrs in raw.items():
        if name.lower().startswith(SKIP_PREFIXES):
            continue
        for family, addr, mask in addrs:
            if family not in (socket.AF_INET, socket.AF_INET6):
                continue
            parsed = _parse(addr, mask)
            if parsed and not parsed[0].is_loopback and (parsed[0].is_private or parsed[0].is_link_local):
                out.append(Iface(name, *parsed))
    return out


def networks(allow: Iterable[str] = (), ifaces: list[Iface] | None = None) -> list[Net]:
    nets: list[Net] = [i.network for i in (interfaces() if ifaces is None else ifaces)]
    for cidr in allow:
        nets.append(ipaddress.ip_network(cidr, strict=False))
    return nets


def parse_ip(value: str | None) -> Addr | None:
    if not value:
        return None
    try:
        ip = ipaddress.ip_address(value.split("%")[0].strip("[]"))
    except ValueError:
        return None
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:      # ::ffff:192.168.1.5 from a dual-stack socket
        return ip.ipv4_mapped
    return ip


def is_loopback(value: str | None) -> bool:
    ip = parse_ip(value)
    return ip is not None and ip.is_loopback


def is_local(value: str | None, nets: list[Net]) -> bool:
    """A device on this machine's network (or an allowed one); loopback is not "local" here: it is this machine."""
    ip = parse_ip(value)
    if ip is None or ip.is_loopback or ip.is_multicast or ip.is_unspecified:
        return False
    return any(ip.version == n.version and ip in n for n in nets)


def check_cidr(value: str) -> str:
    """An `allow` entry: a private, link-local or CGNAT (Tailscale's 100.64/10) network, never the internet."""
    net = ipaddress.ip_network(value.strip(), strict=False)
    cgnat = ipaddress.ip_network("100.64.0.0/10")
    ok = (net.version == 4 and net.subnet_of(cgnat)) or net.is_private or net.is_link_local
    if not ok or net.prefixlen < (8 if net.version == 4 else 48):
        raise ValueError(f"{value!r} isn't a local network; GAIFA is never opened to the internet")
    return str(net)


def primary(ifaces: list[Iface] | None = None) -> Addr | None:
    """The address other devices most likely reach this machine at: the one the default route leaves from (a UDP
    connect sends nothing), when it is one of the local interfaces' addresses; else the first IPv4 one."""
    ifaces = interfaces() if ifaces is None else ifaces
    mine = {i.address for i in ifaces}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            ip = ipaddress.ip_address(s.getsockname()[0])
        if ip in mine:
            return ip
    except OSError:
        pass
    v4 = [i.address for i in ifaces if i.address.version == 4]
    return v4[0] if v4 else (ifaces[0].address if ifaces else None)


def names(extra: Iterable[str] = ()) -> list[str]:
    """Host names a device may use: this machine's name and its mDNS `.local` name, and `[hub.lan] names`."""
    host = socket.gethostname().split(".")[0].lower()
    out = [host, f"{host}.local", *(n.lower() for n in extra)]
    return list(dict.fromkeys(n for n in out if n))


def host_names(extra: Iterable[str] = (), ifaces: list[Iface] | None = None) -> set[str]:
    """Every Host a device on the network may send: the names and this machine's addresses."""
    ifaces = interfaces() if ifaces is None else ifaces
    return {*names(extra), *(str(i.address) for i in ifaces)}


def urls(port: int, https_port: int | None = None, extra: Iterable[str] = (), ifaces: list[Iface] | None = None) -> list[str]:
    """What to open on another device, the most likely first."""
    ifaces = interfaces() if ifaces is None else ifaces
    ip = primary(ifaces)
    hosts = [*([str(ip)] if ip else []), *names(extra)[1:]]
    fmt = lambda h: f"[{h}]" if ":" in h else h               # noqa: E731
    out = [f"http://{fmt(h)}:{port}" for h in hosts]
    if https_port:
        out = [f"https://{fmt(h)}:{https_port}" for h in hosts] + out
    return out
