from linuxprint.discovery import classify, suggest_queue_name


def test_classify_usb_extracts_model_and_serial():
    device = classify("usb://EPSON/L3150%20Series?serial=581234&interface=1")
    assert device.category == "usb"
    assert "L3150" in device.label
    assert device.identity_key == "usb:epson l3150 series:581234"


def test_classify_dnssd_is_self_healing_and_keys_on_uuid():
    device = classify("dnssd://Brother%20HL-2270DW._ipp._tcp.local/?uuid=abc-123")
    assert device.category == "network-mdns"
    assert device.label == "Brother HL-2270DW"
    assert device.identity_key == "dnssd:abc-123"


def test_classify_raw_ip_keys_on_scheme_and_path_not_host():
    device_a = classify("ipp://192.168.1.50:631/ipp/print")
    device_b = classify("ipp://192.168.1.99:631/ipp/print")
    assert device_a.category == "network-ip"
    assert device_a.identity_key == device_b.identity_key
    assert device_a.host == "192.168.1.50"
    assert device_a.port == 631


def test_classify_socket_scheme():
    device = classify("socket://192.168.1.50:9100")
    assert device.category == "network-ip"
    assert device.port == 9100


def test_suggest_queue_name_sanitizes():
    assert suggest_queue_name("Brother HL-2270DW") == "Brother-HL-2270DW"
    assert suggest_queue_name("EPSON L3150 Series") == "EPSON-L3150-Series"
