"""Generates the icons and logos of the add-ons as PNG files, and the program icon as an ICO file.

Standard library only (zlib, struct, pathlib). No network. The output is
deterministic: the same code always writes the same bytes.

PNG format: 8-bit RGBA (colour type 6), only the IHDR, IDAT and IEND chunks,
no text or date chunks. This script writes only filter type 0 (None) on every
scanline; no other filter is used.

Run from the repository root:
    python3 tools/make_icons.py
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUPERSAMPLE = 4  # 4x4 samples per pixel, averaged
GRID = 24.0  # the icon is drawn on a 24-unit grid
CORNER_RADIUS = 2.22

ICONS = [
    ("mfi-server/icon.png", 128, 128, (30, 136, 229), (255, 255, 255), (0, 0, 128)),
    ("mfi-server/logo.png", 250, 100, (30, 136, 229), (255, 255, 255), (75, 0, 100)),
    ("mfi-controller/icon.png", 128, 128, (120, 144, 156), (255, 255, 255), (0, 0, 128)),
    ("mfi-controller/logo.png", 250, 100, (120, 144, 156), (255, 255, 255), (75, 0, 100)),
]

# (path, sizes, background, drawing colour). Kept apart from ICONS, which the server tests parse.
ICO_FILES = [
    ("mfi-wifi-setup/icon.ico", (16, 32, 48, 256), (67, 160, 71), (255, 255, 255)),
]


def _chunk(kind: bytes, data: bytes) -> bytes:
    crc = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)


def _in_circle(gx: float, gy: float, cx: float, cy: float, radius: float) -> bool:
    return (gx - cx) ** 2 + (gy - cy) ** 2 <= radius ** 2


def _in_rounded_square(gx: float, gy: float) -> bool:
    # the square goes from 2 to 22 on both axes, corners rounded by CORNER_RADIUS
    cx = min(max(gx, 2 + CORNER_RADIUS), 22 - CORNER_RADIUS)
    cy = min(max(gy, 2 + CORNER_RADIUS), 22 - CORNER_RADIUS)
    return _in_circle(gx, gy, cx, cy, CORNER_RADIUS)


def _sample(gx: float, gy: float, bg: tuple, fg: tuple) -> tuple:
    # shapes from the top: small background eyes, foreground disc, rounded square
    for cx in (7.5, 16.5):
        if _in_circle(gx, gy, cx, 12.0, 1.5):
            return (*bg, 255)
    if _in_circle(gx, gy, 12.0, 12.0, 8.0):
        return (*fg, 255)
    if _in_rounded_square(gx, gy):
        return (*bg, 255)
    return (0, 0, 0, 0)


def _pixel(px: int, py: int, icon_box: tuple, bg: tuple, fg: tuple) -> bytes:
    x0, y0, side = icon_box
    total = [0, 0, 0, 0]
    for j in range(SUPERSAMPLE):
        for i in range(SUPERSAMPLE):
            sx = px + (i + 0.5) / SUPERSAMPLE
            sy = py + (j + 0.5) / SUPERSAMPLE
            gx = (sx - x0) / side * GRID
            gy = (sy - y0) / side * GRID
            sample = _sample(gx, gy, bg, fg)
            total = [t + s for t, s in zip(total, sample)]
    n = SUPERSAMPLE * SUPERSAMPLE
    return bytes((t + n // 2) // n for t in total)


def render_png(
    width: int,
    height: int,
    bg: tuple[int, int, int],
    fg: tuple[int, int, int],
    icon_box: tuple[int, int, int],
) -> bytes:
    rows = bytearray()
    for py in range(height):
        rows.append(0)  # filter type 0 (None): the only filter this script writes
        for px in range(width):
            rows += _pixel(px, py, icon_box, bg, fg)
    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (
        PNG_SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + _chunk(b"IEND", b"")
    )


def render_ico(sizes: tuple[int, ...], bg: tuple[int, int, int], fg: tuple[int, int, int]) -> bytes:
    """ICO file with one PNG image per size: 6-byte header, one 16-byte entry per image, then the PNGs."""
    for size in sizes:
        if not 1 <= size <= 256:
            raise ValueError(f"icon size {size} is outside 1..256")
    pngs = [render_png(size, size, bg, fg, (0, 0, size)) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    entries = bytearray()
    offset = 6 + 16 * len(sizes)
    for size, png in zip(sizes, pngs):
        dim = 0 if size == 256 else size  # 0 stands for 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
    return header + bytes(entries) + b"".join(pngs)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    for relpath, width, height, bg, fg, icon_box in ICONS:
        (root / relpath).write_bytes(render_png(width, height, bg, fg, icon_box))
    for relpath, sizes, bg, fg in ICO_FILES:
        (root / relpath).write_bytes(render_ico(sizes, bg, fg))


if __name__ == "__main__":
    main()
