# Changelog

## ui-v1.0 — new UI (in progress, not yet built or tested on hardware)
- New, non-stock UI in `newui/`, based on [A02-OS](https://github.com/TheWirelessPhoenix/a02-os) (MIT; vendored at `d1c10b6`, see `newui/UPSTREAM.md`). It replaces the whole stock UI with its own drivers; the stock firmware stays installed underneath (hold M at power-on).
- Home screen: **MUSIC** and **INFO** only. INFO shows version, battery, card free/size, backlight (changeable) and Bluetooth status.
- Installs from Windows without extra tools: `UPGRADE.HEX` + the stock **Tools → Firmware upgrade** (`tools/mk_newui_upgrade.py`, built by `.github/workflows/newui.yml`).
- Limits (inherited from A02-OS): music from the microSD card only, MP3/WAV only, no Bluetooth driver yet.

## v4 — AGP-A02-V4-MUSIC-BT
- Home screen: Music + Settings (`MAINMENU_AP_ID_ARRAY = [0, 10]`). There is no standalone About/Info app in this firmware; the About screen is Settings → Device Info.
- Bluetooth reconnection (A02 is a BT *transmitter* to headphones/speakers; settings live in `config.bin`):
  - `BTSTACK_AUTO_CONNECT_COUNT_TIMEOUT` 8 → 0 (after a dropped link, keep retrying indefinitely)
  - `BTSTACK_AUTO_CONNECT_COUNT_STARTUP` 5 → 15 (retries at power-on)
  - `BTSTACK_AUTO_CONNECT_COUNT_MODE` 5 → 15 (retries when entering BT mode)
  - `BTSTACK_AUTO_CONNECT_INTERVAL` 46 → 10 (every 5 s instead of 23 s; unit is 0.5 s)
  - TX power (`BTSTACK_OUTPUT_POWER_VALUE`) was already at its maximum (7) — left as is.
- English default (unchanged from stock, which is already 2 = English), version string `AGP-A02-V4-MUSIC-BT`.
- Built directly from the stock vendor file with `tools/build.py` (no v2/v3 intermediates). Config keys are now edited by name with value checks (`tools/configbin.py`), and file contents are mapped through SQLite's overflow pages (`tools/fwimage.py`). 48 bytes changed in total, only inside `config.bin` / `configbk.bin`; self-verified by re-decrypting with atjboottool (byte-identical) and SQLite `integrity_check`.
- Skin graphics untouched. The `.sty` format is now documented in `tools/sty.py` (raw RGB565 bitmaps), but the green/purple theme is on hold.
- Trade-off: unlimited reconnect after link loss means the player keeps looking for the headphones while BT is on — turn BT off when not using it.

## v3 — AGP-A02-MUSICONLY-EN
- Home screen app list reduced to a single entry (music), so the firmware boots straight into playback with no menu to navigate.
- Default language changed to English.
- About-screen version string set to `AGP-A02-MUSICONLY-EN` to make a successful flash unmistakable.
- Built on top of v2, patching `config.bin` and `configbk.bin` directly (the files the firmware actually reads at runtime).

## v2 — AGP-A02-CUSTOM-GRNPUR
- First correct patch: discovered that v1 had edited `config.txt`, a human-readable reference copy the firmware never reads, which is why v1 produced no visible change on the device.
- Located the real runtime config (`config.bin` / `configbk.bin`), decoded its offset-table binary format, and patched: home screen reduced to Music + Settings, default language set to Hebrew, About-screen version string set to `AGP-A02-CUSTOM-GRNPUR`.
- Investigated a UI color theme change (green/purple); found no such preset exists in config — would require editing raw bitmap resources in the `.sty` skin files, a separate and not-yet-attempted task.

## v1 — AGPTEK-A02(20241019)-music-only-he (superseded, did not work)
- Edited `config.txt` to show a music-only menu and default to Hebrew.
- Verified the edit round-tripped correctly through decrypt/encrypt, but the edit had no effect on the device because `config.txt` isn't the file the firmware parses at runtime.
