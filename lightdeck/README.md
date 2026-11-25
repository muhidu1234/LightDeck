# LightDeck

A small RGB controller for all your lights at once. OpenRGB does the hardware
talking. LightDeck runs the animations, and you control every one of them.

## Start it
1. Close SignalRGB fully (system tray, then Exit). Only one RGB app can drive the lights.
2. Open **LightDeck** from the Start menu or the Desktop shortcut.
   It's installed in `%LOCALAPPDATA%\Programs\LightDeck` with its own copy of OpenRGB,
   and starts OpenRGB by itself (Windows asks for admin once so RAM lighting works).

Everything you might edit lives next to `LightDeck.exe`: `effects\` (your effects, live-reloaded),
`drivers\` (LightDeck's own device drivers), `config.json` (all settings), `OpenRGB\`. No Python needed.

## New devices
- Devices **OpenRGB supports** appear in the Lights list by themselves a few seconds after you plug
  them in (LightDeck asks OpenRGB for changes every 6 s). New ARGB headers start at 60 LEDs and
  use the All lights effect.
- Devices **without a live mode** still work: if a device only has modes like "Static", LightDeck
  uses that mode at a gentler pace (per-LED colors), or, if it can only show one color, gives it the
  effect's average color (2 updates a second by default). The device's page explains which.
- **Keyboards and other grids** with a key map are split into their key rows the first time they
  show up, so effects line up across the keys. "Join back into one" undoes it; "Key rows" in
  *Split this cable* brings it back.
- **Windows Dynamic Lighting devices** (many newer keyboards, mice, headsets and strips) are driven
  directly by `drivers/dynamic_lighting.py`: it reads where every lamp sits and which colors it can
  show, lines keyboards up in key rows, and only sends lamps that changed. Turn Windows' own Dynamic
  Lighting off for those devices (Settings > Personalization > Dynamic Lighting), or the two take
  turns. When LightDeck closes, they go back to their own lighting. Devices OpenRGB already drives
  are left to OpenRGB.
- Gaming devices **nothing can light** are listed under **Found, not controllable** with their
  maker, USB ID and the reason. They can get a driver of their own (see *Device drivers*).
- **Wi-Fi lights** (WLED, Philips Hue, Nanoleaf, Govee): *Settings > Wi-Fi lights > Search my network*,
  then **Add**. Hue and Nanoleaf need a button press to pair (the window says which); Govee needs
  "LAN Control" on in the Govee Home app. Not found? Type its IP address. When LightDeck closes,
  Hue and Nanoleaf go back to what they showed before.
- **Devices OpenRGB doesn't drive** are lit through the maker's own app while it runs: Logitech G HUB
  (or Logitech Gaming Software), ASUS Armoury Crate (Aura SDK), Corsair iCUE (put Corsair's free
  `iCUESDK.x64_2019.dll` from github.com/CorsairOfficial/cue-sdk in the `drivers` folder; iCUE's
  "Enable SDK" setting on), Razer Synapse (Chroma) and SteelSeries GG. Written from the makers'
  documentation; not yet tried on real devices.
- **Other RGB apps** that fight LightDeck (SignalRGB, Mystic Light, RGB Fusion, NZXT CAM...) show a
  warning in the status bar; *Settings > Other RGB apps* lists what's running and can close them.
- **Rescan devices** checks everything right away.
- **A device still doesn't work?** **Report a device** (Settings, or *Found, not controllable*)
  saves and copies a short list of what LightDeck sees (names, USB IDs, problems; IP addresses and
  your user name are removed). On a not-controllable device's page, **Add support for it** records
  what the device's own lighting app sends to it, with USBPcap (free; Windows asks for admin):
  only messages sent *to* that device are kept, so never your key presses, and the raw recording
  is deleted. That file is what a new driver is written from.

## Rebuilding the .exe (only if you change the Python code)
```
python -m PyInstaller --noconfirm --windowed --name LightDeck --icon lightdeck\lightdeck.ico --paths lightdeck --hidden-import openrgb --hidden-import devscan --hidden-import winhid --hidden-import driver_base --hidden-import nethelp --hidden-import report --hidden-import usbcapture --hidden-import hud --hidden-import effect_base lightdeck\app.py
```
then copy `dist\LightDeck\LightDeck.exe` and `dist\LightDeck\_internal` over the installed ones
(or simply run `python build/make_package.py`, which also copies the `effects` and `drivers` folders).

## Two windows
- **Night City** (default since 1.21): animated window with a menu on the left - *Lights* (every
  light with a live preview, on/off, Blink), *Light settings* (effect and its settings for All lights
  or one light), *Preview*, *Effects* (gallery with live samples; click one to use it), *Palettes* and *Settings*.
- **Palettes** (1.22): 24 ready-made palettes in three groups (Classic, City districts, Night City moods).
  Click one to use it on the chosen light (or All lights). **Edit** renames it or changes its colors
  (click a color to change it, right-click to remove, **+** to add; **Reset to original** undoes it).
  *My palettes* has 8 slots for your own: save the current colors, rename, share as a code
  (`LightDeck palette: name | #hex #hex`) or paste a friend's code. Saved as `palette_slots` and
  `palette_edits` in config.json; the Classic window's preset list shows them too.
