"""Classify devices reported by `lpinfo -v` into USB / network / raw-IP
buckets, and derive a human-friendly label plus a stable identity key used by
the healer to recognise "the same printer" across IP/port changes.

This module contains no I/O of its own beyond calling into :mod:`cups_cli`;
every classification function is a pure function of a URI string so it can be
exercised directly in tests with fixture strings instead of a live CUPS.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit

from . import cups_cli

# URI schemes that are inherently self-healing: CUPS/avahi re-resolves the
# host on every print job, so an IP or port change on the printer's side
# never breaks them.
SELF_HEALING_SCHEMES = {"dnssd", "usb"}

# Schemes that pin a raw IP address and therefore need the healer's help.
IP_PINNED_SCHEMES = {"ipp", "ipps", "socket", "lpd", "http", "https"}


@dataclass
class DiscoveredPrinter:
    uri: str
    scheme: str
    category: str  # "usb" | "network-mdns" | "network-ip" | "other"
    label: str
    identity_key: str
    host: str = ""
    port: int | None = None


def _usb_label_and_key(uri: str) -> tuple[str, str]:
    # usb://EPSON/L3150%20Series?serial=581234&interface=1
    """
    Builds a human-readable label and stable identity key from a USB printer URI.
    
    Parameters:
        uri (str): USB printer URI containing make/model information and an optional serial number.
    
    Returns:
        tuple[str, str]: The printer label and identity key.
    """
    parts = urlsplit(uri)
    make_model = unquote(parts.netloc + parts.path).strip("/").replace("/", " ")
    query = parse_qs(parts.query)
    serial = (query.get("serial") or [""])[0]
    label = make_model or "USB device"
    key = f"usb:{make_model.lower()}:{serial}" if serial else f"usb:{make_model.lower()}"
    return label, key


def _dnssd_label_and_key(uri: str) -> tuple[str, str]:
    # dnssd://Brother%20HL-2270DW._ipp._tcp.local/?uuid=...
    """
    Derive a human-readable label and stable identity key from an mDNS printer URI.
    
    Parameters:
        uri (str): The mDNS printer URI.
    
    Returns:
        tuple[str, str]: The printer label and identity key.
    """
    parts = urlsplit(uri)
    instance = unquote(parts.netloc)
    query = parse_qs(parts.query)
    uuid = (query.get("uuid") or [""])[0]
    label = instance.split("._", 1)[0] or "Network printer (mDNS)"
    key = f"dnssd:{uuid}" if uuid else f"dnssd:{instance.lower()}"
    return label, key


def _ip_label_and_key(uri: str) -> tuple[str, str, str, int | None]:
    # ipp://192.168.1.50:631/ipp/print , socket://192.168.1.50:9100
    """
    Build a connection label and stable identity key from an IP-based printer URI.
    
    Parameters:
    	uri (str): IP-based printer URI to parse.
    
    Returns:
    	tuple[str, str, str, int | None]: The connection label, identity key, host, and optional port.
    """
    parts = urlsplit(uri)
    host = parts.hostname or ""
    port = parts.port
    path = parts.path or ""
    label = f"{host}:{port}{path}" if port else f"{host}{path}"
    # Identity key deliberately excludes host so the healer can recognise the
    # "same" printer after its IP changes; it keys on scheme + resource path,
    # which for most printers (and for CUPS's own driverless queues) is
    # stable across DHCP lease changes.
    key = f"ip:{parts.scheme}:{path or '/'}"
    return label, key, host, port


def classify(uri: str) -> DiscoveredPrinter | None:
    """
    Classify a printer URI and derive its discovery metadata.
    
    Parameters:
    	uri (str): Printer device URI to classify.
    
    Returns:
    	DiscoveredPrinter | None: Printer metadata for the URI, or `None` if the URI has no scheme.
    """
    if ":" not in uri:
        return None
    scheme = uri.split(":", 1)[0]
    if scheme == "usb":
        label, key = _usb_label_and_key(uri)
        return DiscoveredPrinter(uri=uri, scheme=scheme, category="usb", label=label, identity_key=key)
    if scheme == "dnssd":
        label, key = _dnssd_label_and_key(uri)
        return DiscoveredPrinter(uri=uri, scheme=scheme, category="network-mdns", label=label, identity_key=key)
    if scheme in IP_PINNED_SCHEMES:
        label, key, host, port = _ip_label_and_key(uri)
        return DiscoveredPrinter(
            uri=uri, scheme=scheme, category="network-ip", label=label, identity_key=key, host=host, port=port
        )
    if scheme in ("serial", "parallel"):
        return DiscoveredPrinter(uri=uri, scheme=scheme, category="usb", label=uri, identity_key=f"other:{uri}")
    return DiscoveredPrinter(uri=uri, scheme=scheme, category="other", label=uri, identity_key=f"other:{uri}")


def discover_all() -> list[DiscoveredPrinter]:
    """
    Discover and classify all printer devices reported by CUPS.
    
    Returns:
    	list[DiscoveredPrinter]: Classified devices with valid supported URIs.
    """
    devices = cups_cli.lpinfo_devices()
    result = []
    for device in devices:
        classified = classify(device.uri)
        if classified is not None:
            result.append(classified)
    return result


_SANITIZE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def suggest_queue_name(label: str) -> str:
    """
    Convert a human-readable printer label into a CUPS-compatible queue name.
    
    Parameters:
        label (str): Human-readable printer label.
    
    Returns:
        str: Sanitized queue name, or ``"printer"`` when the label contains no usable characters.
    """
    name = _SANITIZE_RE.sub("-", label).strip("-")
    return name or "printer"


def list_remote_server_printers(server: str) -> list[DiscoveredPrinter]:
    """
    List printers shared by a remote CUPS server.
    
    Parameters:
    	server (str): The hostname or address of the remote CUPS server.
    
    Returns:
    	list[DiscoveredPrinter]: Discovered printers exposed by the server.
    """
    names = cups_cli.list_remote_printers(server)
    result = []
    for name in names:
        uri = f"ipp://{server}/printers/{name}"
        result.append(
            DiscoveredPrinter(
                uri=uri,
                scheme="ipp",
                category="remote-cups",
                label=f"{name} @ {server}",
                identity_key=f"remote-cups:{server}:{name}",
                host=server.split(":", 1)[0],
            )
        )
    return result
