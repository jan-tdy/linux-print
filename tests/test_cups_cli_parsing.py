from linuxprint.cups_cli import (
    parse_lpinfo_v,
    parse_lpstat_a,
    parse_lpstat_d,
    parse_lpstat_o,
    parse_lpstat_p,
    parse_lpstat_v,
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
