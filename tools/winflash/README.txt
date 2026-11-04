A02 Flasher for Windows
=======================

Installs the new UI (based on A02-OS) on an AGPTEK A02 over USB, or restores the stock AGPTEK
firmware. Nothing else on the player is touched: only the firmware area is written, and it is
read back and compared before the program finishes.

ONE-TIME SETUP: USB driver (Zadig)
----------------------------------
1. Download Zadig from https://zadig.akeo.ie and start it.
2. Connect the player by USB, then hold PLAY about 10 seconds until it enters recovery mode
   (the screen stays dark; Windows may say "new hardware found").
3. In Zadig: Options -> List All Devices. Pick the device with USB ID 10D6 10D6.
   Choose "WinUSB" as the driver and click "Replace Driver" (or "Install Driver").
   Only do this for 10D6 10D6. Do not change the player's normal USB disk (10D6 1101).

Note: after this, AGPTEK's Media Product Tool no longer sees the player in recovery mode.
To use it again: Device Manager -> the 10D6 device -> Uninstall device (tick "delete the driver"),
then reconnect.

USE
---
1. Put music (MP3/WAV) on the microSD card, ideally in a folder named Music, and insert it.
2. Put the player in recovery mode: connect USB, hold PLAY about 10 seconds.
3. Start A02Flasher.exe.
   - Option 1 "Check the connection" first. It cannot write anything.
     Then switch the player OFF, unplug, replug, and enter recovery mode again.
   - Option 2 installs the new UI. Type YES to confirm. It takes a few minutes.
   - Option 3 restores the stock AGPTEK firmware.
4. When it says VERIFIED: switch the player OFF, unplug it, switch it ON.

Start the stock firmware at any time: hold M while switching the player on (needed to copy
music over USB). If the new UI cannot start, the player starts the stock firmware by itself.

IF SOMETHING GOES WRONG
-----------------------
- "STOPPED: ..." before step 5: nothing was written. Switch OFF, unplug, replug, try again.
- "this player has NAND ...": your unit has a different flash chip than the one this procedure
  was verified on. The program refuses to write. Please report the chip ID.
- "VERIFY FAILED": leave the player plugged in, do not switch it off, run the program again.
- To go back to stock in any case: option 3, or AGPTEK's Media Product Tool with the
  official firmware (after removing the WinUSB driver, see above).

CREDITS
-------
New UI and flash procedure: A02-OS, https://github.com/TheWirelessPhoenix/a02-os (MIT).
USB tool (actions_dump) and loader (adfus): https://github.com/ilyakurdyukov/actions_flash
(provided "as is", no license file; included here unmodified, built from source).
Decryption: Rockbox atjboottool (GPL-2.0-or-later). Firmware files: AGPTEK / Actions.
Use at your own risk.
