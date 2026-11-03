"""
Parser for the A02's RU3 ".sty" skin/resource containers.

Layout (all little-endian), as reverse-engineered from the 20241019 firmware:

  0x00  "RU3" + 1 byte          magic
  0x04  u32                     total resource count (sum of section counts)
  0x08  u32                     (unknown; varies per file)
  0x0C  "V100"                  version tag
  0x10  section descriptors, 16 bytes each, until an all-zero record:
          u32 table_off         file offset of this section's entry table
          u16 count             number of entries
          u8  type              'P' = picture, 'S' = string table, 'X' = XML descriptor
          ...                   (remaining bytes unknown)
  table entries, 16 bytes each:
          u32 data_off          file offset of the resource data
          u32 data_len          length in bytes
          u16 fmt               picture: 2 = raw 16bpp RGB565 (width*height*2 bytes)
          u16 a, u16 b          picture: width, height
          u16 c                 (string table: index)
          u16 pad

Usage:
  python3 tools/sty.py info  FILE.sty          # list sections and entries
  python3 tools/sty.py dump  FILE.sty OUTDIR   # write each picture as PNG (needs Pillow)
"""
import struct
import sys
import os


class Entry:
    def __init__(self, sec_type, index, off, length, fmt, a, b, c):
        self.sec_type, self.index = sec_type, index
        self.off, self.length, self.fmt = off, length, fmt
        self.a, self.b, self.c = a, b, c

    @property
    def is_rgb565(self):
        return self.sec_type == "P" and self.fmt == 2 and self.a * self.b * 2 == self.length


def parse(data: bytes):
    assert data[:3] == b"RU3", "not an RU3 container"
    assert data[12:16] == b"V100", "unexpected version tag"
    sections = []
    pos = 0x10
    while True:
        table_off, count, typ = struct.unpack_from("<IHB", data, pos)
        if table_off == 0 and count == 0:
            break
        sections.append((chr(typ), table_off, count))
        pos += 16
    entries = []
    for typ, table_off, count in sections:
        for i in range(count):
            off, length, fmt, a, b, c = struct.unpack_from("<IIHHHH", data, table_off + i * 16)
            entries.append(Entry(typ, i, off, length, fmt, a, b, c))
    return sections, entries


def rgb565_to_rgb(px: int):
    r, g, b = (px >> 11) & 0x1F, (px >> 5) & 0x3F, px & 0x1F
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)


def rgb_to_rgb565(r: int, g: int, b: int) -> int:
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def picture_to_image(data: bytes, e: Entry):
    from PIL import Image
    w, h = e.a, e.b
    px = struct.unpack_from(f"<{w * h}H", data, e.off)
    img = Image.new("RGB", (w, h))
    img.putdata([rgb565_to_rgb(p) for p in px])
    return img


def main(argv):
    cmd, path = argv[1], argv[2]
    data = open(path, "rb").read()
    sections, entries = parse(data)
    if cmd == "info":
        print("sections:", sections)
        for e in entries:
            tag = "rgb565" if e.is_rgb565 else ""
            print(f"{e.sec_type}{e.index:03d} off=0x{e.off:06x} len={e.length:7d} "
                  f"fmt={e.fmt} a={e.a} b={e.b} c={e.c} {tag}")
    elif cmd == "dump":
        out = argv[3]
        os.makedirs(out, exist_ok=True)
        for e in entries:
            if e.is_rgb565:
                picture_to_image(data, e).save(os.path.join(out, f"P{e.index:03d}_{e.a}x{e.b}.png"))


if __name__ == "__main__":
    main(sys.argv)
