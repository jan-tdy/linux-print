"""'Add printer' dialog: USB / autodiscovered network / remote CUPS server."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .. import cups_cli, discovery
from ..discovery import DiscoveredPrinter


class _DiscoveryTab(QWidget):
    """Shared behaviour for the USB and network discovery tabs."""

    def __init__(self, categories: set[str], empty_hint: str, parent=None) -> None:
        """
        Initialize a discovery tab for the specified printer categories.
        
        Parameters:
        	categories (set[str]): Printer categories to include in discovery results.
        	empty_hint (str): Message displayed when no printers are available.
        """
        super().__init__(parent)
        self.categories = categories
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(empty_hint))
        layout.addWidget(self.list_widget)
        layout.addWidget(refresh_btn)
        self.on_selection_changed = None  # callback set by the dialog

    def refresh(self) -> None:
        """
        Refresh the list with printers discovered in the configured categories.
        
        Clears existing entries, displays a message when no matching printers are found, and warns when the required CUPS tools are unavailable.
        """
        self.list_widget.clear()
        try:
            devices = discovery.discover_all()
        except cups_cli.CupsToolMissing as exc:
            QMessageBox.warning(self, "CUPS tools missing", str(exc))
            return
        matching = [d for d in devices if d.category in self.categories]
        if not matching:
            self.list_widget.addItem("Nothing found (try Refresh again)")
            self.list_widget.setEnabled(False)
            return
        self.list_widget.setEnabled(True)
        for device in matching:
            item = QListWidgetItem(f"{device.label}  [{device.uri}]")
            item.setData(1000, device)
            self.list_widget.addItem(item)

    def _on_selection_changed(self) -> None:
        """Notify the selection callback with the currently selected printer, when configured."""
        if self.on_selection_changed:
            self.on_selection_changed(self.selected_device())

    def selected_device(self) -> DiscoveredPrinter | None:
        """Return the currently selected discovered printer, if any.
        
        Returns:
        	DiscoveredPrinter | None: The selected printer, or `None` when no printer is selected.
        """
        items = self.list_widget.selectedItems()
        if not items:
            return None
        return items[0].data(1000)


class _RemoteCupsTab(QWidget):
    def __init__(self, parent=None) -> None:
        """
        Initialize the remote CUPS server browsing interface.
        """
        super().__init__(parent)
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("e.g. printer-server.local:631")
        browse_btn = QPushButton("Browse server")
        browse_btn.clicked.connect(self.browse)
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)

        row = QHBoxLayout()
        row.addWidget(self.server_edit)
        row.addWidget(browse_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Enter the remote CUPS server's address and browse its shared printers:"))
        layout.addLayout(row)
        layout.addWidget(self.list_widget)
        self.on_selection_changed = None

    def browse(self) -> None:
        """
        Browse the remote CUPS server for available printers.
        """
        server = self.server_edit.text().strip()
        if not server:
            QMessageBox.information(self, "Missing address", "Enter the server's address or hostname.")
            return
        self.list_widget.clear()
        try:
            devices = discovery.list_remote_server_printers(server)
        except cups_cli.CupsToolMissing as exc:
            QMessageBox.warning(self, "CUPS tools missing", str(exc))
            return
        if not devices:
            self.list_widget.addItem("Server did not respond or shares no printers")
            self.list_widget.setEnabled(False)
            return
        self.list_widget.setEnabled(True)
        for device in devices:
            item = QListWidgetItem(f"{device.label}  [{device.uri}]")
            item.setData(1000, device)
            self.list_widget.addItem(item)

    def _on_selection_changed(self) -> None:
        """Notify the selection callback with the currently selected printer, when configured."""
        if self.on_selection_changed:
            self.on_selection_changed(self.selected_device())

    def selected_device(self) -> DiscoveredPrinter | None:
        """Return the currently selected discovered printer, if any.
        
        Returns:
        	DiscoveredPrinter | None: The selected printer, or `None` when no printer is selected.
        """
        items = self.list_widget.selectedItems()
        if not items:
            return None
        return items[0].data(1000)


class AddPrinterDialog(QDialog):
    def __init__(self, parent=None) -> None:
        """Initialize the add-printer dialog with discovery tabs and printer configuration fields."""
        super().__init__(parent)
        self.setWindowTitle("Add printer")
        self.resize(560, 480)
        self.selected_device: DiscoveredPrinter | None = None

        self.usb_tab = _DiscoveryTab({"usb"}, "USB printers connected and recognised by the system:")
        self.network_tab = _DiscoveryTab(
            {"network-mdns", "network-ip"}, "Printers found on the network (autodiscovery via mDNS/IPP):"
        )
        self.remote_tab = _RemoteCupsTab()

        self.usb_tab.on_selection_changed = self._on_device_selected
        self.network_tab.on_selection_changed = self._on_device_selected
        self.remote_tab.on_selection_changed = self._on_device_selected

        tabs = QTabWidget()
        tabs.addTab(self.usb_tab, "USB")
        tabs.addTab(self.network_tab, "Network (autodiscovery)")
        tabs.addTab(self.remote_tab, "Remote CUPS server")
        tabs.currentChanged.connect(lambda _: self._on_device_selected(None))

        self.name_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.location_edit = QLineEdit()
        self.shared_check = QCheckBox("Share on network")
        self.default_check = QCheckBox("Set as default")

        form = QFormLayout()
        form.addRow("Queue name:", self.name_edit)
        form.addRow("Description:", self.description_edit)
        form.addRow("Location:", self.location_edit)
        form.addRow(self.shared_check)
        form.addRow(self.default_check)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)

        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.usb_tab.refresh()
        self.network_tab.refresh()

    def _on_device_selected(self, device: DiscoveredPrinter | None) -> None:
        """Update the selected printer and enable confirmation when a printer is selected."""
        self.selected_device = device
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(device is not None)
        if device is not None and not self.name_edit.text().strip():
            self.name_edit.setText(discovery.suggest_queue_name(device.label))

    def accept(self) -> None:
        """
        Accept the dialog when a printer is selected and a queue name is provided.
        
        Displays a warning and leaves the dialog open when the queue name is empty.
        """
        if self.selected_device is None:
            return
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Missing name", "Enter a print queue name.")
            return
        super().accept()

    # Convenience accessors used by the caller once accepted:
    def queue_name(self) -> str:
        """
        Return the configured printer queue name.
        
        Returns:
        	str: The queue name with leading and trailing whitespace removed.
        """
        return self.name_edit.text().strip()

    def description(self) -> str:
        """Return the printer description entered in the dialog."""
        return self.description_edit.text().strip()

    def location(self) -> str:
        """Return the configured printer location."""
        return self.location_edit.text().strip()

    def shared(self) -> bool:
        """Return whether printer sharing is enabled."""
        return self.shared_check.isChecked()

    def set_default(self) -> bool:
        """Return whether the printer should be configured as the default printer.
        
        Returns:
        	bool: `True` if the default-printer option is selected, `False` otherwise.
        """
        return self.default_check.isChecked()
