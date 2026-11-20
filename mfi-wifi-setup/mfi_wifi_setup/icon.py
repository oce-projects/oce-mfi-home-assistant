"""Program icon of mfi-wifi-setup: where the icon file is found.

Standard library only, no tkinter: the path can be tested offline. The .exe built
by PyInstaller reads the icon from its temporary folder (sys._MEIPASS); from the
source it is mfi-wifi-setup/icon.ico.
"""
from __future__ import annotations

import pathlib
import sys

ICON_NAME = "icon.ico"


def icon_path() -> pathlib.Path | None:
    """The path of the icon file, or None when the file is not there."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        path = pathlib.Path(sys._MEIPASS) / ICON_NAME
    else:
        path = pathlib.Path(__file__).resolve().parent.parent / ICON_NAME
    return path if path.is_file() else None
