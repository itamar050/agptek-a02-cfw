#!/usr/bin/env python3
"""A02 Flasher for Windows: installs the new UI (or the stock firmware) over USB recovery mode.

This is a Windows front end for the A02-OS USB flash procedure (newui/tools/flash/adfu_flash.py,
verified on an AGPTEK A02 with an Intel NAND on 2026-09-28), driving `actions_dump.exe` (libusb).
Like AGPTEK's own tool, it picks the flash driver and boot record for the NAND chip it finds:

  1/7 load the USB loader (adfus) into the player's RAM
  2/7 hardware scan -> NAND ID -> chip record + flash type from FLASH_ID.BIN (vendor SERACH_ID)
      -> flash driver fwscfXXX / boot record brecfXXX for that type (FWSC / BREC tables)
      -> for the new UI: the boot stub must be compatible with that boot record, else STOP
  3/7 load that flash driver + chip record
  4/7 read the current firmware header (keeps this unit's serial / capacity fields)
  5/7 write the firmware area only (boot records are never touched)
  6/7 finalize
  7/7 read the whole firmware area back and compare, BEFORE anything reboots

`check` never writes: it runs the hardware scan and the compatibility checks, and (for the
Intel chip, where a write-disabled driver exists) also reads the firmware header.

Data folder (next to the .exe): actions_dump.exe, libusb-1.0.dll, adfus.bin, nandhwsc.bin,
fwscf651-readonly.bin, a02.afi (official firmware database), newui.lfi
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
PRESERVE = [(0x28, 0x38), (0x4F, 0x80)]
READONLY_TYPE = 0xF651            # the only type with a gate-proven write-disabled driver

# What the boot stub (newui/os/boot/stub.c) needs from the boot record, which is loaded at
# 0x10E900: its NAND read function at 0x11485E and the firmware-base variable 0x20361C.
BREC_BASE = 0x10E900
BREC_READ = 0x11485E
BREC_READ_SIG = bytes([0x2D, 0xE9, 0xFC, 0x47, 0x15, 0x46, 0x89, 0x46])
LFI_BASE_VAR = struct.pack("<I", 0x0020361C)
REF_BREC = "brecf651.bin"         # the boot record the stub was verified with on hardware


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
    tail = out.strip().splitlines()[-3:]
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


def load_db():
    afi = need("a02.afi")
    if a02fw.sha256(afi.read_bytes()) != a02fw.STOCK_AFI_SHA:
        raise Stop("a02.afi is not the official firmware database")
    db = a02fw.FirmwareDB(str(afi))
    return db, a02fw.build_lfi(db)


def by_type(db, table, ftype):
    names = [r[0] for r in db.db.execute("select FileName, NumberD from %s" % table) if r[1] == ftype]
    if len(names) != 1:
        raise Stop("no %s entry for flash type 0x%X" % (table, ftype))
    return names[0], adfu_prep.file_by_key(db, table, names[0])


def stub_compatible(db, brec_name, brec):
    """The stub calls BREC's read function at a fixed address and reads one BREC variable.
    Accept a boot record only if both are exactly where they are in the verified one."""
    off = BREC_READ - BREC_BASE
    ref = adfu_prep.file_by_key(db, "BREC", REF_BREC)
    if brec[off:off + 8] != BREC_READ_SIG:
        return False, "read function not at the expected address"
    span = next((i for i in range(min(len(ref), len(brec)) - off) if ref[off + i] != brec[off + i]), 0)
    refs = [i for i in range(len(ref) - 3) if ref[i:i + 4] == LFI_BASE_VAR]
    if not refs or any(brec[i:i + 4] != LFI_BASE_VAR for i in refs):
        return False, "firmware-base variable referenced differently"
    return True, "%s: read function and firmware-base variable match %s (%d identical bytes)" % (
        brec_name, REF_BREC, span)


def scan(work, n):
    run(["simple_switch", "0x118000", need("adfus.bin")], "1/%d load the USB loader" % n)
    hw = hexdump_bytes(run(["write_mem", "0x11e000", "0", "0", need("nandhwsc.bin"),
                            "exec_ret", "0x11e000", "-1"], "2/%d hardware scan" % n))
    if hw[0:2] != b"HW":
        raise Stop("unexpected hardware scan answer %s" % hw[:32].hex())
    if int.from_bytes(hw[0x18:0x1C], "little") != adfu_prep.NAF_PARAM_ADDR:
        raise Stop("unexpected chip-record address in the hardware scan")
    return hw[16:24]


def identify(db, id8, newui):
    try:
        rec, ftype = adfu_prep.search_id(dict(db.files("NAND_ID"))["flash_id.bin"], id8)
    except ValueError:
        raise Stop("NAND %s is not in AGPTEK's chip table. Nothing was written." % id8[:5].hex())
    fwsc_name, driver = by_type(db, "FWSC", ftype)
    brec_name, brec = by_type(db, "BREC", ftype)
    print("   NAND %s -> flash type 0x%X -> driver %s, boot record %s" % (id8[:5].hex(), ftype, fwsc_name, brec_name))
    ok, why = stub_compatible(db, brec_name, brec)
    print("   new UI boot stub: %s" % ("compatible (" + why + ")" if ok else "NOT compatible: " + why))
    if newui and not ok:
        raise Stop("the new UI's boot stub does not support this chip's boot record. Nothing was written.")
    return rec, ftype, driver


def load_driver(work, db, rec, ftype, driver, stock_lfi, n):
    lfi_sectors = len(stock_lfi) // 512
    brec, res = adfu_prep.brec_image(db, lfi_sectors, ftype)
    brec_cap = (len(brec) + len(res)) // 512
    (work / "nandinfo.bin").write_bytes(rec)
    (work / "fwsc.bin").write_bytes(adfu_prep.fwsc_image(db, driver, brec_cap, lfi_sectors))
    st = hexdump_bytes(run(["write_mem", "0x11e000", "0", "0", work / "fwsc.bin",
                            "write_mem", hex(adfu_prep.NAF_PARAM_ADDR), "0", "0", work / "nandinfo.bin",
                            "exec_ret", "0x11e200", "-1"], "3/%d flash driver" % n))
    if st[6:12] != b"NAFWSC":
        raise Stop("flash driver status %s" % st[:32].hex())
    run(["read_lfi", "0", "0x200", work / "device_head.bin"], "4/%d read the current firmware header" % n)
    dev = (work / "device_head.bin").read_bytes()
    if struct.unpack_from("<I", dev, 0)[0] != a02fw.LFI_MAGIC:
        raise Stop("the player's firmware header has no LFI magic (%s)" % dev[:16].hex())
    print("   firmware header ok")
    return dev


def flash(work, image, dev):
    image = bytearray(image)
    for s, e in PRESERVE:
        image[s:e] = dev[s:e]
    struct.pack_into("<H", image, 0x1FE, a02fw.sum16(bytes(image[:0x1FE])))
    a02fw.parse_lfi(bytes(image))
    (work / "image.bin").write_bytes(image)
    run(["blk_size", "0x4000", "write_flash", "0xc0000000", "0", "0", work / "image.bin"],
        "5/7 WRITE the firmware area (a few minutes)")
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

  1  Check the connection (does not write anything)
  2  Install the NEW UI
  3  Restore the STOCK AGPTEK firmware
  q  Quit
"""


