#!/usr/bin/env python3
"""Render a mockup of the new UI's screens (newui/) on the host, without the device.

Re-implements the drawing calls from newui/os/src/ui.c and main.c (header, rows, hints,
Now Playing) in Python, using the real 5x7 font table parsed from font.c and the theme
colors from ui.c. Sample data (battery, card size, track names) is made up.

  python3 tools/preview_ui.py OUT.png [--theme 0..4] [--scale 3]
"""
import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SRC = Path(__file__).resolve().parents[1] / "newui/os/src"
LCD_W, LCD_H = 128, 160
HDR_H, HINT_H, ROW_H = 14, 12, 15
ROW_Y0 = HDR_H + 2
ROWS = (LCD_H - HDR_H - HINT_H - 2) // ROW_H


def load_font():
    txt = (SRC / "font.c").read_text()
    body = txt[txt.index("font5x7"):txt.index("};")]
    glyphs = re.findall(r"\{(0x[0-9a-f]{2}(?:,0x[0-9a-f]{2}){4})\}", body)
    assert len(glyphs) == 64
    return [[int(v, 16) for v in g.split(",")] for g in glyphs]


def load_themes():
    txt = (SRC / "ui.c").read_text()
    themes = []
    for m in re.finditer(r'\{ "(\w+)",((?:\s*RGB\([^)]*\),?)+)\s*\}', txt):
        cols = [tuple(int(v, 16) for v in c.split(",")) for c in re.findall(r"RGB\(([^)]*)\)", m.group(2))]
        keys = ["bg", "surface", "text", "dim", "accent", "sel", "sel_text", "line", "rec"]
        themes.append(dict(name=m.group(1), **dict(zip(keys, cols))))
    return themes


FONT = load_font()


class Screen:
    def __init__(self, t):
        self.T = t
        self.img = Image.new("RGB", (LCD_W, LCD_H), t["bg"])
        self.px = self.img.load()

    def rect(self, x, y, w, h, c):
        for yy in range(max(0, y), min(LCD_H, y + h)):
            for xx in range(max(0, x), min(LCD_W, x + w)):
                self.px[xx, yy] = c

    def char(self, x, y, ch, scale, fg, bg):
        if "a" <= ch <= "z":
            ch = ch.upper()
        if not (0x20 <= ord(ch) <= 0x5f):
            ch = "?"
        g = FONT[ord(ch) - 0x20]
        w, h = 6 * scale, 8 * scale
        if x + w > LCD_W or y + h > LCD_H:
            return
        for row in range(h):
            for col in range(w):
                c, r = col // scale, row // scale
                self.px[x + col, y + row] = fg if (c < 5 and r < 7 and g[c] >> r & 1) else bg

    def text(self, x, y, s, scale, fg, bg):
        for i, ch in enumerate(s):
            self.char(x + i * 6 * scale, y, ch, scale, fg, bg)

    # --- ui.c widgets ---
    def battery(self, x, y, level=4):
        T = self.T
        c = T["rec"] if level <= 1 else T["dim"]
        fill = level * 7 // 5
        self.rect(x, y, 11, 1, c); self.rect(x, y + 6, 11, 1, c)
        self.rect(x, y, 1, 7, c); self.rect(x + 10, y, 1, 7, c)
        self.rect(x + 11, y + 2, 1, 3, c)
        self.rect(x + 2, y + 2, fill, 3, c)

    def header(self, title, playing=False):
        T = self.T
        self.rect(0, 0, LCD_W, HDR_H - 1, T["bg"])
        self.text(5, 3, title, 1, T["accent"], T["bg"])
        if playing:
            self.text(LCD_W - 26, 3, ">", 1, T["accent"], T["bg"])
        self.battery(LCD_W - 17, 3)
        self.rect(0, HDR_H - 1, LCD_W, 1, T["line"])

    def hints(self, left, right):
        T = self.T
        y = LCD_H - HINT_H
        self.rect(0, y, LCD_W, 1, T["line"])
        self.text(5, y + 3, left, 1, T["dim"], T["bg"])
        self.text(LCD_W - 5 - 6 * len(right), y + 3, right, 1, T["dim"], T["bg"])

    def row(self, slot, icon, label, meta, selected):
        T = self.T
        y = ROW_Y0 + slot * ROW_H
        bg = T["sel"] if selected else T["bg"]
        fg = T["sel_text"] if selected else T["text"]
        self.rect(3, y, LCD_W - 6, ROW_H, bg)
        self.text(7, y + 4, icon, 1, T["sel_text"] if selected else T["accent"], bg)
        maxch = (LCD_W - 24 - (len(meta) * 6 + 4 if meta else 0)) // 6
        self.text(17, y + 4, label[:maxch], 1, fg, bg)
        if meta:
            self.text(LCD_W - 7 - len(meta) * 6, y + 4, meta, 1, T["sel_text"] if selected else T["dim"], bg)

    def list_screen(self, title, items, sel, hl, hr):
        self.header(title)
        for i, (icon, label, meta) in enumerate(items[:ROWS]):
            self.row(i, icon, label, meta, i == sel)
        self.hints(hl, hr)
        return self


