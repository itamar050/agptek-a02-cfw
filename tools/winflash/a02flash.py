#!/usr/bin/env python3
"""A02 Flasher for Windows: installs the new UI (or the stock firmware) over USB recovery mode.

This is a Windows front end for the A02-OS USB flash procedure (newui/tools/flash/adfu_flash.py,
verified on an AGPTEK A02 on 2026-09-28), driving `actions_dump.exe` (libusb):

  1/7 load the USB loader (adfus) into the player's RAM
  2/7 hardware scan -> must report the NAND chip A02-OS was verified on, else STOP
  3/7 load the vendor flash driver (fwscf651) + chip record
  4/7 read the current firmware header (keeps this unit's serial / capacity fields)
  5/7 write the firmware area only (boot records are never touched)
  6/7 finalize
  7/7 read the whole firmware area back and compare, BEFORE anything reboots

`check` runs steps 1-4 with a driver whose erase/program functions are disabled: it cannot
change the flash. Use it first to confirm the USB driver and the player are OK.

Layout (next to the .exe): data/actions_dump.exe, data/adfus.bin, data/nandhwsc.bin,
data/fwscf651.bin, data/fwscf651-readonly.bin, data/a02.afi, data/newui.lfi
"""
import re
import struct
import subprocess
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
HERE = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
if not FROZEN:   # running from a checkout: use the vendored A02-OS flash library
    sys.path.insert(0, str(HERE.parents[1] / "newui/tools/flash"))
import a02fw  # noqa: E402
import adfu_prep  # noqa: E402

DATA = HERE / "data"
STOCK_FWSC_SHA = "93c4686260826e635babb16226e1a348a971892ef09fcdaaa4f70bfde4d7bcf9"
NAND_ID8 = bytes.fromhex("8984643ca50c0000")
PRESERVE = [(0x28, 0x38), (0x4F, 0x80)]


class Stop(Exception):
    pass


def need(name):
    p = DATA / name
    if not p.exists():
        raise Stop("missing %s (keep the data folder next to the program)" % p)
    return p


def run(args, what):
    exe = need("actions_dump.exe" if sys.platform == "win32" else "actions_dump")
    cmd = [str(exe), "--wait", "20", "chip", "2157", "timeout", "60000"] + [str(a) for a in args]
    print("\n== %s" % what)
    r = subprocess.run(cmd, cwd=str(DATA), capture_output=True, text=True, timeout=900)
    out = r.stdout + r.stderr
    tail = out.strip().splitlines()[-6:]
    if tail:
        print("   " + "\n   ".join(tail))
    if r.returncode or "failed" in out or "unexpected" in out:
        raise Stop("%s did not complete." % what)
    return out


def hexdump_bytes(out):
    data = bytearray()
    for line in out.splitlines():
        m = re.match(r"^((?:[0-9a-f]{2} ){1,16})\s*\|", line)
        if m:
            data += bytes.fromhex(m.group(1).replace(" ", ""))
    return bytes(data)


def prepare(work, readonly):
    db = a02fw.FirmwareDB(str(need("a02.afi")))
    if a02fw.sha256(need("a02.afi").read_bytes()) != a02fw.STOCK_AFI_SHA:
        raise Stop("a02.afi is not the official firmware database")
    stock_lfi = a02fw.build_lfi(db)
    lfi_sectors = len(stock_lfi) // 512
    rec, ftype = adfu_prep.search_id(dict(db.files("NAND_ID"))["flash_id.bin"], NAND_ID8)
    brec, res = adfu_prep.brec_image(db, lfi_sectors, ftype)
    brec_cap = (len(brec) + len(res)) // 512
    if ftype != 0xF651:
        raise Stop("unexpected flash type 0x%x" % ftype)
    if readonly:
        drv = need("fwscf651-readonly.bin").read_bytes()
    else:
        drv = need("fwscf651.bin").read_bytes()
        if a02fw.sha256(drv) != STOCK_FWSC_SHA:
            raise Stop("fwscf651.bin is not the stock flash driver")
    (work / "nandinfo.bin").write_bytes(rec)
    (work / "fwsc.bin").write_bytes(adfu_prep.fwsc_image(db, drv, brec_cap, lfi_sectors))
    vram = bytearray(512)
    vram[510:512] = b"\xaa\xbb"
    (work / "vram_last.bin").write_bytes(vram)
    return db, stock_lfi


