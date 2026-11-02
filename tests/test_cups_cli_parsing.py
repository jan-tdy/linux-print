from linuxprint.cups_cli import (
    Printer,
    ToolResult,
    add_or_update_printer,
    parse_lpinfo_v,
    parse_lpoptions_p,
    parse_lpstat_a,
    parse_lpstat_d,
    parse_lpstat_o,
    parse_lpstat_p,
    parse_lpstat_v,
    rename_printer,
    requires_legacy_transport_opt_in,
    set_device_uri,
    submit_print_job,
)


def test_parse_lpstat_p_idle_and_stopped():
    output = (
        "printer HP_LaserJet is idle.  enabled since Mon 01 Sep 2026 10:00:00 AM CEST\n"
        "printer Brother_HL is stopped for a reason unknown.\n"
        "printer Office_Copier now printing Office_Copier-42.  enabled since ...\n"
    )
    printers = parse_lpstat_p(output)
    assert printers["HP_LaserJet"].state == "idle"
    assert printers["Brother_HL"].state == "stopped"
    assert printers["Office_Copier"].state == "printing"


def test_parse_lpstat_d_with_default():
    assert parse_lpstat_d("system default destination: HP_LaserJet\n") == "HP_LaserJet"


def test_parse_lpstat_d_without_default():
    assert parse_lpstat_d("no system default destination.\n") is None


def test_parse_lpstat_a_accepting_and_rejecting():
    output = "HP_LaserJet accepting requests since Mon 01 Sep 2026\nBrother_HL not accepting requests since ...\n"
    result = parse_lpstat_a(output)
    assert result["HP_LaserJet"] is True
    assert result["Brother_HL"] is False


def test_parse_lpstat_v_extracts_uri():
    output = "device for HP_LaserJet: dnssd://HP%20LaserJet._ipp._tcp.local/?uuid=abc\n"
    result = parse_lpstat_v(output)
    assert result["HP_LaserJet"] == "dnssd://HP%20LaserJet._ipp._tcp.local/?uuid=abc"


def test_parse_lpinfo_v_splits_kind_and_uri():
    output = "network dnssd://Brother%20HL-2270DW._ipp._tcp.local/?uuid=xyz\ndirect usb://EPSON/L3150?serial=581234\n"
    devices = parse_lpinfo_v(output)
    assert len(devices) == 2
    assert devices[0].kind == "network"
    assert devices[0].scheme == "dnssd"
    assert devices[1].scheme == "usb"


def test_parse_lpstat_o_extracts_jobs():
    output = "HP_LaserJet-42     jan             1024   Sun 06 Sep 2026 10:00:00 AM CEST\n"
    jobs = parse_lpstat_o(output)
    assert len(jobs) == 1
    assert jobs[0].job_id == "HP_LaserJet-42"
    assert jobs[0].user == "jan"
    assert jobs[0].printer == "HP_LaserJet"


def test_legacy_transport_detection():
    assert requires_legacy_transport_opt_in("ipp://printer.local/ipp/print")
    assert requires_legacy_transport_opt_in("socket://printer.local:9100")
    assert requires_legacy_transport_opt_in("lpd://printer.local/queue")
    assert requires_legacy_transport_opt_in("http://printer.local/ipp/print")
    assert requires_legacy_transport_opt_in("dnssd://Printer._ipp._tcp.local/")
    assert requires_legacy_transport_opt_in("dnssd://Printer._pdl-datastream._tcp.local/")
    assert requires_legacy_transport_opt_in("dnssd://Printer._ipp._tcp.local/?note=._ipps._tcp.local")
    assert not requires_legacy_transport_opt_in("ipps://printer.local/ipp/print")
    assert not requires_legacy_transport_opt_in("https://printer.local/ipp/print")
    assert not requires_legacy_transport_opt_in("dnssd://Printer._ipps._tcp.local/")
    assert not requires_legacy_transport_opt_in("usb://EPSON/L3150")


def test_add_printer_blocks_legacy_transport_without_opt_in(monkeypatch):
    calls = []
    monkeypatch.setattr("linuxprint.cups_cli.run", lambda args: calls.append(args))

    result = add_or_update_printer("Office", "ipp://printer.local/ipp/print")

    assert not result.ok
    assert calls == []


def test_add_printer_rejects_non_boolean_legacy_transport_opt_in(monkeypatch):
    calls = []
    monkeypatch.setattr("linuxprint.cups_cli.run", lambda args: calls.append(args))

    result = add_or_update_printer(
        "Office",
        "ipp://printer.local/ipp/print",
        allow_legacy_transport="yes",  # type: ignore[arg-type]
    )

    assert not result.ok
    assert calls == []


def test_add_printer_allows_legacy_transport_after_opt_in(monkeypatch):
    calls = []

    def fake_run(args):
        calls.append(args)
        from linuxprint.cups_cli import ToolResult

        return ToolResult(True, 0, "", "")

    monkeypatch.setattr("linuxprint.cups_cli.run", fake_run)

    result = add_or_update_printer(
        "Office", "socket://printer.local:9100", allow_legacy_transport=True, enable=False, accept=False
    )

    assert result.ok
    assert calls[0][:5] == ["lpadmin", "-p", "Office", "-v", "socket://printer.local:9100"]


