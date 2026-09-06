import subprocess

from linuxprint import servicectl


def test_systemctl_survives_missing_binary(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("systemctl not found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = servicectl._systemctl("is-active")
    assert result.returncode != 0


def test_systemctl_survives_timeout(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="systemctl", timeout=10)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = servicectl._systemctl("is-active")
    assert result.returncode != 0


def test_is_installed_false_when_systemctl_missing(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("no systemctl")

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert servicectl.is_installed() is False