def main():
    work = HERE / "work"
    work.mkdir(exist_ok=True)
    vram = bytearray(512)
    vram[510:512] = b"\xaa\xbb"
    (work / "vram_last.bin").write_bytes(vram)
    choice = sys.argv[1] if len(sys.argv) > 1 else None
    if not choice:
        print(MENU)
        choice = input("Choose 1, 2, 3 or q: ").strip().lower()
    choice = {"check": "1", "newui": "2", "stock": "3"}.get(choice, choice)
    if choice not in ("1", "2", "3"):
        return 0
    try:
        db, stock_lfi = load_db()
        if choice == "1":
            id8 = scan(work, 4)
            rec, ftype, driver = identify(db, id8, newui=False)
            if ftype == READONLY_TYPE:
                ro = need("fwscf651-readonly.bin").read_bytes()
                load_driver(work, db, rec, ftype, ro, stock_lfi, 4)
            else:
                print("\n   (header read skipped: no write-disabled driver for this chip type)")
            print("\nCHECK DONE. Nothing was written.")
            print("Now switch the player OFF, unplug it, plug it back in, enter recovery mode and run this again.")
            return 0
        if choice == "2":
            image, label = need("newui.lfi").read_bytes(), "the NEW UI"
        else:
            image, label = stock_lfi, "the STOCK firmware"
        a02fw.parse_lfi(image)
        if len(image) != len(stock_lfi):
            raise Stop("image size %d differs from the stock size %d" % (len(image), len(stock_lfi)))
        id8 = scan(work, 7)
        rec, ftype, driver = identify(db, id8, newui=(choice == "2"))
        if (len(sys.argv) <= 2 or sys.argv[2] != "--yes") and \
                input("\nThis will write %s to the player. Type YES to continue: " % label).strip() != "YES":
            print("Cancelled. Nothing was written. Switch the player OFF and unplug it.")
            return 0
        dev = load_driver(work, db, rec, ftype, driver, stock_lfi, 7)
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
