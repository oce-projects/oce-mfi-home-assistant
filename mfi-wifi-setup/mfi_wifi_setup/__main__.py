"""Start mfi-wifi-setup with: python -m mfi_wifi_setup (run from the mfi-wifi-setup folder).

The tkinter import stays inside window.py, so importing the package never loads tkinter.
"""
from .window import run

if __name__ == "__main__":
    run()
