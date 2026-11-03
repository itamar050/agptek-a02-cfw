"""
Name-based reader/editor for the A02's runtime config (config.bin / configbk.bin).

Format (little-endian):
  0x00  "cfg\\0" + 12 bytes header
  0x10  table of (offset:u32, length:u32) records, one per key; the table ends
        where the first record's data begins
  data  packed values, one per record:
          range key  "V[min~max,step]"  -> s16 value, s16 min, s16 max, s16 step
          list key   "V[a,b,c]"         -> s16 value, u16 count, s16 items...
          array key  (MAINMENU_AP_ID_ARRAY, CFG_KEY_ARRAY)
                                         -> u16 default, u16 count, u16 items...
          string key "text"              -> bytes (GBK), NUL-terminated

Record order follows the non-comment keys of config.txt, but not 1:1 (a few
entries in the middle of the table have no config.txt line). So names are
assigned by aligning config.txt keys from the START and from the END of the
table, and every aligned record is checked against the default value written
in config.txt. A key is only editable if its record passed that check.
"""
import re
import struct


def parse_config_txt(text: str):
    keys = []
    for line in text.splitlines():
        m = re.match(r"^\s*([A-Z][A-Z0-9_]+)\s*=\s*(.*?);", line)
        if not m:
            continue
        name, val = m.group(1), m.group(2).strip()
        if val.startswith('"'):
            keys.append((name, "str", val.strip('"')))
        else:
            n = re.match(r"(-?\d+)", val)
            keys.append((name, "num", int(n.group(1)) if n else None))
    return keys


class ConfigBin:
    def __init__(self, data: bytes, config_txt: str):
        self.data = bytearray(data)
        assert self.data[:4] == b"cfg\x00", "not a config.bin blob"
        first = struct.unpack_from("<I", self.data, 16)[0]
        self.records = [struct.unpack_from("<II", self.data, 16 + 8 * i)
                        for i in range((first - 16) // 8)]
        self.index = {}
        keys = parse_config_txt(config_txt)
        self._align(keys, range(len(keys)), range(len(self.records)))
        self._align(keys, reversed(range(len(keys))), reversed(range(len(self.records))))

    def _matches(self, key, rec):
        _name, kind, default = key
        off, ln = rec
        raw = bytes(self.data[off:off + ln])
        if kind == "str":
            # configbk.bin carries a different version text than config.txt, so
            # strings are checked structurally: one NUL-terminated text field.
            return ln > 0 and raw.index(b"\x00") == ln - 1 and all(b >= 0x20 for b in raw[:-1])
        return ln >= 4 and default is not None and struct.unpack_from("<h", raw, 0)[0] == default

    def _align(self, keys, key_order, rec_order):
        for ki, ri in zip(key_order, rec_order):
            if not self._matches(keys[ki], self.records[ri]):
                break
            self.index.setdefault(keys[ki][0], ri)

    def _rec(self, name):
        if name not in self.index:
            raise KeyError(f"{name}: not reliably located in config.bin")
        return self.records[self.index[name]]

    def get_u16s(self, name):
        off, ln = self._rec(name)
        return list(struct.unpack_from(f"<{ln // 2}h", self.data, off))

    def set_value(self, name, value: int):
        """Set the current value of a range/list key, enforcing its range."""
        off, ln = self._rec(name)
        v = self.get_u16s(name)
        if name.endswith("_ARRAY"):
            raise ValueError("use set_array")
        if v[1] <= v[2] and len(v) == 4:           # range: value, min, max, step
            assert v[1] <= value <= v[2], f"{name}={value} outside [{v[1]}, {v[2]}]"
        else:                                       # list: value, count, items
            assert value in v[2:2 + v[1]], f"{name}={value} not in {v[2:2 + v[1]]}"
        struct.pack_into("<h", self.data, off, value)

    def set_array(self, name, items):
        """Set an array key's element list; unused slots are zero-filled."""
        off, ln = self._rec(name)
        slots = (ln - 4) // 2
        assert 0 < len(items) <= slots
        struct.pack_into("<H", self.data, off + 2, len(items))
        struct.pack_into(f"<{slots}H", self.data, off + 4, *(list(items) + [0] * (slots - len(items))))

    def set_string(self, name, text: bytes):
        """Replace a string value in place; padded with NULs to the field length."""
        off, ln = self._rec(name)
        assert len(text) < ln, f"{name}: '{text}' needs {len(text) + 1} bytes, field has {ln}"
        self.data[off:off + ln] = text + b"\x00" * (ln - len(text))
