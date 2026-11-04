#!/usr/bin/env python3
"""Build a firmware file for AGPTEK's Media Product Tool (Windows) that installs the new UI.

The official tool flashes whatever is in the firmware file's database (FileTable): it packs the
FWIM files in table order, each zero-padded to 512 bytes, into the firmware image. So the new UI
goes in as database rows, exactly like the A02-OS flash image (newui/tools/flash/mk_a02os_lfi.py):

  KER_INIT.BIN := newui boot stub (starts the new UI; hold M at power-on for stock)
  A02OS.BIN    := the new UI program (appended as the last FWIM row)
  874L/1253L/1255L/1257L.TBL shrunk (Thai, Greek, Hebrew, Baltic code pages; unused in
  English) so the image keeps exactly the stock size, which the boot record requires.

The modified database must keep the exact plaintext size, so the file can be re-encrypted
with the original RC4 keystream (new = old_cipher ^ old_plain ^ new_plain). Plaintext offset
p sits at file offset p+512 / p+1536 / p+2048 depending on where the 1 KB block A and 512-byte
block B are interleaved (header bytes 0x1ee / 0x1fe), as in Rockbox atjboottool fwu.c.

  python3 tools/mk_newui_fw.py --stock STOCK.fw --plain STOCK.plain \\
      --stub newui/os/boot/stub.bin --ui newui/os/a02os.bin -o OUT.fw

Verify afterwards: atjboottool --fwu -o check OUT.fw && cmp check OUT.fw.plain
"""
import argparse
import shutil
import sqlite3
import struct
import sys
import tempfile
from pathlib import Path

LFI_SECTORS = 0x383F800 // 512       # stock image size; the boot record rejects any other
DONORS = ["874L.TBL", "1253L.TBL", "1255L.TBL", "1257L.TBL"]
UI_NAME = "A02OS.BIN"                # the name the boot stub looks for
UI_MAX = 0x10000                     # stub limit (loads at 0x120000, must stay below 0x130000)
LFI_DIR_MAX = 240


def secs(n):
    return (n + 511) // 512


def pad512(b):
    return b + b"\0" * (-len(b) % 512)


def cipher_offset(p, offA, offB):
    if p < offA:
        return p + 512
    if p < offA + offB:
        return p + 512 + 1024
    return p + 2048


def fwim_rows(db):
    return db.execute("select rowid, FileName, File from FileTable where Keyword='FWIM' order by rowid").fetchall()


