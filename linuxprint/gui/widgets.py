"""Small shared GUI helpers."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTableWidgetItem

from .. import cups_cli

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


def supplies_item(markers: list[cups_cli.MarkerLevel]) -> QTableWidgetItem:
    """
    Create a table item summarizing a printer's ink/toner levels.

    Parameters:
        markers (list[cups_cli.MarkerLevel]): The printer's supplies, as
            reported by `cups_cli.get_marker_levels` (empty when unknown).

    Returns:
        QTableWidgetItem: A comma-separated "name: level%" summary, in the
        "stopped" color when any supply is low, blank when nothing is
        reported.
    """
    item = QTableWidgetItem(
        ", ".join(
            f"{marker.name}: {marker.level}%" if marker.level >= 0 else f"{marker.name}: n/a"
            for marker in markers
        )
    )
    if any(marker.low for marker in markers):
        item.setForeground(QColor(STATE_COLORS["stopped"]))
    return item


CATEGORY_LABELS = {
    "usb": "USB",
    "network-mdns": "Network (autodiscovery)",
    "network-ip": "Network (fixed IP)",
    "remote-cups": "Remote CUPS server",
    "other": "Other",
}
