from linuxprint.cups_cli import MarkerLevel
from linuxprint.watcher import Watcher


def _watcher_with_recorder():
    watcher = Watcher.__new__(Watcher)
    watcher._low_supplies_notified = set()
    emitted = []
    watcher.supplies_low = type("Signal", (), {"emit": staticmethod(emitted.append)})()
    return watcher, emitted


def test_check_low_supplies_emits_once_per_low_marker():
    watcher, emitted = _watcher_with_recorder()

    watcher._check_low_supplies({"Office": [MarkerLevel(name="Black", level=5)]})
    watcher._check_low_supplies({"Office": [MarkerLevel(name="Black", level=5)]})

    assert emitted == ["Office: Black is low (5%)."]


def test_check_low_supplies_renotifies_after_recovery_and_drop():
    watcher, emitted = _watcher_with_recorder()

    watcher._check_low_supplies({"Office": [MarkerLevel(name="Black", level=5)]})
    watcher._check_low_supplies({"Office": [MarkerLevel(name="Black", level=80)]})
    watcher._check_low_supplies({"Office": [MarkerLevel(name="Black", level=5)]})

    assert emitted == [
        "Office: Black is low (5%).",
        "Office: Black is low (5%).",
    ]


def test_check_low_supplies_ignores_unknown_levels():
    watcher, emitted = _watcher_with_recorder()

    watcher._check_low_supplies({"Office": [MarkerLevel(name="Black", level=-1)]})

    assert emitted == []
