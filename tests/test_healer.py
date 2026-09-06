from linuxprint.cups_cli import Printer
from linuxprint.discovery import DiscoveredPrinter
from linuxprint.healer import plan_repairs
from linuxprint.identity import IdentityRecord


def test_plan_repairs_fixes_drifted_ip_printer():
    installed = {
        "Office_Printer": Printer(name="Office_Printer", uri="ipp://192.168.1.50:631/ipp/print"),
    }
    discovered = [
        DiscoveredPrinter(
            uri="ipp://192.168.1.99:631/ipp/print",
            scheme="ipp",
            category="network-ip",
            label="192.168.1.99:631/ipp/print",
            identity_key="ip:ipp:/ipp/print",
            host="192.168.1.99",
            port=631,
        )
    ]
    identities = {
        "Office_Printer": IdentityRecord(
            identity_key="ip:ipp:/ipp/print",
            category="network-ip",
            added_uri="ipp://192.168.1.50:631/ipp/print",
            added_at=0.0,
        )
    }
    repairs = plan_repairs(installed, discovered, identities)
    assert len(repairs) == 1
    assert repairs[0].printer_name == "Office_Printer"
    assert repairs[0].new_uri == "ipp://192.168.1.99:631/ipp/print"


def test_plan_repairs_skips_dnssd_and_usb_schemes():
    installed = {
        "Bonjour_Printer": Printer(name="Bonjour_Printer", uri="dnssd://Brother._ipp._tcp.local/?uuid=abc"),
        "Usb_Printer": Printer(name="Usb_Printer", uri="usb://EPSON/L3150?serial=1"),
    }
    discovered = [
        DiscoveredPrinter(
            uri="dnssd://Brother._ipp._tcp.local/?uuid=abc-new",
            scheme="dnssd",
            category="network-mdns",
            label="Brother",
            identity_key="dnssd:abc",
        )
    ]
    identities = {
        "Bonjour_Printer": IdentityRecord("dnssd:abc", "network-mdns", "dnssd://old", 0.0),
        "Usb_Printer": IdentityRecord("usb:epson l3150:1", "usb", "usb://old", 0.0),
    }
    assert plan_repairs(installed, discovered, identities) == []


def test_plan_repairs_no_op_when_uri_unchanged():
    installed = {"P": Printer(name="P", uri="ipp://192.168.1.50:631/ipp/print")}
    discovered = [
        DiscoveredPrinter(
            uri="ipp://192.168.1.50:631/ipp/print",
            scheme="ipp",
            category="network-ip",
            label="x",
            identity_key="ip:ipp:/ipp/print",
            host="192.168.1.50",
            port=631,
        )
    ]
    identities = {"P": IdentityRecord("ip:ipp:/ipp/print", "network-ip", "ipp://192.168.1.50:631/ipp/print", 0.0)}
    assert plan_repairs(installed, discovered, identities) == []


def test_plan_repairs_ignores_printer_removed_outside_tool():
    identities = {"Gone": IdentityRecord("ip:ipp:/x", "network-ip", "ipp://1.2.3.4/x", 0.0)}
    assert plan_repairs({}, [], identities) == []