def test_set_device_uri_blocks_legacy_transport_without_opt_in(monkeypatch):
    calls = []
    monkeypatch.setattr("linuxprint.cups_cli.run", lambda args: calls.append(args))

    result = set_device_uri("Office", "lpd://printer.local/queue")

    assert not result.ok
    assert calls == []


def test_submit_print_job_without_ppi_omits_the_option(monkeypatch):
    calls = []
    monkeypatch.setattr("linuxprint.cups_cli.run", lambda args: calls.append(args))

    submit_print_job("Office", "/tmp/design.svg", title="Job")

    assert calls == [["lp", "-d", "Office", "-t", "Job", "/tmp/design.svg"]]


def test_submit_print_job_with_ppi_tells_cups_the_raster_resolution(monkeypatch):
    calls = []
    monkeypatch.setattr("linuxprint.cups_cli.run", lambda args: calls.append(args))

    submit_print_job("Office", "/tmp/artwork.png", title="Job", ppi=200)

    assert calls == [["lp", "-d", "Office", "-t", "Job", "-o", "ppi=200", "/tmp/artwork.png"]]


def test_parse_lpoptions_p_extracts_shared_description_and_location():
    output = (
        "copies=1 device-uri=ipp://printer.local/ipp/print printer-info=FrontDesk "
        "printer-is-shared=true printer-location=Lobby\n"
    )
    attrs = parse_lpoptions_p(output)
    assert attrs["printer-is-shared"] == "true"
    assert attrs["printer-location"] == "Lobby"
    assert attrs["device-uri"] == "ipp://printer.local/ipp/print"


def test_rename_printer_fails_fast_when_old_printer_missing(monkeypatch):
    monkeypatch.setattr("linuxprint.cups_cli.list_printers", lambda: {})
    calls = []
    monkeypatch.setattr("linuxprint.cups_cli.run", lambda args: calls.append(args))

    result = rename_printer("Missing", "New", "ipp://printer.local/ipp/print")

    assert not result.ok
    assert calls == []


def test_rename_printer_carries_over_shared_description_location_and_default(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "linuxprint.cups_cli.list_printers",
        lambda: {"Old": Printer(name="Old", uri="ipp://printer.local/ipp/print", is_default=True)},
    )
    monkeypatch.setattr(
        "linuxprint.cups_cli.printer_attributes",
        lambda name: {
            "printer-info": "Front Desk",
            "printer-location": "Lobby",
            "printer-is-shared": "true",
        },
    )
    monkeypatch.setattr("linuxprint.cups_cli.os.path.isfile", lambda path: False)

    def fake_run(args):
        calls.append(args)
        return ToolResult(True, 0, "", "")

    monkeypatch.setattr("linuxprint.cups_cli.run", fake_run)

    result = rename_printer("Old", "New", "ipp://printer.local/ipp/print", allow_legacy_transport=True)

    assert result.ok
    lpadmin_call = calls[0]
    assert lpadmin_call[:5] == ["lpadmin", "-p", "New", "-v", "ipp://printer.local/ipp/print"]
    assert lpadmin_call[lpadmin_call.index("-D") + 1] == "Front Desk"
    assert lpadmin_call[lpadmin_call.index("-L") + 1] == "Lobby"
    assert "printer-is-shared=true" in lpadmin_call
    assert ["lpoptions", "-d", "New"] in calls
    assert ["lpadmin", "-x", "Old"] in calls


def test_rename_printer_copies_bound_ppd_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "linuxprint.cups_cli.list_printers",
        lambda: {"Old": Printer(name="Old", uri="ipp://printer.local/ipp/print")},
    )
    monkeypatch.setattr("linuxprint.cups_cli.printer_attributes", lambda name: {})
    monkeypatch.setattr("linuxprint.cups_cli._SYSTEM_PPD_DIR", str(tmp_path))
    ppd_path = tmp_path / "Old.ppd"
    ppd_path.write_text('*PPD-Adobe: "4.3"\n')

    calls = []

    def fake_run(args):
        calls.append(args)
        return ToolResult(True, 0, "", "")

    monkeypatch.setattr("linuxprint.cups_cli.run", fake_run)

    rename_printer("Old", "New", "ipp://printer.local/ipp/print", allow_legacy_transport=True)

    assert ["lpadmin", "-p", "New", "-P", str(ppd_path)] in calls


def test_rename_printer_keeps_old_queue_when_new_queue_creation_fails(monkeypatch):
    monkeypatch.setattr(
        "linuxprint.cups_cli.list_printers",
        lambda: {"Old": Printer(name="Old", uri="ipp://printer.local/ipp/print")},
    )
    monkeypatch.setattr("linuxprint.cups_cli.printer_attributes", lambda name: {})

    calls = []

    def fake_run(args):
        calls.append(args)
        return ToolResult(False, 1, "", "lpadmin: failed")

    monkeypatch.setattr("linuxprint.cups_cli.run", fake_run)

    result = rename_printer("Old", "New", "ipp://printer.local/ipp/print", allow_legacy_transport=True)

    assert not result.ok
    assert calls  # the lpadmin call was actually attempted
    assert ["lpadmin", "-x", "Old"] not in calls