- **Classic**: the original window with every tool (LED count, splitting, Wi-Fi lights, recording).
  Night City > Settings > *Classic window*; back with Settings > Window style > *Switch to the new look*.
  The choice is saved as `"ui"` in config.json.

The rest of this section describes the Classic window.

## Use it
- **All lights**: the effect every light uses by default.
- **Click a light** (for example an ARGB header). Its settings are grouped in cards; cards with
  **Hide / Show** on the right fold away when you don't need them:
  - rename it (`Rename`, or double-click it in the list). Devices can be renamed too.
  - turn it off (`Light on`), or blink it white to find it in your case (`Blink to find it`)
  - **Effect**: pick one in `Choose an effect`, or `Same as All lights` to go back. The card
    below it holds that effect's settings; settings that don't apply to the chosen color mode
    are hidden.
  - **LED count**: how many LEDs are on that ARGB cable. Not sure? `Run a test dot` sends one dot
    through the LEDs in wiring order; where it disappears is the real end of the strip.
  - **Split this cable**:
    - *Parts one after another* (e.g. 3 fans chained on one cable): `Split equally`, or type exact
      sizes such as `20, 20, 20`.
    - *Strips side by side* (several strips next to each other, wired as one chain): set how many
      strips and how the wiring goes, then `Split into strips`. Watch the test dot: if it hops
      sideways across the strips, pick "Across all strips"; if it runs down one strip first, pick
      "Down one strip". If every other row/strip goes back the other way, tick Zigzag wiring.
    - Each part or strip can have its own name and effect. `Join back into one` undoes the split.
- **Settings** (top right): app-wide options, such as starting LightDeck with Windows.
- **Brightness** and **Max FPS** (10-120, default 60) at the top affect everything.
- **Theme** (top right): Cyberpunk or Midnight. Themes live in the `THEMES` table at the top of
  `app.py`; copy one, change its colors and fonts, and it appears in the picker.
- **Telemetry** (bottom right): live FPS and frame time, packets sent per second, estimated LED
  current (about 20 mA per color channel at full brightness - a rough guide, not a measurement),
  average brightness, a hue spectrum of everything the LEDs show, and per-device data links
  (USB or I2C, with updates per second).
- **Night City Comet** and **Night City Aurora** use the same colors as the Cyberpunk theme.
  The palette is available to your own effects as `NIGHT_CITY["cyan"]` etc., with
  `gradient()` and `palette()` helpers for smooth blends.
