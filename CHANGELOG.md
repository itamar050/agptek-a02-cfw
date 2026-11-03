# Changelog

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