def connect(work, n):
    run(["simple_switch", "0x118000", need("adfus.bin")], "1/%d load the USB loader" % n)
    hw = hexdump_bytes(run(["write_mem", "0x11e000", "0", "0", need("nandhwsc.bin"),
                            "exec_ret", "0x11e000", "-1"], "2/%d hardware scan" % n))
    if hw[0:2] != b"HW":
        raise Stop("unexpected hardware scan answer %s" % hw[:32].hex())
    if hw[16:21] != a02fw.NAND_ID:
        raise Stop("this player has NAND %s; the flasher only supports %s (the chip A02-OS was "
                   "verified on). Nothing was written." % (hw[16:21].hex(), a02fw.NAND_ID.hex()))
    if int.from_bytes(hw[0x18:0x1C], "little") != adfu_prep.NAF_PARAM_ADDR:
        raise Stop("unexpected chip-record address in the hardware scan")
    print("   NAND %s: supported" % hw[16:21].hex())
    st = hexdump_bytes(run(["write_mem", hex(0x11e000), "0", "0", work / "fwsc.bin",
                            "write_mem", hex(adfu_prep.NAF_PARAM_ADDR), "0", "0", work / "nandinfo.bin",
                            "exec_ret", "0x11e200", "-1"], "3/%d flash driver" % n))
    if st[6:12] != b"NAFWSC":
        raise Stop("flash driver status %s" % st[:32].hex())
    run(["read_lfi", "0", "0x200", work / "device_head.bin"], "4/%d read the current firmware header" % n)
    dev = (work / "device_head.bin").read_bytes()
    if struct.unpack_from("<I", dev, 0)[0] != a02fw.LFI_MAGIC:
        raise Stop("the player's firmware header has no LFI magic (%s)" % dev[:16].hex())
    return dev


def flash(work, image, dev):
    image = bytearray(image)
    for s, e in PRESERVE:
        image[s:e] = dev[s:e]
    struct.pack_into("<H", image, 0x1FE, a02fw.sum16(bytes(image[:0x1FE])))
    a02fw.parse_lfi(bytes(image))
    (work / "image.bin").write_bytes(image)
    run(["blk_size", "0x4000", "write_flash", "0xc0000000", "0", "0", work / "image.bin"],
        "5/7 WRITE the firmware area (about a minute)")
    run(["write_flash", "0xff000000", "0", "0", work / "vram_last.bin"], "6/7 finalize")
    run(["blk_size", "0x4000", "read_lfi", "0", hex(len(image)), work / "readback.bin"],
        "7/7 read back and compare")
    back = (work / "readback.bin").read_bytes()
    bad = [i // 512 for i in range(0, len(image), 512) if back[i:i + 512] != image[i:i + 512]]
    if bad:
        print("\nVERIFY FAILED: %d sectors differ (first %s)." % (len(bad), bad[:8]))
        print("Leave the player plugged in. Do NOT switch it off. Run this program again.")
        return False
    print("\nVERIFIED: all %d sectors read back identical." % (len(image) // 512))
    return True


MENU = """
A02 Flasher  (new UI based on A02-OS; stock firmware by AGPTEK)

Before you start:
  - Zadig must have installed the WinUSB driver for the player in recovery mode (see README.txt).
  - Put the player in recovery mode: connect it by USB, then hold PLAY about 10 seconds
    (the screen stays dark).

  1  Check the connection (read-only, cannot change anything)
  2  Install the NEW UI
  3  Restore the STOCK AGPTEK firmware
  q  Quit
"""


def main():
    work = HERE / "work"
    work.mkdir(exist_ok=True)
    choice = sys.argv[1] if len(sys.argv) > 1 else None
    if not choice:
        print(MENU)
        choice = input("Choose 1, 2, 3 or q: ").strip().lower()
    choice = {"check": "1", "newui": "2", "stock": "3"}.get(choice, choice)
    if choice not in ("1", "2", "3"):
        return 0
    try:
        if choice == "1":
            prepare(work, readonly=True)
            connect(work, 4)
            print("\nCONNECTION OK: the player answered and its flash chip is supported. Nothing was written.")
            print("Now switch the player OFF, unplug it, plug it back in and run this again to install.")
            return 0
        db, stock_lfi = prepare(work, readonly=False)
        if choice == "2":
            image = need("newui.lfi").read_bytes()
            label = "the NEW UI"
        else:
            image = stock_lfi
            label = "the STOCK firmware"
        a02fw.parse_lfi(image)
        if len(image) != len(stock_lfi):
            raise Stop("image size %d differs from the stock size %d" % (len(image), len(stock_lfi)))
        if (len(sys.argv) <= 2 or sys.argv[2] != "--yes") and \
                input("\nThis will write %s to the player. Type YES to continue: " % label).strip() != "YES":
            print("Cancelled. Nothing was written.")
            return 0
        dev = connect(work, 7)
        if not flash(work, image, dev):
            return 1
        print("Done. Switch the player OFF, unplug it, then switch it ON.")
        if choice == "2":
            print("The new UI starts at power-on. Hold M while switching on to start the stock firmware.")
        return 0
    except Stop as e:
        print("\nSTOPPED: %s" % e)
        print("Switch the player OFF, unplug it, plug it back in, and try again.")
        return 1


if __name__ == "__main__":
    rc = main()
    if FROZEN and len(sys.argv) <= 1:
        input("\nPress Enter to close.")
    sys.exit(rc)
