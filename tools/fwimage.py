"""
Byte-accurate access to files inside the decrypted A02 firmware image.

The decrypted image is an SQLite database; each firmware file is a BLOB in
FileTable(Keyword, FileName, FileLength, File). BLOBs larger than a page are
split across a chain of overflow pages, so a file's bytes are NOT contiguous
in the image. This module walks the FileTable B-tree and overflow chains to
build an exact file-offset -> image-offset map, so a file can be edited in
place (same length) without letting SQLite rewrite anything else.

It also provides the XOR-delta re-encryption step:
  cipher[img_off + CONST_SHIFT] ^= old_plain[img_off] ^ new_plain[img_off]
which is valid because the payload is encrypted with a plain RC4 keystream
and the encrypted file is the decrypted image plus a 2048-byte header region.
"""
import sqlite3
import struct

CONST_SHIFT = 2048


def _varint(buf, pos):
    v = 0
    for i in range(9):
        b = buf[pos + i]
        if i == 8:
            return (v << 8) | b, pos + 9
        v = (v << 7) | (b & 0x7F)
        if b < 0x80:
            return v, pos + i + 1
    raise ValueError("bad varint")


def _serial_len(t):
    if t >= 12:
        return (t - 12) // 2 if t % 2 == 0 else (t - 13) // 2
    return [0, 1, 2, 3, 4, 6, 8, 8, 0, 0, 0, 0][t]


class FirmwareImage:
    def __init__(self, path):
        self.path = path
        self.data = bytearray(open(path, "rb").read())
        self.page_size = struct.unpack(">H", self.data[16:18])[0] or 65536
        self.usable = self.page_size - self.data[20]
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        self.root = db.execute(
            "select rootpage from sqlite_master where name='FileTable'").fetchone()[0]
        db.close()
        self._maps = {}
        self._index()

    # --- SQLite B-tree walking -------------------------------------------
    def _page_off(self, pgno):
        return (pgno - 1) * self.page_size

    def _payload_segments(self, page_start, cell_off):
        """Return (total_payload_len, [(img_off, length), ...]) for a leaf cell."""
        d = self.data
        P, pos = _varint(d, cell_off)
        _rowid, pos = _varint(d, pos)
        U = self.usable
        X = U - 35
        if P <= X:
            return P, [(pos, P)]
        M = ((U - 12) * 32 // 255) - 23
        K = M + ((P - M) % (U - 4))
        local = K if K <= X else M
        segs = [(pos, local)]
        remaining = P - local
        ovfl = struct.unpack(">I", d[pos + local:pos + local + 4])[0]
        while remaining > 0:
            po = self._page_off(ovfl)
            n = min(remaining, U - 4)
            segs.append((po + 4, n))
            remaining -= n
            ovfl = struct.unpack(">I", d[po:po + 4])[0]
        return P, segs

    def _walk(self, pgno, out):
        d = self.data
        base = self._page_off(pgno)
        hdr = base + (100 if pgno == 1 else 0)
        kind = d[hdr]
        ncells = struct.unpack(">H", d[hdr + 3:hdr + 5])[0]
        if kind == 0x05:
            ptrs = hdr + 12
            for i in range(ncells):
                c = base + struct.unpack(">H", d[ptrs + 2 * i:ptrs + 2 * i + 2])[0]
                self._walk(struct.unpack(">I", d[c:c + 4])[0], out)
            self._walk(struct.unpack(">I", d[hdr + 8:hdr + 12])[0], out)
        elif kind == 0x0D:
            ptrs = hdr + 8
            for i in range(ncells):
                c = base + struct.unpack(">H", d[ptrs + 2 * i:ptrs + 2 * i + 2])[0]
                out.append(self._payload_segments(base, c))
        else:
            raise ValueError(f"unexpected page type {kind:#x} on page {pgno}")

    def _index(self):
        cells = []
        self._walk(self.root, cells)
        self.files = {}
        for P, segs in cells:
            payload_map = []
            for off, n in segs:
                payload_map.extend(range(off, off + n))
            assert len(payload_map) == P
            payload = bytes(self.data[i] for i in payload_map[:min(P, 512)])
            hsize, pos = _varint(payload, 0)
            types = []
            while pos < hsize:
                t, pos = _varint(payload, pos)
                types.append(t)
            col_off = hsize
            cols = []
            for t in types:
                cols.append((col_off, _serial_len(t)))
                col_off += _serial_len(t)
            fn_off, fn_len = cols[1]
            name = bytes(self.data[i] for i in payload_map[fn_off:fn_off + fn_len]).decode()
            blob_off, blob_len = cols[3]
            self.files[name] = payload_map[blob_off:blob_off + blob_len]

    # --- file access ------------------------------------------------------
    def read_file(self, name) -> bytes:
        return bytes(self.data[i] for i in self.files[name])

    def write_file(self, name, new: bytes):
        m = self.files[name]
        assert len(new) == len(m), f"{name}: size change not supported ({len(new)} != {len(m)})"
        for i, b in zip(m, new):
            self.data[i] = b

    def verify_against_sqlite(self):
        """Check every mapped file against what SQLite itself returns."""
        db = sqlite3.connect(f"file:{self.path}?mode=ro", uri=True)
        n = 0
        for name, blob in db.execute("select FileName, File from FileTable"):
            assert self.read_file(name) == blob, f"map mismatch for {name}"
            n += 1
        db.close()
        return n


def xor_patch(orig_plain: bytes, new_plain: bytes, cipher: bytearray) -> int:
    assert len(orig_plain) == len(new_plain) and len(cipher) == len(orig_plain) + CONST_SHIFT
    changed = 0
    for p, (a, b) in enumerate(zip(orig_plain, new_plain)):
        if a != b:
            cipher[p + CONST_SHIFT] ^= a ^ b
            changed += 1
    return changed
