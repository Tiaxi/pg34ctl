"""The settings window, laid out like the monitor's own OSD."""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..aspect import Aspect, AspectError, Scaling, current_aspect, switch_aspect
from ..ddc import DdcError, MonitorNotFound, open_backend
from ..features import BY_KEY, FEATURES, MODE_CHANGING, Feature, Kind, Tab
from ..monitor import FeatureState, Monitor

UNVERIFIED = "Mapping taken from ASUS DisplayWidget Center; not yet confirmed on this monitor."


def _value(states: dict[str, FeatureState], key: str) -> int | None:
    state = states.get(key)
    return state.value if state and state.available else None


# Settings the monitor only honours while another setting has a given value; the OSD
# greys them out the same way. Each maps to (predicate, reason shown in the tooltip).
GATES = {
    "red_gain": (lambda s: _value(s, "color_temp") == 0x0B, "Set Color Temp. to User"),
    "green_gain": (lambda s: _value(s, "color_temp") == 0x0B, "Set Color Temp. to User"),
    "blue_gain": (lambda s: _value(s, "color_temp") == 0x0B, "Set Color Temp. to User"),
    "adjustable_hdr": (lambda s: _value(s, "hdr_mode") is not None, "Turn HDR on in the OS"),
    "aura_color": (
        lambda s: _value(s, "aura_effect") in (0x04, 0x05, 0x06),
        "Only for the Static, Breathing and Strobing effects",
    ),
}


class Worker(QObject):
    """Owns the monitor connection; every DDC/CI call happens on its thread."""

    connected = Signal(dict)
    states = Signal(dict)
    aspect = Signal(str)
    message = Signal(str)
    failed = Signal(str)
    busy = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self.monitor: Monitor | None = None

    def _run(self, action, *args) -> None:
        self.busy.emit(True)
        try:
            if self.monitor is None:
                self.monitor = Monitor(open_backend())
                self.connected.emit(
                    {
                        "description": self.monitor.backend.description,
                        "firmware": self.monitor.firmware(),
                        "hours": self.monitor.usage_hours(),
                    }
                )
            action(*args)
        except (MonitorNotFound, DdcError, AspectError, ValueError, OSError) as exc:
            self.failed.emit(str(exc))
        finally:
            self.busy.emit(False)

    def _refresh(self) -> None:
        self.states.emit(self.monitor.read_all())
        self.aspect.emit(current_aspect(self.monitor.backend).value)

    @Slot()
    def refresh(self) -> None:
        self._run(self._refresh)

    @Slot(str, int)
    def write(self, key: str, value: int) -> None:
        def action():
            feature = BY_KEY[key]
            state = self.monitor.write(feature, value)
            if feature.code in MODE_CHANGING:
                self._refresh()
            else:
                self.states.emit({key: state})
            self.message.emit(f"{feature.label} set to {feature.label_for(value)}")

        self._run(action)

    @Slot(str, int)
    def switch_aspect(self, ratio: str, scaling: int) -> None:
        def action():
            switch_aspect(
                self.monitor.backend,
                Aspect(ratio),
                Scaling(scaling),
                on_step=self.message.emit,
            )
            self._refresh()
            self.message.emit(f"Aspect is now {ratio}")

        self._run(action)

    @Slot()
    def pixel_cleaning(self) -> None:
        def action():
            self.monitor.start_pixel_cleaning()
            self.message.emit("Pixel cleaning started")

        self._run(action)

    @Slot(int)
    def raw_get(self, code: int) -> None:
        def action():
            reading = self.monitor.backend.get_vcp(code)
            self.message.emit(
                f"VCP 0x{code:02X}: current 0x{reading.current:04X}, max 0x{reading.maximum:04X}"
            )

        self._run(action)

    @Slot(int, int)
    def raw_set(self, code: int, value: int) -> None:
        def action():
            self.monitor.backend.set_vcp(code, value)
            self.message.emit(f"Wrote 0x{value:04X} to VCP 0x{code:02X}")

        self._run(action)

    @Slot()
    def capabilities(self) -> None:
        self._run(lambda: self.message.emit(self.monitor.backend.capabilities()))


