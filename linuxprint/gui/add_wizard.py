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
        super().__init__(parent)
        self.categories = categories
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        refresh_btn = QPushButton("Obnoviť")
        refresh_btn.clicked.connect(self.refresh)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(empty_hint))
        layout.addWidget(self.list_widget)
        layout.addWidget(refresh_btn)
        self.on_selection_changed = None  # callback set by the dialog

    def refresh(self) -> None:
        self.list_widget.clear()
        try:
            devices = discovery.discover_all()
        except cups_cli.CupsToolMissing as exc:
            QMessageBox.warning(self, "CUPS nástroje chýbajú", str(exc))
            return
        matching = [d for d in devices if d.category in self.categories]
        if not matching:
            self.list_widget.addItem("Nič sa nenašlo (skús Obnoviť znova)")
            self.list_widget.setEnabled(False)
            return
        self.list_widget.setEnabled(True)
        for device in matching:
            item = QListWidgetItem(f"{device.label}  [{device.uri}]")
            item.setData(1000, device)
            self.list_widget.addItem(item)

    def _on_selection_changed(self) -> None:
        if self.on_selection_changed:
            self.on_selection_changed(self.selected_device())

    def selected_device(self) -> DiscoveredPrinter | None:
        items = self.list_widget.selectedItems()
        if not items:
            return None
        return items[0].data(1000)


class _RemoteCupsTab(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.server_edit = QLineEdit()
        self.server_edit.setPlaceholderText("napr. tlaciaren-server.local:631")
        browse_btn = QPushButton("Prehľadať server")
        browse_btn.clicked.connect(self.browse)
        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)

        row = QHBoxLayout()
        row.addWidget(self.server_edit)
        row.addWidget(browse_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Zadaj adresu vzdialeného CUPS servera a prehľadaj jeho zdieľané tlačiarne:"))
        layout.addLayout(row)
        layout.addWidget(self.list_widget)
        self.on_selection_changed = None

    def browse(self) -> None:
        server = self.server_edit.text().strip()
        if not server:
            QMessageBox.information(self, "Chýba adresa", "Zadaj adresu alebo hostname servera.")
            return
        self.list_widget.clear()
        try:
            devices = discovery.list_remote_server_printers(server)
        except cups_cli.CupsToolMissing as exc:
            QMessageBox.warning(self, "CUPS nástroje chýbajú", str(exc))
            return
        if not devices:
            self.list_widget.addItem("Server neodpovedal alebo nezdieľa žiadne tlačiarne")
            self.list_widget.setEnabled(False)
            return
        self.list_widget.setEnabled(True)
        for device in devices:
            item = QListWidgetItem(f"{device.label}  [{device.uri}]")
            item.setData(1000, device)
            self.list_widget.addItem(item)

    def _on_selection_changed(self) -> None:
        if self.on_selection_changed:
            self.on_selection_changed(self.selected_device())

    def selected_device(self) -> DiscoveredPrinter | None:
        items = self.list_widget.selectedItems()
        if not items:
            return None
        return items[0].data(1000)


class AddPrinterDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Pridať tlačiareň")
        self.resize(560, 480)
        self.selected_device: DiscoveredPrinter | None = None

        self.usb_tab = _DiscoveryTab({"usb"}, "Zapojené USB tlačiarne rozpoznané systémom:")
        self.network_tab = _DiscoveryTab(
            {"network-mdns", "network-ip"}, "Tlačiarne nájdené v sieti (autodiscovery cez mDNS/IPP):"
        )
        self.remote_tab = _RemoteCupsTab()

        self.usb_tab.on_selection_changed = self._on_device_selected
        self.network_tab.on_selection_changed = self._on_device_selected
        self.remote_tab.on_selection_changed = self._on_device_selected

        tabs = QTabWidget()
        tabs.addTab(self.usb_tab, "USB")
        tabs.addTab(self.network_tab, "Sieť (autodiscovery)")
        tabs.addTab(self.remote_tab, "Vzdialený CUPS server")
        tabs.currentChanged.connect(lambda _: self._on_device_selected(None))

        self.name_edit = QLineEdit()
        self.description_edit = QLineEdit()
        self.location_edit = QLineEdit()
        self.shared_check = QCheckBox("Zdieľať v sieti")
        self.default_check = QCheckBox("Nastaviť ako predvolenú")

        form = QFormLayout()
        form.addRow("Názov frontu:", self.name_edit)
        form.addRow("Popis:", self.description_edit)
        form.addRow("Umiestnenie:", self.location_edit)
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
        self.selected_device = device
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(device is not None)
        if device is not None and not self.name_edit.text().strip():
            self.name_edit.setText(discovery.suggest_queue_name(device.label))

    def accept(self) -> None:
        if self.selected_device is None:
            return
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Chýba názov", "Zadaj názov tlačovej fronty.")
            return
        super().accept()

    # Convenience accessors used by the caller once accepted:
    def queue_name(self) -> str:
        return self.name_edit.text().strip()

    def description(self) -> str:
        return self.description_edit.text().strip()

    def location(self) -> str:
        return self.location_edit.text().strip()

    def shared(self) -> bool:
        return self.shared_check.isChecked()

    def set_default(self) -> bool:
        return self.default_check.isChecked()
