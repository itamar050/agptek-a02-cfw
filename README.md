# AGPTEK A02 Custom Firmware Patch

A music-only, English-default firmware patch for the AGPTEK A02 MP3 player (Actions Semiconductor ATJ2157 chip), built by reverse-engineering the vendor's own update package rather than writing firmware from scratch.

## What this does

Starting from AGPTEK's official `AGP-A02-20241019-V1.0` update package, the patched firmware:

- Shows **only the music player** on boot — no home-screen menu, no other apps (radio, file browser, recorder, tools, photo viewer, ebook reader, video) to navigate past.
- Defaults to **English** as the UI language.
- Shows a distinctive build string (`AGP-A02-MUSICONLY-EN`) in the About screen, so a successful flash is unmistakable.

No code was added or removed from the device — everything here is a configuration change inside the vendor's own firmware.

## How it was built

The A02's update package is a custom encrypted container (RC4 keystream, keyed via an ECIES handshake over the sect233k1 curve — the same scheme used across Actions Semiconductor's ATJ21xx/ATJ213x product line). It was decrypted using [atjboottool](https://github.com/Rockbox/rockbox/tree/master/utils/atj2137/atjboottool), originally built for Rockbox.

Decrypted, the firmware image turns out to be an **SQLite database** (`FileTable`) holding every app module, driver, font, codepage table, and config file as a row — 180 files in total, including a human-readable `config.txt` (reference only, never read by the firmware) and the real runtime config, `config.bin` / `configbk.bin` (a small binary table of offset/length records pointing into a packed value region).

Because the payload encryption is a plain RC4 keystream, a plaintext edit of a known byte length can be converted into a ciphertext patch with a simple XOR delta — `new_ciphertext = old_ciphertext XOR old_plaintext XOR new_plaintext` — without ever needing to break or re-derive the encryption key. Each patched build was verified by decrypting it again with atjboottool and diffing the result byte-for-byte against the intended plaintext before it was ever flashed to real hardware.

See [`tools/patch_config.py`](tools/patch_config.py) for the exact patch applied to the current release, and [`CHANGELOG.md`](CHANGELOG.md) for the iteration history (including a first attempt that patched the unused `config.txt` reference file instead of the real `config.bin`, and why that produced no visible change on-device).

## Flashing

Use AGPTEK's own **Media Product Tool** (bundled in their official update package) exactly as documented in their upgrade instructions — "replace firmware" → "uploading the firmware" → select the patched `.bin` → flash. Nothing about the flashing procedure itself changes; only the firmware file does.

**Keep the original AGPTEK update package as a rollback.** If anything looks wrong after flashing, reflashing the original stock file the same way restores the official state.

## Downloads

See the [Releases](../../releases) page for the latest patched firmware binary.

## Disclaimer

This is a config-level patch to a third-party vendor's firmware, built and self-verified cryptographically but only tested by actually flashing it to the target hardware by the repository owner. Flash at your own risk; keep a backup of the stock firmware.
