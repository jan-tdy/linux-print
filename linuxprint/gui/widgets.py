"""Small shared GUI helpers."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidgetItem

STATE_COLORS = {
    "idle": "#2e7d32",
    "printing": "#1565c0",
    "stopped": "#c62828",
    "unreachable": "#ef6c00",
    "unknown": "#757575",
}

STATE_LABELS = {
    "idle": "Pripravená",
    "printing": "Tlačí",
    "stopped": "Zastavená",
    "unreachable": "Nedostupná",
    "unknown": "Neznámy stav",
}


def status_item(state: str) -> QTableWidgetItem:
    item = QTableWidgetItem(STATE_LABELS.get(state, state))
    item.setForeground(QColor(STATE_COLORS.get(state, STATE_COLORS["unknown"])))
    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return item


CATEGORY_LABELS = {
    "usb": "USB",
    "network-mdns": "Sieťová (autodiscovery)",
    "network-ip": "Sieťová (pevná IP)",
    "remote-cups": "Vzdialený CUPS server",
    "other": "Iné",
}
