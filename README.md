# AGPTEK A02 Custom Firmware Patch

A music-only, English-default firmware patch for the AGPTEK A02 MP3 player (Actions Semiconductor ATJ2157 chip), built by reverse-engineering the vendor's own update package rather than writing firmware from scratch.

## What this does

Starting from AGPTEK's official `AGP-A02-20241019-V1.0` update package, the patched firmware:

- Home screen has **only Music and Settings** (Settings → Device Info is the About screen) — no radio, file browser, recorder, tools, photo viewer, ebook reader or video.
- Defaults to **English** as the UI language.
- **More persistent Bluetooth reconnection**: after the link drops it keeps retrying instead of giving up after 8 tries, retries up to 15 times at power-on / when entering BT mode (was 5), and retries every 5 s instead of every 23 s.
- Shows a distinctive build string (`AGP-A02-V4-MUSIC-BT`) in Device Info, so a successful flash is unmistakable.

No code was added or removed from the device — everything here is a configuration change inside the vendor's own firmware.

## How it was built

The A02's update package is a custom encrypted container (RC4 keystream, keyed via an ECIES handshake over the sect233k1 curve — the same scheme used across Actions Semiconductor's ATJ21xx/ATJ213x product line). It was decrypted using [atjboottool](https://github.com/Rockbox/rockbox/tree/master/utils/atj2137/atjboottool), originally built for Rockbox.

Decrypted, the firmware image turns out to be an **SQLite database** (`FileTable`) holding every app module, driver, font, codepage table, and config file as a row — 180 files in total, including a human-readable `config.txt` (reference only, never read by the firmware) and the real runtime config, `config.bin` / `configbk.bin` (a small binary table of offset/length records pointing into a packed value region).

Because the payload encryption is a plain RC4 keystream, a plaintext edit of a known byte length can be converted into a ciphertext patch with a simple XOR delta — `new_ciphertext = old_ciphertext XOR old_plaintext XOR new_plaintext` — without ever needing to break or re-derive the encryption key. Each patched build was verified by decrypting it again with atjboottool and diffing the result byte-for-byte against the intended plaintext before it was ever flashed to real hardware.

See [`CHANGELOG.md`](CHANGELOG.md) for the iteration history (including a first attempt that patched the unused `config.txt` reference file instead of the real `config.bin`, and why that produced no visible change on-device).

## Building from the stock firmware

Since v4 the whole patch is reproducible from the untouched vendor file — no intermediate builds needed. Only `config.bin` / `configbk.bin` are changed; app code and skin graphics are left exactly as shipped.

```bash
# build atjboottool once (needs zlib1g-dev)
git clone --depth 1 https://github.com/Rockbox/rockbox && make -C rockbox/utils/atj2137/atjboottool
# decrypt the vendor firmware (the extension-less file inside AGPTEK_A02(20241019).rar)
rockbox/utils/atj2137/atjboottool/atjboottool --fwu -o decrypted/a02 "AGPTEK-A02(20241019)"
# build, then self-verify (cmp must print nothing)
python3 tools/build.py "AGPTEK-A02(20241019)" decrypted/a02 AGPTEK-A02-V4-MUSIC-BT.bin
rockbox/utils/atj2137/atjboottool/atjboottool --fwu -o verify/a02 AGPTEK-A02-V4-MUSIC-BT.bin
cmp verify/a02 AGPTEK-A02-V4-MUSIC-BT.bin.plain
```

Tools:

- [`tools/build.py`](tools/build.py) — the build: which settings are changed and to what.
- [`tools/configbin.py`](tools/configbin.py) — name-based editor for `config.bin`; every key is located by aligning against `config.txt` and checked against its default before it can be written, and range/list limits are enforced.
- [`tools/fwimage.py`](tools/fwimage.py) — walks the SQLite B-tree and overflow pages so a file inside the image can be rewritten in place byte-for-byte (large files are not contiguous in the image), plus the XOR-delta re-encryption.
- [`tools/sty.py`](tools/sty.py) — read-only parser/dumper for the RU3 `.sty` skin containers (raw RGB565 pictures, per-language string tables, XML resource descriptor), documented for future work.
- [`tools/patch_config.py`](tools/patch_config.py) — the original v3 patch script (historical; it needs the v2 intermediate files).

Stock build `AGPTEK-A02(20241019)` SHA-256: `45b198455d310c15030506c1cefb654e65e505298d0cfa167fdfe1d550586484`.

## Flashing

Use AGPTEK's own **Media Product Tool** (bundled in their official update package) exactly as documented in their upgrade instructions — "replace firmware" → "uploading the firmware" → select the patched `.bin` → flash. Nothing about the flashing procedure itself changes; only the firmware file does.

**Keep the original AGPTEK update package as a rollback.** If anything looks wrong after flashing, reflashing the original stock file the same way restores the official state.

## Downloads

See the [Releases](../../releases) page for the latest patched firmware binary.

## Disclaimer

This is a config-level patch to a third-party vendor's firmware, built and self-verified cryptographically but only tested by actually flashing it to the target hardware by the repository owner. Flash at your own risk; keep a backup of the stock firmware.
