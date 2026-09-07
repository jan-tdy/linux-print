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
    "idle": "Ready",
    "printing": "Printing",
    "stopped": "Stopped",
    "unreachable": "Unreachable",
    "unknown": "Unknown status",
}


def status_item(state: str) -> QTableWidgetItem:
    """
    Create a color-coded, vertically centered table item for a printer state.
    
    Parameters:
    	state (str): Printer state used to select the displayed label and foreground color.
    
    Returns:
    	QTableWidgetItem: Table item displaying the localized state label when available, or the raw state otherwise.
    """
    item = QTableWidgetItem(STATE_LABELS.get(state, state))
    item.setForeground(QColor(STATE_COLORS.get(state, STATE_COLORS["unknown"])))
    item.setTextAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    return item


CATEGORY_LABELS = {
    "usb": "USB",
    "network-mdns": "Network (autodiscovery)",
    "network-ip": "Network (fixed IP)",
    "remote-cups": "Remote CUPS server",
    "other": "Other",
}
