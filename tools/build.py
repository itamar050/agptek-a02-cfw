"""
Reproducible build of the patched A02 firmware from the ORIGINAL vendor file.

  1. Decrypt the vendor firmware once with atjboottool:
       atjboottool --fwu -o decrypted/a02 "AGPTEK-A02(20241019)"
  2. Build:
       python3 tools/build.py "AGPTEK-A02(20241019)" decrypted/a02 OUT.bin
  3. Self-verify before flashing (must print nothing):
       atjboottool --fwu -o verify/a02 OUT.bin
       cmp verify/a02 OUT.bin.plain

Only config.bin / configbk.bin are changed. No code, skins or other files are
touched. See CHANGELOG.md for what each setting does.
"""
import sys

from configbin import ConfigBin
from fwimage import FirmwareImage, xor_patch

VERSION = b"AGP-A02-V4-MUSIC-BT"   # must be < 20 bytes (configbk.bin field size)

MENU = [0, 10]                      # 0 = music, 10 = settings (Device Info lives here)

SETTINGS = {
    "SETTING_AP_ID_LANGUAGE_ID": 2,             # English
    # Bluetooth reconnect behavior
    "BTSTACK_ENABLE_AUTO_CONNECT": 1,           # (already 1) auto-reconnect on
    "BTSTACK_AUTO_CONNECT_COUNT_TIMEOUT": 0,    # was 8: after link loss, keep retrying (0 = unlimited)
    "BTSTACK_AUTO_CONNECT_COUNT_STARTUP": 15,   # was 5: retries at power-on
    "BTSTACK_AUTO_CONNECT_COUNT_MODE": 15,      # was 5: retries when entering BT mode
    "BTSTACK_AUTO_CONNECT_INTERVAL": 10,        # was 46 (23 s): retry every 5 s (unit 0.5 s)
    "BTSTACK_OUTPUT_POWER_VALUE": 7,            # (already max) TX power
}


def patch(cfg_bytes: bytes, config_txt: str) -> bytes:
    cfg = ConfigBin(cfg_bytes, config_txt)
    cfg.set_array("MAINMENU_AP_ID_ARRAY", MENU)
    for k, v in SETTINGS.items():
        before = cfg.get_u16s(k)[0]
        cfg.set_value(k, v)
        print(f"  {k}: {before} -> {v}")
    cfg.set_string("SETTING_AP_CREAT_DATA", VERSION)
    out = bytes(cfg.data)
    assert len(out) == len(cfg_bytes)
    return out


def main(argv):
    orig_cipher_path, plain_path, out_path = argv[1:4]
    img = FirmwareImage(plain_path)
    print(f"indexed {len(img.files)} files; map verified for {img.verify_against_sqlite()}")
    orig_plain = bytes(img.data)
    config_txt = img.read_file("config.txt").decode("gbk")

    for name in ("config.bin", "configbk.bin"):
        print(name)
        img.write_file(name, patch(img.read_file(name), config_txt))

    new_plain = bytes(img.data)
    open(out_path + ".plain", "wb").write(new_plain)
    cipher = bytearray(open(orig_cipher_path, "rb").read())
    changed = xor_patch(orig_plain, new_plain, cipher)
    open(out_path, "wb").write(cipher)
    print(f"{changed} bytes changed -> {out_path}")


if __name__ == "__main__":
    main(sys.argv)