class FeatureRow(QWidget):
    """One setting: a slider, dropdown or checkbox that writes when the user changes it."""

    changed = Signal(str, int)

    def __init__(self, feature: Feature) -> None:
        super().__init__()
        self.feature = feature
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self._debounce = QTimer(self, singleShot=True, interval=300)
        self._debounce.timeout.connect(self._emit_range)
        if feature.kind is Kind.RANGE:
            self.slider = QSlider(Qt.Orientation.Horizontal)
            self.spin = QSpinBox()
            self.slider.valueChanged.connect(self.spin.setValue)
            self.spin.valueChanged.connect(self.slider.setValue)
            self.spin.valueChanged.connect(lambda _v: self._debounce.start())
            layout.addWidget(self.slider, 1)
            layout.addWidget(self.spin)
        elif feature.kind is Kind.CHOICE:
            self.combo = QComboBox()
            self.combo.setPlaceholderText("—")
            for value, label in feature.choices.items():
                self.combo.addItem(label, value)
            self.combo.activated.connect(
                lambda index: self.changed.emit(feature.key, self.combo.itemData(index))
            )
            layout.addWidget(self.combo, 1)
        else:
            self.check = QCheckBox()
            self.check.clicked.connect(lambda on: self.changed.emit(feature.key, int(on)))
            layout.addWidget(self.check, 1)

    def _emit_range(self) -> None:
        self.changed.emit(self.feature.key, self.spin.value())

    def show_state(self, state: FeatureState) -> None:
        widgets = self.findChildren(QWidget)
        for widget in widgets:
            widget.blockSignals(True)
        try:
            if state.value is not None and self.feature.kind is Kind.RANGE:
                self.slider.setRange(0, state.maximum or 100)
                self.spin.setRange(0, state.maximum or 100)
                self.spin.setValue(state.value)
                self.slider.setValue(state.value)
            elif state.value is not None and self.feature.kind is Kind.CHOICE:
                index = self.combo.findData(state.value)
                self.combo.setCurrentIndex(index)
            elif state.value is not None:
                self.check.setChecked(bool(state.value))
        finally:
            for widget in widgets:
                widget.blockSignals(False)
        self.setEnabled(state.available)
        if state.locked:
            self.setToolTip("Greyed out by the monitor in its current mode.")
        elif not state.available:
            self.setToolTip(self.feature.note or state.error or "Not available right now.")
        else:
            self.setToolTip(self.feature.note)


