"""Graphical window of mfi-wifi-setup, version 1: a bridge to the original setup page.

Thin layer over the core modules bridge, device_check, messages and config_store,
which hold the logic and do not import tkinter. This is the only module that
imports tkinter. The program never creates or changes Wi-Fi profiles.
"""
from __future__ import annotations

import http.client
import queue
import string
import threading
import tkinter as tk
import webbrowser

from . import bridge, config_store, device_check, messages

DEVICE_HOST = "192.168.2.20"
DEVICE_PORT = 443
DEVICE_TIMEOUT_S = 5
UNKNOWN_MAC6 = "XXXXXX"
DRAIN_INTERVAL_MS = 200


def _device_connection() -> http.client.HTTPSConnection:
    """TLS 1.0 connection to the setup page of the device (certificate not verified)."""
    return http.client.HTTPSConnection(
        DEVICE_HOST, DEVICE_PORT, context=bridge.device_tls_context(), timeout=DEVICE_TIMEOUT_S
    )


def _mac6(model: str) -> str:
    """Last 6 hex digits of the host name (mFi-mPowerMini-AABBCC), or UNKNOWN_MAC6 when not there."""
    tail = model.rsplit("-", 1)[-1] if "-" in model else ""
    if len(tail) == 6 and all(c in string.hexdigits for c in tail):
        return tail.upper()
    return UNKNOWN_MAC6


class SetupWindow:
    """The window: steps 1 to 3, the language buttons and the close button."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.lang = messages.choose_language(messages.windows_language())
        self.status: device_check.DeviceStatus | None = None
        self.mac6 = UNKNOWN_MAC6
        self.bridge: bridge.Bridge | None = None
        self.note_key = "how_to_stop"
        self.error_text = ""
        self.updates: queue.Queue[device_check.DeviceStatus] = queue.Queue()
        self.stop_polling = threading.Event()
        self.saved_address = config_store.load_controller_address()

        self.title_label = tk.Label(root, font=("Segoe UI", 12, "bold"))
        self.it_button = tk.Button(root, text="IT", width=4, command=lambda: self._set_language("it"))
        self.en_button = tk.Button(root, text="EN", width=4, command=lambda: self._set_language("en"))
        self.step1_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.network_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.status_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.step2_button = tk.Button(root, state=tk.DISABLED, command=self._open_page)
        self.step3_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.address_entry = tk.Entry(root, width=40)
        self.address_entry.insert(0, self.saved_address)
        self.copy_button = tk.Button(root, command=self._copy_address)
        self.note_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.close_button = tk.Button(root, command=self.close)

        self.title_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.it_button.grid(row=0, column=1, pady=(10, 4))
        self.en_button.grid(row=0, column=2, sticky="e", padx=(0, 10), pady=(10, 4))
        self.step1_label.grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=4)
        self.network_label.grid(row=2, column=0, columnspan=3, sticky="w", padx=(30, 10))
        self.status_label.grid(row=3, column=0, columnspan=3, sticky="w", padx=(30, 10))
        self.step2_button.grid(row=4, column=0, columnspan=3, sticky="w", padx=(30, 10), pady=6)
        self.step3_label.grid(row=5, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))
        self.address_entry.grid(row=6, column=0, sticky="w", padx=(30, 4))
        self.copy_button.grid(row=6, column=1, columnspan=2, sticky="w", padx=(0, 10))
        self.note_label.grid(row=7, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))
        self.close_button.grid(row=8, column=2, sticky="e", padx=10, pady=(4, 10))

    def start(self) -> None:
        """Show the texts, start the device check, and apply its results on the Tk thread."""
        self._apply_language()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        threading.Thread(target=self._poll_device, daemon=True).start()
        self.root.after(DRAIN_INTERVAL_MS, self._drain_updates)

    def _apply_language(self) -> None:
        """Put every text of the window in the current language (all texts come from messages.tr)."""
        text = messages.tr(self.lang)
        self.root.title(text["title"])
        self.title_label.config(text=text["title"])
        self.step1_label.config(text="1  " + text["step1_title"])
        self.step2_button.config(text="2  " + text["step2_button"])
        self.step3_label.config(text="3  " + text["step3_title"])
        self.copy_button.config(text=text["copy_button"])
        self.close_button.config(text=text["close_button"])
        self._apply_status()
        self._refresh_note()

    def _apply_status(self) -> None:
        """Show the device status: model and firmware, or why the device cannot be used yet."""
        text = messages.tr(self.lang)
        status = self.status
        if status is None:
            line = text["status_checking"]
        elif status.state == device_check.STATE_FOUND:
            self.mac6 = _mac6(status.model)
            line = text["status_found"].format(model=status.model, firmware=status.firmware)
        elif status.state == device_check.STATE_NOT_ON_NETWORK:
            line = text["not_on_network"]
        else:
            line = text["not_answering"]
        found = status is not None and status.state == device_check.STATE_FOUND
        self.step2_button.config(state=tk.NORMAL if found else tk.DISABLED)
        self.network_label.config(text=text["network_name"].format(mac6=self.mac6))
        self.status_label.config(text=line)

    def _refresh_note(self) -> None:
        """Show the last error, or else the current note message."""
        self.note_label.config(text=self.error_text or messages.tr(self.lang)[self.note_key])

    def _set_error(self, text: str) -> None:
        """Show an error in the note line; an empty text clears it."""
        self.error_text = text
        self._refresh_note()

    def _set_language(self, lang: str) -> None:
        """Switch the language by hand and redraw every text."""
        self.lang = lang
        self._apply_language()

    def _poll_device(self) -> None:
        """Worker thread: check the device every CHECK_INTERVAL_S seconds. It never touches tkinter."""
        while True:
            try:
                status = device_check.read_status(_device_connection)
            except http.client.HTTPException:
                status = device_check.DeviceStatus(device_check.STATE_NOT_ANSWERING)
            self.updates.put(status)
            if self.stop_polling.wait(device_check.CHECK_INTERVAL_S):
                return

    def _drain_updates(self) -> None:
        """Tk thread: take the newest device statuses from the worker and schedule the next look."""
        changed = False
        while True:
            try:
                self.status = self.updates.get_nowait()
            except queue.Empty:
                break
            changed = True
        if changed:
            self._apply_status()
        self.root.after(DRAIN_INTERVAL_MS, self._drain_updates)

    def _open_page(self) -> None:
        """Start the bridge once and open the default browser on it."""
        try:
            if self.bridge is None:
                self.bridge = bridge.Bridge()
                self.bridge.start()
        except OSError as exc:
            self.bridge = None
            self._set_error(str(exc))
            return
        webbrowser.open(self.bridge.url)
        self.note_key = "page_ready"
        self._set_error("")

    def _copy_address(self) -> None:
        """Copy the controller address; a changed address is saved for the next run."""
        address = self.address_entry.get().strip()
        self.root.clipboard_clear()
        self.root.clipboard_append(address)
        if address != self.saved_address:
            try:
                config_store.save_controller_address(address)
            except OSError as exc:
                self._set_error(str(exc))
                return
            self.saved_address = address
        self._set_error("")

    def close(self) -> None:
        """Stop the device check and the bridge, then close the window (close button and window close)."""
        self.stop_polling.set()
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None
        self.root.destroy()


def run() -> None:
    """Open the window and run it until it is closed."""
    root = tk.Tk()
    SetupWindow(root).start()
    root.mainloop()
