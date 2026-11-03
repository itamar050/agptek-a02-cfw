#!/usr/bin/env python3
"""Build UPGRADE.HEX that installs the new UI (newui/, based on A02-OS) with the stock updater.

Install on the player (stock firmware): copy UPGRADE.HEX to the root of the player's disk,
then Tools -> Firmware upgrade. Afterwards the new UI starts at power-on; hold M while
powering on to start the stock firmware instead.

The image is: stock firmware + KER_INIT.BIN replaced by the A02-OS boot stub + A02OS.BIN added,
with unused language tables shrunk so the total stays exactly the stock size (the boot record
rejects any other size). Every check from newui/tools/flash (LFI checksums, stub replay, the
updater's own checks, independent decryption) runs before the file is written.

  A02_VENDOR_DIR=... python3 tools/mk_newui_upgrade.py -o UPGRADE.HEX
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FLASH = REPO / "newui/tools/flash"
sys.path.insert(0, str(FLASH))
import a02fw  # noqa: E402
import mk_a02os_lfi  # noqa: E402
import mkupgrade  # noqa: E402
import paths  # noqa: E402

OS_DIR = REPO / "newui/os"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--output", default="UPGRADE.HEX")
    ap.add_argument("--stub", default=str(OS_DIR / "boot/stub.bin"))
    ap.add_argument("--a02os", default=str(OS_DIR / "a02os.bin"))
    a = ap.parse_args()

    db = a02fw.FirmwareDB(paths.need(paths.stock_afi(), "firmware database", paths.FETCH_HINT))
    stub = Path(a.stub).read_bytes()
    ui = Path(a.a02os).read_bytes()
    add = [("A02OS.BIN", ui)]
    replace = mk_a02os_lfi.make_room(db, {"KER_INIT.BIN": stub}, add)

    # Same LFI the USB installer would write: check it exactly like the boot stub will.
    lfi = a02fw.build_lfi(db, replace=replace, add=add)
    if len(lfi) != a02fw.STOCK_LFI_SIZE:
        sys.exit("REFUSED: image is %d bytes, boot record requires exactly %d" % (len(lfi), a02fw.STOCK_LFI_SIZE))
    orig = dict(db.files("FWIM"))["KER_INIT.BIN"]
    mk_a02os_lfi.check(lfi, stub, ui, orig)
    print("LFI ok: %d sectors, sha256 %s" % (len(lfi) // 512, a02fw.sha256(lfi)))

    # Wrap it for the on-device updater (mkupgrade verifies before writing).
    ns = argparse.Namespace(fw=str(paths.stock_fw()), afi=str(paths.stock_afi()), output=a.output)
    mkupgrade.make(ns, replace=replace, add=add)


if __name__ == "__main__":
    main()