class MainWindow(QMainWindow):
    request_refresh = Signal()
    request_write = Signal(str, int)
    request_aspect = Signal(str, int)
    request_pixel_cleaning = Signal()
    request_raw_get = Signal(int)
    request_raw_set = Signal(int, int)
    request_capabilities = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PG34WCDN Control")
        self.resize(720, 640)
        self.rows: dict[str, FeatureRow] = {}
        self.states: dict[str, FeatureState] = {}

        self.header = QLabel("Connecting to the monitor…")
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.request_refresh)
        top = QHBoxLayout()
        top.addWidget(self.header, 1)
        top.addWidget(refresh)

        self.tabs = QTabWidget()
        for tab in Tab:
            self.tabs.addTab(self._feature_tab(tab), tab.value)
        self.tabs.addTab(self._advanced_tab(), "Advanced")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        self.thread = QThread(self)
        self.worker = Worker()
        self.worker.moveToThread(self.thread)
        self.request_refresh.connect(self.worker.refresh)
        self.request_write.connect(self.worker.write)
        self.request_aspect.connect(self.worker.switch_aspect)
        self.request_pixel_cleaning.connect(self.worker.pixel_cleaning)
        self.request_raw_get.connect(self.worker.raw_get)
        self.request_raw_set.connect(self.worker.raw_set)
        self.request_capabilities.connect(self.worker.capabilities)
        self.worker.connected.connect(self._on_connected)
        self.worker.states.connect(self._on_states)
        self.worker.aspect.connect(self._on_aspect)
        self.worker.message.connect(self._on_message)
        self.worker.failed.connect(self._on_failed)
        self.worker.busy.connect(self._on_busy)
        self.thread.start()
        self.request_refresh.emit()

    # Layout

    def _feature_tab(self, tab: Tab) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        if tab is Tab.IMAGE:
            outer.addWidget(self._aspect_box())
        form = QFormLayout()
        for feature in (f for f in FEATURES if f.tab is tab):
            row = FeatureRow(feature)
            row.changed.connect(self._on_row_changed)
            self.rows[feature.key] = row
            label = QLabel(feature.label + ("" if feature.verified else " *"))
            label.setToolTip("" if feature.verified else UNVERIFIED)
            form.addRow(label, row)
        outer.addLayout(form)
        if tab is Tab.OLED:
            clean = QPushButton("Start Pixel Cleaning…")
            clean.clicked.connect(self._confirm_pixel_cleaning)
            outer.addWidget(clean, 0, Qt.AlignmentFlag.AlignLeft)
        outer.addStretch(1)
        footnote = QLabel("* " + UNVERIFIED)
        footnote.setWordWrap(True)
        footnote.setEnabled(False)
        outer.addWidget(footnote)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        return scroll

    def _aspect_box(self) -> QGroupBox:
        box = QGroupBox("Aspect Control")
        layout = QHBoxLayout(box)
        self.aspect_label = QLabel("Current: …")
        self.aspect_buttons = []
        layout.addWidget(self.aspect_label, 1)
        for aspect in Aspect:
            button = QPushButton(aspect.value)
            button.clicked.connect(lambda _c=False, a=aspect: self._switch_aspect(a))
            layout.addWidget(button)
            self.aspect_buttons.append(button)
        box.setToolTip(
            "Drives the monitor's OSD remotely (HDR must be off). In 16:9 the monitor "
            "advertises 2560x1440 as its native resolution."
        )
        return box

    def _advanced_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        row = QHBoxLayout()
        self.raw_code = QLineEdit(placeholderText="VCP code, hex (e.g. 86)")
        self.raw_value = QLineEdit(placeholderText="value (e.g. 0x0002)")
        read = QPushButton("Read")
        write = QPushButton("Write…")
        caps = QPushButton("Capabilities")
        read.clicked.connect(self._raw_read)
        write.clicked.connect(self._raw_write)
        caps.clicked.connect(self.request_capabilities)
        for widget in (self.raw_code, self.raw_value, read, write, caps):
            row.addWidget(widget)
        layout.addLayout(row)
        self.log = QPlainTextEdit(readOnly=True)
        layout.addWidget(self.log, 1)
        return page

    # Actions

    def _on_row_changed(self, key: str, value: int) -> None:
        feature = BY_KEY[key]
        if feature.confirm and not self._confirm(feature.label, feature.confirm):
            self.rows[key].show_state(self.states[key])
            return
        self.request_write.emit(key, value)

    def _switch_aspect(self, aspect: Aspect) -> None:
        scaling = self.states.get("scaling")
        value = scaling.value if scaling and scaling.available else Scaling.PIXEL_BY_PIXEL.value
        self.request_aspect.emit(aspect.value, value)

    def _confirm_pixel_cleaning(self) -> None:
        if self._confirm(
            "Pixel Cleaning", "The screen goes dark for about 6-8 minutes. Start now?"
        ):
            self.request_pixel_cleaning.emit()

    def _raw_read(self) -> None:
        try:
            self.request_raw_get.emit(int(self.raw_code.text(), 16))
        except ValueError:
            self._on_failed("Enter the VCP code in hex, e.g. 86")

    def _raw_write(self) -> None:
        try:
            code, value = int(self.raw_code.text(), 16), int(self.raw_value.text(), 0)
        except ValueError:
            self._on_failed("Enter a hex VCP code and a value")
            return
        if self._confirm(
            "Raw write",
            f"Write 0x{value:04X} to VCP 0x{code:02X}? Unknown codes can do anything, "
            "including a factory reset.",
        ):
            self.request_raw_set.emit(code, value)

    def _confirm(self, title: str, text: str) -> bool:
        answer = QMessageBox.question(self, title, text)
        return answer == QMessageBox.StandardButton.Yes

    # Worker results

    def _on_connected(self, info: dict) -> None:
        self.header.setText(
            f"<b>ASUS ROG Swift PG34WCDN</b> · firmware {info['firmware']} · "
            f"{info['hours']} h · {info['description']}"
        )

    def _on_states(self, states: dict) -> None:
        self.states.update(states)
        for key, state in states.items():
            self.rows[key].show_state(state)
        for key, (allowed, reason) in GATES.items():
            state = self.states.get(key)
            if state and state.available and not allowed(self.states):
                self.rows[key].setEnabled(False)
                self.rows[key].setToolTip(reason)

    def _on_aspect(self, value: str) -> None:
        self.aspect_label.setText(f"Current: <b>{value}</b>")

    def _on_message(self, text: str) -> None:
        self.statusBar().showMessage(text.splitlines()[0][:200], 8000)
        self.log.appendPlainText(text)

    def _on_failed(self, text: str) -> None:
        self.statusBar().showMessage(f"Error: {text}", 15000)
        self.log.appendPlainText(f"Error: {text}")
        if self.header.text().startswith("Connecting"):
            self.header.setText(f"<b>Not connected:</b> {text}")
            self.header.setWordWrap(True)

    def _on_busy(self, busy: bool) -> None:
        for button in self.aspect_buttons:
            button.setEnabled(not busy)
        if busy:
            QApplication.setOverrideCursor(Qt.CursorShape.BusyCursor)
        else:
            QApplication.restoreOverrideCursor()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self.thread.quit()
        self.thread.wait(5000)
        if self.worker.monitor:
            self.worker.monitor.close()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("pg34ctl")
    app.setDesktopFileName("pg34ctl")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
