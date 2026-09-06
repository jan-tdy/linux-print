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
    assert records["Office_Printer"].legacy_transport_allowed is False

    identity.forget("Office_Printer")
    assert identity.load_map() == {}


def test_load_map_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IDENTITY_FILE", tmp_path / "does-not-exist.json")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    assert identity.load_map() == {}


def test_load_map_returns_empty_for_non_dict_json(tmp_path, monkeypatch):
    identity_file = tmp_path / "printers.json"
    monkeypatch.setattr(config, "IDENTITY_FILE", identity_file)
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)

    identity_file.write_text("[]", encoding="utf-8")
    assert identity.load_map() == {}

    identity_file.write_text("null", encoding="utf-8")
    assert identity.load_map() == {}


def test_load_map_rejects_non_boolean_legacy_transport_consent(tmp_path, monkeypatch):
    identity_file = tmp_path / "printers.json"
    monkeypatch.setattr(config, "IDENTITY_FILE", identity_file)
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    identity_file.write_text(
        '{"Office": {"identity_key": "ip:ipp:/", "category": "network-ip", '
        '"added_uri": "ipp://printer/", "added_at": 0, "legacy_transport_allowed": "yes"}}',
        encoding="utf-8",
    )

    assert identity.load_map()["Office"].legacy_transport_allowed is False


def test_remember_persists_legacy_transport_consent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IDENTITY_FILE", tmp_path / "printers.json")
    monkeypatch.setattr(config, "ensure_dirs", lambda: None)
    device = DiscoveredPrinter(
        uri="socket://192.168.1.50:9100",
        scheme="socket",
        category="network-ip",
        label="Office Printer",
        identity_key="ip:socket:/",
    )

    identity.remember("Office_Printer", device, legacy_transport_allowed=True)

    assert identity.load_map()["Office_Printer"].legacy_transport_allowed is True