def check_image(db, stub, ui, orig_ker_init):
    """Replay what the flash tool builds and what the boot stub checks."""
    rows = fwim_rows(db)
    names = [r[1] for r in rows]
    if len(rows) > LFI_DIR_MAX:
        raise ValueError("too many files for the image directory")
    total = 16 + sum(secs(len(r[2])) for r in rows)
    if total != LFI_SECTORS:
        raise ValueError("image would be %d sectors, boot record requires %d" % (total, LFI_SECTORS))
    for k in ("KER_TEXT.BIN", "KER_DATA.BIN", "KER_INIT.BIN"):
        if names.index(k) >= 16:
            raise ValueError("%s not in the first directory sector" % k)
    blobs = {r[1]: r[2] for r in rows}
    if blobs["KER_INIT.BIN"] != stub:
        raise ValueError("KER_INIT.BIN is not the stub")
    if stub[0x800:0x800 + len(orig_ker_init)] != orig_ker_init:
        raise ValueError("stub does not carry the original KER_INIT.BIN at +0x800")
    if names.count(UI_NAME) != 1 or blobs[UI_NAME] != ui:
        raise ValueError("%s missing, duplicated or wrong" % UI_NAME)
    if len(pad512(ui)) > UI_MAX:
        raise ValueError("%s is %d bytes, stub limit is %d" % (UI_NAME, len(pad512(ui)), UI_MAX))
    lens = db.execute("select count(*) from FileTable where FileLength != length(File)").fetchone()[0]
    if lens:
        raise ValueError("FileLength column out of sync")
    ok = db.execute("pragma integrity_check").fetchone()[0]
    if ok != "ok":
        raise ValueError("database integrity: %s" % ok)
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stock", required=True, help="official encrypted firmware file")
    ap.add_argument("--plain", required=True, help="its decryption (atjboottool --fwu)")
    ap.add_argument("--stub", required=True)
    ap.add_argument("--ui", required=True)
    ap.add_argument("-o", "--output", required=True)
    a = ap.parse_args()

    cipher = bytearray(Path(a.stock).read_bytes())
    old_plain = Path(a.plain).read_bytes()
    stub = Path(a.stub).read_bytes()
    ui = Path(a.ui).read_bytes()
    if len(cipher) != len(old_plain) + 2048:
        sys.exit("REFUSED: --plain is not the decryption of --stock")
    offA, offB = 512 * (1 + (cipher[0x1EE] & 15)), 512 * (1 + (cipher[0x1FE] & 15))

    with tempfile.TemporaryDirectory() as td:
        work = Path(td) / "fw.db"
        shutil.copyfile(a.plain, work)
        db = sqlite3.connect(work, isolation_level=None)
        db.execute("pragma journal_mode=memory")
        rows = {r[1]: r for r in fwim_rows(db)}
        orig_ker_init = rows["KER_INIT.BIN"][2]

        grow = secs(len(stub)) - secs(len(orig_ker_init)) + secs(len(ui))
        shrink = {}
        for d in DONORS:
            if grow <= 0:
                break
            have = secs(len(rows[d][2]))
            take = min(grow, have - 1)
            shrink[d] = rows[d][2][:(have - take) * 512]
            grow -= take
        if grow > 0:
            sys.exit("REFUSED: not enough donor space (%d sectors short)" % grow)

        db.execute("begin")
        for name, blob in [("KER_INIT.BIN", stub)] + list(shrink.items()):
            db.execute("update FileTable set File=?, FileLength=? where Keyword='FWIM' and FileName=?",
                       (blob, len(blob), name))
        db.execute("insert into FileTable(Keyword, FileName, FileLength, File) values('FWIM', ?, ?, ?)",
                   (UI_NAME, len(ui), ui))
        db.execute("insert into FileAttribute(Keyword, FileName, FilePath, FileTime) "
                   "select 'FWIM', ?, 'newui\\' || ?, FileTime from FileAttribute where FileName='KER_INIT.BIN'",
                   (UI_NAME, UI_NAME))
        db.execute("commit")
        try:
            total = check_image(db, stub, ui, orig_ker_init)
        except ValueError as e:
            sys.exit("REFUSED: %s" % e)
        db.close()

        new_plain = work.read_bytes()
        if len(new_plain) > len(old_plain):
            sys.exit("REFUSED: database grew by %d bytes; cannot keep the encrypted size"
                     % (len(new_plain) - len(old_plain)))
        if len(new_plain) < len(old_plain):   # SQLite never shrinks without VACUUM; be safe
            new_plain += bytes(len(old_plain) - len(new_plain))

    changed = 0
    for p in range(len(old_plain)):
        if old_plain[p] != new_plain[p]:
            cipher[cipher_offset(p, offA, offB)] ^= old_plain[p] ^ new_plain[p]
            changed += 1
    Path(a.output).write_bytes(cipher)
    Path(a.output + ".plain").write_bytes(new_plain)
    for d, b in shrink.items():
        print("  room: %s %d -> %d bytes" % (d, len(rows[d][2]), len(b)))
    print("image %d sectors (stock size); KER_INIT.BIN = stub (%d bytes); %s = %d bytes"
          % (total, len(stub), UI_NAME, len(ui)))
    print("%d bytes changed -> %s" % (changed, a.output))


if __name__ == "__main__":
    main()
