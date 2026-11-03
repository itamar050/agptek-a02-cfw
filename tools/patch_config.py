"""
Patches the AGPTEK A02's decrypted firmware database (config.bin / configbk.bin)
and re-encrypts the result via an XOR delta against the original ciphertext,
without ever needing to know or re-derive the RC4/ECIES key material.

Prerequisites:
  - atjboottool (https://github.com/Rockbox/rockbox/tree/master/utils/atj2137/atjboottool),
    used to decrypt the original firmware once, and again to self-verify the patched result.
  - The original vendor firmware file (e.g. AGP-A02-20241019-V1.0's .bin from the .rar).

Usage (after running `atjboottool --fwu -o decrypted/a02 original_firmware.bin`):
  python3 patch_config.py

This reproduces the v3 (AGP-A02-MUSICONLY-EN) patch: the home-screen app list
reduced to one entry (music only, so the device boots straight into playback),
default language set to English, and a distinctive About-screen version string.

The technique generalizes to any text/numeric field inside config.bin: find its
byte offset (the config.bin format is a 16-byte header, a table of (offset,
length) uint32 pairs -- one per key in config.spc, in order -- followed by the
packed value data those pairs point into), patch it in the decrypted plaintext,
and XOR the delta into the original ciphertext at `plaintext_offset + 2048`
(valid for any offset past the small blockA/blockB region near the start of
the file -- true for config.bin, which sits deep in the image).
"""
import struct

CONST_SHIFT = 2048  # ciphertext_offset = plaintext_offset + CONST_SHIFT,
                     # valid for any edit past the ~16KB header/key region.


def patch_bytes(plain: bytearray, off: int, old: bytes, new: bytes, name: str):
    assert len(old) == len(new), f"{name}: length must match exactly (no resizing)"
    assert bytes(plain[off:off + len(old)]) == old, f"{name}: content mismatch at {off}"
    plain[off:off + len(new)] = new
    print(f"patched {name} at {off}")


def patch_version_string(plain: bytearray, off: int, old: bytes, new_text: bytes) -> int:
    """Pads new_text with trailing NULs to match old's exact length. Returns the
    offset immediately after the field (start of the next field)."""
    new = new_text + b"\x00" * (len(old) - len(new_text))
    patch_bytes(plain, off, old, new, "version_string")
    return off + len(old)


def patch_config_blob(plain: bytearray, base: int, ver_old: bytes, ver_new: bytes):
    """base = full-file offset where this config.bin/configbk.bin blob starts
    (the 'cfg\\0'... header). Offsets below are relative to that, taken directly
    from the parsed (offset,length) record table."""
    count_off = base + 1244   # MAINMENU_AP_ID_ARRAY element count (u16)
    elems_off = base + 1246   # MAINMENU_AP_ID_ARRAY elements (9x u16)
    lang_off  = base + 1388   # SETTING_AP_ID_LANGUAGE_ID current value (u16)

    patch_bytes(plain, count_off, struct.pack("<H", 9), struct.pack("<H", 1), "count")
    old_elems = struct.pack("<9H", 0, 10, 0, 0, 0, 0, 0, 0, 0)
    new_elems = struct.pack("<9H", 0, 0, 0, 0, 0, 0, 0, 0, 0)
    patch_bytes(plain, elems_off, old_elems, new_elems, "elems")
    patch_bytes(plain, lang_off, struct.pack("<H", 23), struct.pack("<H", 2), "language_id")
    patch_version_string(plain, base + 2512, ver_old, ver_new)


def xor_patch_ciphertext(orig_plain: bytes, new_plain: bytes, orig_cipher: bytearray) -> int:
    assert len(orig_plain) == len(new_plain)
    changed = 0
    for p in range(len(orig_plain)):
        if orig_plain[p] != new_plain[p]:
            c = p + CONST_SHIFT
            orig_cipher[c] ^= (orig_plain[p] ^ new_plain[p])
            changed += 1
    return changed


if __name__ == "__main__":
    orig_plain = bytearray(open("decrypted/a02_modified2", "rb").read())

    patch_config_blob(
        orig_plain, base=2581075,
        ver_old=b"AGP-A02-CUSTOM-GRNPUR\x00",
        ver_new=b"AGP-A02-MUSICONLY-EN\x00",
    )
    patch_config_blob(
        orig_plain, base=2384373,
        ver_old=b"AGP-A02-CSTM-GP" + b"\x00" * 5,
        ver_new=b"AGP-A02-MUSEN\x00",
    )

    open("decrypted/a02_modified3", "wb").write(orig_plain)

    base_plain = open("decrypted/a02_modified2", "rb").read()
    new_plain = open("decrypted/a02_modified3", "rb").read()
    cipher = bytearray(open("AGPTEK-A02-patched2.bin", "rb").read())
    changed = xor_patch_ciphertext(base_plain, new_plain, cipher)
    print(f"{changed} bytes changed; writing patched firmware")
    open("AGPTEK-A02-patched3.bin", "wb").write(cipher)

    # Always self-verify before flashing:
    #   atjboottool --fwu -o verify/a02 AGPTEK-A02-patched3.bin
    #   diff verify/a02 decrypted/a02_modified3   # must be byte-identical