- **Custom color palettes**: every color effect can use your own list of colors.
  - Comet Chase, Rain Drops, Starfield Sparkle: set Color Mode to **Palette** (the palette row appears).
  - Aurora, Night City Aurora, Night City Comet, Fire: pick **Custom Palette** in their color dropdown.
  - Rainbow Wave, Rainbow Strips, Breathing: tick **Use My Palette / Cycle Through Palette**.
  - In the palette row: click a swatch to change it, right-click to remove, shift+click to move it
    left, **+** to add (up to 16), or **Load a preset**. The bar under it shows the blend.
  - In your own effects: `Param("Colors", "palette", ["#ff0000", "#00ff00"])` and `self.colors("key")`.
  - Show a setting only when it matters: `Param(..., show_if={"color_mode": "Palette"})`, and add a
    one-line explanation under it with `hint="..."`.
- Settings save automatically to `config.json`.

## RK N80 keyboard
OpenRGB doesn't support the RK N80, so LightDeck drives it itself (`drivers/rk_n80.py`), using the exact
message RK's own app sends (recorded with USBPcap): HID feature report 9, 520 bytes,
`09 08 00 00 01 00 7a 01` + 126 keys x (G, R, B), keys stored column by column (21 x 6 grid).
- Works over the **USB cable** only (not 2.4G/Bluetooth). LightDeck checks for it every 10 s.
- The keyboard accepts about **7 updates per second** (USB 1.1, same limit as RK's app). It is fed
  on its own thread, so the other lights keep their full frame rate.
- It must keep receiving frames; if they stop, it returns to the lighting saved in RK's app.
- **Close RK's app** while LightDeck runs, or the two will fight.
- First time it's found, its keys are split into the 6 keyboard rows (F-key row ... Space row).

## Device drivers
For devices OpenRGB can't control, LightDeck has its own drivers: one file per device in the
`drivers` folder (next to the exe, like `effects`). Files starting with `_` are ignored.
LightDeck looks for their devices at start-up, every 10 seconds and on **Rescan devices**
(which also reloads the driver files). Each device runs on its own thread, so a slow one never
holds up the others.

A driver is a class based on `Driver` (see `driver_base.py` and `drivers/_template.py`):
- `name`, `usb_ids`, `leds` (and optionally `rows` with names, for keyboards)
- `find()` returns the connected devices, `connect(found)` opens one, `send(colors)` sends one
  frame of `leds` (r, g, b) colors, `disconnect()` closes it.
- `winhid.py` has the Windows HID helpers: `winhid.devices(vid, pid, interface=..., usage_page=...,
  feature_len=...)`, `open_path`, `set_feature`, `write`, `set_output_report`, `close`, and
  `winhid.Reports` to fill in / read reports by usage (Windows packs the bits) for standard devices.
- Optional: `label(found)` for a per-device name, a `matrix` key map (set in `connect`) for keyboards.
- Network lights: set `network = True`, `kind_name`, and implement `discover()` (and `pair(entry)` if
  `needs_pairing`); added lights are kept in `config.json` under `driver_settings` (`cls.store`).
  `nethelp.py` has `http_json`, `udp_sender` and an mDNS browser. See `wled.py`, `hue.py`.

## Make your own effects
1. Click **Effects folder**.
2. Copy `_template.py`, rename it (e.g. `galaxy.py`, no underscore at the start), and edit it.
3. Save. It appears in the dropdown within a second and reloads live every time you save.
   If the code has a mistake, the error shows in red under the effect settings.

Helpers available in every effect: `hsv(h, s, v)`, `hex_to_rgb("#ff0000")`,
`scale(color, 0..1)`, `mix(a, b, 0..1)`, `add(a, b)`, `zone_random(zone)`, plus `math` and `random`.

## Needs
- Python 3 with `openrgb-python` (`python -m pip install --user openrgb-python`)
- OpenRGB 1.1 in `%LOCALAPPDATA%\Programs\OpenRGB` (path can be changed in `config.json`)