def splash(T):
    s = Screen(T)
    s.text(10, 64, "A02-OS", 3, T["accent"], T["bg"])
    s.text(40, 92, "LOADING", 1, T["dim"], T["bg"])
    return s


def home(T, sel=0):
    return Screen(T).list_screen("A02", [("#", "MUSIC", ""), ("=", "INFO", "")], sel, "M/DN MOVE", "> OPEN")


def info(T):
    items = [("-", "VERSION", "1.0"), ("-", "BATTERY", "4/5"), ("-", "CARD FREE", "21.4G"),
             ("-", "CARD SIZE", "29.7G"), ("-", "BACKLIGHT", "7"), ("-", "BLUETOOTH", "N/A")]
    return Screen(T).list_screen("INFO", items, 4, "< BACK", "> CHANGE")


def music(T):
    items = [("+", "ALBUMS", ""), ("+", "PODCASTS", ""), (" ", "BOHEMIAN RHAPSODY", ""),
             (" ", "CLAIR DE LUNE", ""), (" ", "HOTEL CALIFORNIA", ""), (" ", "SO WHAT", ""),
             (" ", "TAKE FIVE", ""), (" ", "WONDERWALL", "")]
    return Screen(T).list_screen("MUSIC", items, 2, "< BACK", "> PLAY")


def now_playing(T):
    s = Screen(T)
    s.header("NOW PLAYING", playing=True)
    vx, vy, vw, vh = 6, 20, LCD_W - 12, 50
    s.rect(vx, vy, vw, vh, T["surface"])
    nb, bw, gap = 14, 5, 3
    x0 = vx + (vw - (nb * bw + (nb - 1) * gap)) // 2
    base = vy + vh - 4
    levels = [30, 38, 26, 34, 22, 28, 18, 24, 14, 20, 12, 16, 9, 6]
    for i, h in enumerate(levels):
        s.rect(x0 + i * (bw + gap), base - h, bw, h, T["accent"] if i % 4 == 0 else T["dim"])
    s.text(6, 76, "BOHEMIAN RHAPSODY"[:19], 1, T["text"], T["bg"])
    s.text(6, 100, "QUEEN", 1, T["dim"], T["bg"])
    s.rect(6, 125, LCD_W - 12, 3, T["surface"])
    s.rect(6, 125, (LCD_W - 12) * 83 // 355, 3, T["accent"])
    s.text(6, 131, "1:23", 1, T["dim"], T["bg"])
    s.text(LCD_W - 6 - 6 * 4, 131, "5:55", 1, T["dim"], T["bg"])
    s.hints("<< >> TRACK", "M/DN VOL")
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--theme", type=int, default=0)
    ap.add_argument("--scale", type=int, default=3)
    a = ap.parse_args()
    T = load_themes()[a.theme]
    shots = [("Boot", splash(T)), ("Home", home(T)), ("Music", music(T)),
             ("Now Playing", now_playing(T)), ("Info", info(T))]
    k, pad, cap = a.scale, 24, 28
    W = len(shots) * (LCD_W * k + pad) + pad
    H = LCD_H * k + pad * 2 + cap
    sheet = Image.new("RGB", (W, H), (40, 40, 44))
    d = ImageDraw.Draw(sheet)
    try:
        f = ImageFont.truetype("DejaVuSans.ttf", 16)
    except OSError:
        f = ImageFont.load_default()
    for i, (name, s) in enumerate(shots):
        x = pad + i * (LCD_W * k + pad)
        d.rectangle([x - 3, pad - 3, x + LCD_W * k + 2, pad + LCD_H * k + 2], fill=(10, 10, 10))
        sheet.paste(s.img.resize((LCD_W * k, LCD_H * k), Image.NEAREST), (x, pad))
        d.text((x + LCD_W * k // 2, pad + LCD_H * k + 8), name, fill=(220, 220, 220), font=f, anchor="mt")
    sheet.save(a.out)
    print("wrote", a.out, "theme", T["name"])


if __name__ == "__main__":
    main()
