# LightDeck - project notes for Claude

LightDeck is a lightweight Windows RGB controller (a SignalRGB alternative) written in Python + tkinter.
OpenRGB 1.1 does the hardware talking (SDK server on 127.0.0.1:6742); LightDeck runs the effects,
the UI and its own drivers for devices OpenRGB lacks. Current version: see `VERSION` in `lightdeck/engine.py`.

## Style
- The look is Cyberpunk (rainy Night City: navy, electric blue, cyan, lavender, pink, red).
- On real LEDs, pastel colors look white: keep effect colors saturated (see `vivid()` / `NIGHT_CITY_LED`).
- Explain changes in plain words: the maintainer is not a programmer.
- Personal notes for the maintainer's own PC are in `CLAUDE.local.md` (not uploaded).

## Folder layout
- `lightdeck/` - the app source (run from source with `pythonw lightdeck/app.py` or `lightdeck/LightDeck.bat`)
  - `app.py` - tkinter window: themes (`THEMES` dict), lights tree, details panel, palette editor,
    live preview, first-run welcome, "Found, not controllable" section, Settings window.
    Details panel is built from `_section` (card, foldable with a key) / `_form` + `_field` (label | controls)
    / `_hint`; settings text uses `UI_FONTS` (Segoe UI Variable Text, fallback Segoe UI), headings and
    buttons keep the theme font. Effect params support `show_if={...}` and `hint=` (effect_base.Param).
  - `startup.py` - "Start with Windows": HKCU Run value `LightDeck` (`--startup` = open minimized);
    the installer asks and writes the same value, the uninstaller removes it
  - `engine.py` - render loop thread (default 60 fps), OpenRGB connection/hotplug, zones, splitting
    (parts along a strip, parallel strips, or key rows from an OpenRGB matrix map), per-device rate
    limits, extras (own drivers), config. `pick_control()` picks how each OpenRGB device is driven:
    direct (Direct mode) > perled (e.g. Static with per-LED colors, 10/s) > single (one mode color =
    frame average, 2/s, sent raw with `send_mode`) > none. Zone indices may contain None (gaps in rows).
  - `hud.py` - animated title, neon stripe, telemetry panel (graphs, spectrum, data links)
  - `effect_base.py` - `Effect`/`Param` base classes + helpers (hsv, mix, gradient, palette, vivid,
    `NIGHT_CITY`, `NIGHT_CITY_LED`, `PALETTE_PRESETS`)
  - `effects/*.py` - one effect per file, hot-reloaded; `_template.py` is ignored (underscore)
  - `driver_base.py` - `Driver` base class (find/connect/send/disconnect; LightDeck runs each device
    on its own thread) + `load_drivers()`; `winhid.py` - Windows HID helpers (ctypes + hid.dll)
  - `drivers/*.py` - own drivers, one file per device, loaded from next to the exe like effects
    (`_template.py` ignored). `drivers/rk_n80.py` = the RK N80 keyboard; `drivers/dynamic_lighting.py` =
    any HID LampArray device (Windows Dynamic Lighting standard, usage page 0x59), driven directly via
    `winhid.Reports` (HidP_* by usage). Only tested against a simulated device: the user owns none.
    Network drivers (`network = True`, saved in `cfg["driver_settings"][Class]`, added in Settings > Wi-Fi
    lights): `wled.py` (UDP 21324 DRGB/DNRGB), `nanoleaf.py` (extControl v2, UDP 60222), `hue.py` (API v1,
    xy colors, 10/s), `govee.py` (LAN API, UDP 4001/4002/4003). Bridges: `razer_chroma.py` (Chroma REST,
    localhost:54235), `steelseries.py` (GameSense via coreProps.json). None tested on real devices yet.
  - `nethelp.py` - HTTP JSON, UDP, mDNS browse (own parser)
  - `report.py` - "Report a device" text (IPs/user paths scrubbed); `REPO_URL` empty until GitHub exists
  - `usbcapture.py` - "Add support for it": records with USBPcap (elevated ps1), keeps only host->device
    messages of one vid:pid in `device-recording-<vid>-<pid>.txt`, deletes the raw pcaps
  - `devscan.py` - lists gaming HID devices nothing can control
  - `config.json` - dev settings (copy of the user's real settings; personal, never ship it)
- `build/` - packaging: `make_package.py` (builds .exe with PyInstaller + zip on the Desktop),
  `pkg_src/` (installer .cmd/.ps1, READ ME FIRST, THIRD-PARTY-NOTICES), `licenses/` (GPL texts)
- `.github/` - device request form + Claude workflows (`claude-device.yml` runs when the owner adds the
  `device` label; `claude.yml` = @claude mentions). `build/GITHUB-SETUP.md` = the steps still to do with the user.
- `README.md` (root) - the GitHub page
- `tools/` - USB reverse-engineering helpers used for the N80 (USBPcap capture, pcap parser,
  byte-diff, on-device pattern finder) and `token_usage.py`

## Build, install, share
- Rebuild exe + friend zip: `python build/make_package.py` (from this folder) ->
  `Desktop/LightDeck-<version>-Windows.zip`. Bump `VERSION` in engine.py first.
- Update the user's installed copy: extract that zip and run `Install LightDeck.cmd` (keeps config.json),
  or copy `build/dist/LightDeck/LightDeck.exe` + `_internal` over `%LOCALAPPDATA%\Programs\LightDeck`.
- Installed app: `%LOCALAPPDATA%\Programs\LightDeck` (exe, `_internal`, `effects`, `OpenRGB`, `config.json`,
  `LICENSES`), Start menu + Desktop shortcuts. Settings fall back to `%APPDATA%\LightDeck` if the
  exe folder isn't writable.
- Python 3.15 (user install). Packages: openrgb-python 0.3.8, pyinstaller 6.22.3, Pillow (icon).
- License: LightDeck is GPLv3 (bundles openrgb-python, GPLv3); OpenRGB is GPLv2. The zip must keep
  the source folder + license files.

## Test hardware (the maintainer's PC, all working)
- ASUS ROG STRIX X870-A (Aura USB 0b05:19af): mainboard + 3 ARGB headers (60 LEDs each, Header 1 =
  "RGB cable", a strip cable). USB, full speed.
- ASRock RX 9070 XT Steel Legend: I2C via AMD ADL. Flooding it glitches -> slow-bus devices are capped
  at 10 updates/s, unchanged frames re-sent only every 2 s.
- 2x KLEVV CRAS V RGB DDR5 = "ENE DRAM" (8 LEDs each), SMBus via PawnIO: needs OpenRGB as admin
  (LightDeck launches it with a UAC prompt; user chose to keep the prompt). Same 10/s cap.
- RK N80 keyboard (258a:0187 wired; 258a:0150 = its 2.4G receiver): own driver, see below.
- Logitech G502 X (046d:c099): no RGB on this model. SignalRGB must be closed while LightDeck runs.

## RK N80 protocol (recorded from RK's app with USBPcap)
- HID feature report 9 on interface 1 (the collection with FeatureReportByteLength 520):
  `09 08 00 00 01 00 7a 01` + 126 keys x 3 bytes in **G, R, B** order + zero padding = 520 bytes.
- 126 slots = 21 columns x 6 rows, column-major: `slot = col*6 + row` (Esc=0, F1=12).
- USB 1.1, 8-byte EP0 -> ~133 ms per frame (~7/s max, same as RK's app). Sent on its own thread.
- Must keep streaming: if frames stop it reverts to the lighting saved in RK's app. RK's app must be closed.
- Other observed commands: 0x04 = mode/brightness (byte 18 mode, 01=static; byte 66 brightness 0..0x14),
  0x0a = static color table (bytes 29-31 RGB), 0x0b = clock for its screen, 0x84 precedes 0x04.

## How to work on it
- Test on the real hardware: run the engine headless (see effect tests in history) or the app; then
  restore any settings you changed for testing (the user's config is precious).
- PowerShell `Set-Content -Encoding utf8` writes a BOM; config loading uses `utf-8-sig`, but write
  JSON with Python.
- Heredocs with some Python content broke in this shell before; for long patch scripts write a .py
  file and run it.
- Only one app may talk to the lights: close the running LightDeck before headless tests.
- Device-support roadmap (agreed with the user, Nov 2026): 1) OpenRGB fallbacks + drivers folder +
  key rows (done), 2) Windows Dynamic Lighting (LampArray) driver (done, needs a real device to
  confirm), 3) Wi-Fi lights (WLED, Hue, Nanoleaf, Govee) (done, untested on real lights),
  4) "Report a device" -> GitHub issue, handled by the Claude GitHub add-on, fixes approved by the user
  (app side + .github files done; the GitHub account/repo itself still to set up with the user, see
  build/GITHUB-SETUP.md), 5) in-app USB recording for new drivers (done), 6) vendor-software bridges:
  Razer + SteelSeries done (untested); Logitech/Corsair skipped (need their SDK DLLs downloaded: ask first).
- Other ideas: music-reactive effects, per-key layout map for the N80 (named keys), more themes.
