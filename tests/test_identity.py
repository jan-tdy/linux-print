from linuxprint import config, identity
from linuxprint.discovery import DiscoveredPrinter


def test_remember_forget_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IDENTITY_FILE", tmp_path / "printers.json")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)

    device = DiscoveredPrinter(
        uri="ipp://192.168.1.50:631/ipp/print",
        scheme="ipp",
        category="network-ip",
        label="x",
        identity_key="ip:ipp:/ipp/print",
        host="192.168.1.50",
        port=631,
    )
    identity.remember("Office_Printer", device)

    records = identity.load_map()
    assert "Office_Printer" in records
    assert records["Office_Printer"].identity_key == "ip:ipp:/ipp/print"

    identity.forget("Office_Printer")
    assert identity.load_map() == {}


def test_load_map_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IDENTITY_FILE", tmp_path / "does-not-exist.json")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    assert identity.load_map() == {}
