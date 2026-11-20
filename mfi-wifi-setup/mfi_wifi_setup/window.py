"""Graphical window of mfi-wifi-setup: version 1 (bridge to the setup page) and version 2 (guided setup).

Thin layer over the core modules, which hold the logic and do not import tkinter:
bridge, device_check, messages, wifi_survey and wifi_configure. This is the only
module that imports tkinter. The program never creates or changes Wi-Fi profiles.
The Wi-Fi password is never saved, logged or shown in an error message.
"""
from __future__ import annotations

import http.client
import queue
import string
import threading
import tkinter as tk
import webbrowser
from collections.abc import Callable

from . import bridge, device_check, icon, messages, wifi_configure, wifi_survey

DEVICE_HOST = "192.168.2.20"
DEVICE_PORT = 443
DEVICE_TIMEOUT_S = 5
UNKNOWN_MAC6 = "XXXXXX"
DRAIN_INTERVAL_MS = 200
PASSWORD_MASK = "\u2022"

PROGRESS_KEYS = {
    wifi_configure.STEP_PENDING: "progress_pending",
    wifi_configure.STEP_WIFI_CONNECTED: "progress_wifi",
    wifi_configure.STEP_ADDRESS_OBTAINED: "progress_address",
}


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
    """The window: steps 1 and 2 (version 2 guided setup, with the version 1 page button), the language buttons and the close button."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.lang = messages.choose_language(messages.windows_language())
        self.status: device_check.DeviceStatus | None = None
        self.mac6 = UNKNOWN_MAC6
        self.bridge: bridge.Bridge | None = None
        self.note_key = "how_to_stop"
        self.error_text = ""
        self.updates: queue.Queue[device_check.DeviceStatus] = queue.Queue()
        self.calls: queue.Queue[Callable[[], None]] = queue.Queue()
        self.stop_polling = threading.Event()
        self.networks: list[wifi_survey.Network] = []
        self.scan_started = False
        self.configuring = False
        self.scan_key = ""
        self.progress_key = ""
        self.result_key = ""
        self.result_ip = ""

        self.title_label = tk.Label(root, font=("Segoe UI", 12, "bold"))
        self.it_button = tk.Button(root, text="IT", width=4, command=lambda: self._set_language("it"))
        self.en_button = tk.Button(root, text="EN", width=4, command=lambda: self._set_language("en"))
        self.step1_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.network_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.status_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.step2_button = tk.Button(root, state=tk.DISABLED, command=self._open_page)
        self.networks_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.network_list = tk.Listbox(root, height=6, width=48, exportselection=False)
        self.scan_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.password_label = tk.Label(root)
        self.password_entry = tk.Entry(root, width=30, show=PASSWORD_MASK)
        self.show_var = tk.BooleanVar(value=False)
        self.show_check = tk.Checkbutton(root, variable=self.show_var, command=self._toggle_password)
        self.configure_button = tk.Button(root, state=tk.DISABLED, command=self._on_configure)
        self.progress_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.result_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.note_label = tk.Label(root, justify=tk.LEFT, wraplength=460)
        self.close_button = tk.Button(root, command=self.close)

        self.title_label.grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        self.it_button.grid(row=0, column=1, pady=(10, 4))
        self.en_button.grid(row=0, column=2, sticky="e", padx=(0, 10), pady=(10, 4))
        self.step1_label.grid(row=1, column=0, columnspan=3, sticky="w", padx=10, pady=4)
        self.network_label.grid(row=2, column=0, columnspan=3, sticky="w", padx=(30, 10))
        self.status_label.grid(row=3, column=0, columnspan=3, sticky="w", padx=(30, 10))
        self.step2_button.grid(row=4, column=0, columnspan=3, sticky="w", padx=(30, 10), pady=6)
        self.networks_label.grid(row=5, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))
        self.network_list.grid(row=6, column=0, columnspan=3, sticky="w", padx=(30, 10))
        self.scan_label.grid(row=7, column=0, columnspan=3, sticky="w", padx=(30, 10))
        self.password_label.grid(row=8, column=0, sticky="w", padx=(30, 4), pady=4)
        self.password_entry.grid(row=8, column=1, sticky="w", padx=(0, 4))
        self.show_check.grid(row=8, column=2, sticky="w", padx=(0, 10))
        self.configure_button.grid(row=9, column=0, columnspan=3, sticky="w", padx=(30, 10), pady=6)
        self.progress_label.grid(row=10, column=0, columnspan=3, sticky="w", padx=(30, 10))
        self.result_label.grid(row=11, column=0, columnspan=3, sticky="w", padx=(30, 10), pady=(4, 4))
        self.note_label.grid(row=12, column=0, columnspan=3, sticky="w", padx=10, pady=(8, 4))
        self.close_button.grid(row=13, column=2, sticky="e", padx=10, pady=(4, 10))

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
        self.close_button.config(text=text["close_button"])
        self._apply_status()
        self._render_networks()
        self._refresh_note()

    def _device_found(self) -> bool:
        """True when the last device check found the device."""
        return self.status is not None and self.status.state == device_check.STATE_FOUND

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
        found = self._device_found()
        self.step2_button.config(state=tk.NORMAL if found else tk.DISABLED)
        self.network_label.config(text=text["network_name"].format(mac6=self.mac6))
        self.status_label.config(text=line)
        self._refresh_configure_button()

    def _refresh_configure_button(self) -> None:
        """Configure is possible only when the device is found and no configuration is running."""
        enabled = self._device_found() and not self.configuring
        self.configure_button.config(state=tk.NORMAL if enabled else tk.DISABLED)

    def _render_networks(self) -> None:
        """Put the network, password, progress and result texts in the current language."""
        text = messages.tr(self.lang)
        self.networks_label.config(text=text["networks_title"])
        self.scan_label.config(text=text[self.scan_key] if self.scan_key else "")
        self.password_label.config(text=text["password_label"])
        self.show_check.config(text=text["show_password"])
        self.configure_button.config(text=text["configure_button"])
        self.progress_label.config(text=text[self.progress_key] if self.progress_key else "")
        self.result_label.config(text=self._result_text(text))

    def _result_text(self, text: dict[str, str]) -> str:
        """The final message: the device address when configured, else the error message."""
        if not self.result_key:
            return ""
        if self.result_key == "done_on_network":
            return text[self.result_key].format(ip=self.result_ip)
        return text[self.result_key]

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
        """Tk thread: apply the newest device statuses and the calls of the workers, then schedule the next look."""
        changed = False
        while True:
            try:
                self.status = self.updates.get_nowait()
            except queue.Empty:
                break
            changed = True
        if changed:
            self._apply_status()
            if self._device_found() and not self.scan_started:
                self._start_scan()
        while True:
            try:
                call = self.calls.get_nowait()
            except queue.Empty:
                break
            call()
        self.root.after(DRAIN_INTERVAL_MS, self._drain_updates)

    def _start_scan(self) -> None:
        """Search the networks in a worker thread; the list is filled on the Tk thread."""
        self.scan_started = True
        self.scan_key = "scanning_networks"
        self._render_networks()
        threading.Thread(target=self._scan_networks, daemon=True).start()

    def _scan_networks(self) -> None:
        """Worker thread: read the networks of the device and hand them to the Tk thread."""
        networks = wifi_survey.read_survey(_device_connection)
        self.calls.put(lambda: self._show_networks(networks))

    def _show_networks(self, networks: list[wifi_survey.Network]) -> None:
        """Tk thread: fill the list; row i of the list is networks[i]."""
        self.networks = networks
        self.network_list.delete(0, tk.END)
        for net in networks:
            self.network_list.insert(tk.END, net.essid)
        if networks:
            self.network_list.selection_set(0)
            self.scan_key = ""
        else:
            self.scan_key = "no_networks"
        self._render_networks()

    def _selected_network(self) -> wifi_survey.Network | None:
        """The network chosen in the list, or None when nothing is chosen."""
        picked = self.network_list.curselection()
        if not picked or picked[0] >= len(self.networks):
            return None
        return self.networks[picked[0]]

    def _toggle_password(self) -> None:
        """Show the password as text, or hide it again, following the checkbox."""
        self.password_entry.config(show="" if self.show_var.get() else PASSWORD_MASK)

    def _on_configure(self) -> None:
        """Start the configuration of the chosen network; the password is passed on and never stored."""
        text = messages.tr(self.lang)
        net = self._selected_network()
        if net is None:
            return
        password = self.password_entry.get()
        if net.security != wifi_survey.SEC_NONE and not password:
            self._set_error(text["password_required"])
            return
        self._set_error("")
        self.configuring = True
        self.progress_key = "progress_pending"
        self.result_key = ""
        self.result_ip = ""
        self._refresh_configure_button()
        self._render_networks()
        threading.Thread(target=self._run_configure, args=(net, password), daemon=True).start()

    def _run_configure(self, net: wifi_survey.Network, password: str) -> None:
        """Worker thread: send the setup form and follow its steps; the Tk thread gets every change through self.calls."""

        def on_progress(step: wifi_configure.SetupStep) -> None:
            self.calls.put(lambda: self._show_progress(step.step))

        result = wifi_configure.configure(
            _device_connection,
            essid=net.essid,
            security=net.security,
            wpa_key=password,
            on_progress=on_progress,
        )
        self.calls.put(lambda: self._finish_configure(result))

    def _show_progress(self, step: str) -> None:
        """Tk thread: show the progress line of a step; an error step is shown at the end."""
        key = PROGRESS_KEYS.get(step)
        if key is None:
            return
        self.progress_key = key
        self._render_networks()

    def _finish_configure(self, result: wifi_configure.ConfigureResult) -> None:
        """Tk thread: show the final message, with the device address when the configuration worked."""
        self.configuring = False
        self.progress_key = ""
        if result.ok:
            self.result_key = "done_on_network"
            self.result_ip = result.ip
        else:
            self.result_key = "config_error"
            self.result_ip = ""
        self._refresh_configure_button()
        self._render_networks()

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

    def close(self) -> None:
        """Stop the device check and the bridge, then close the window (close button and window close)."""
        self.stop_polling.set()
        if self.bridge is not None:
            self.bridge.stop()
            self.bridge = None
        self.root.destroy()


def _set_icon(root: tk.Tk) -> None:
    """Set the program icon of the window. A missing or unusable icon never stops the program."""
    path = icon.icon_path()
    if path is None:
        return
    try:
        root.iconbitmap(default=str(path))
    except tk.TclError:
        # the icon is cosmetic: the window opens without it
        pass


def run() -> None:
    """Open the window and run it until it is closed."""
    root = tk.Tk()
    _set_icon(root)
    SetupWindow(root).start()
    root.mainloop()
