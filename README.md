# LightDeck

A lightweight RGB controller for Windows: one small app that runs animated effects across all your
lights at once (motherboard, ARGB fans and strips, graphics card, RAM, keyboards, mice and Wi-Fi lights),
with a Night City neon look.

[OpenRGB](https://openrgb.org) does most of the hardware talking; LightDeck runs the effects and the
window, and adds its own drivers for devices OpenRGB doesn't cover.

## What it can light
- **Everything OpenRGB supports** (hundreds of motherboards, GPUs, RAM kits, keyboards, mice, coolers).
  Devices without a fast "Direct" mode still work at a gentler pace.
- **Windows Dynamic Lighting devices** (HID LampArray): many newer keyboards, mice, headsets and strips.
- **Wi-Fi lights**: WLED, Philips Hue, Nanoleaf and Govee (LAN control), found by *Search my network*.
- **Through the maker's own app**: Razer Chroma and SteelSeries GG (GameSense), when those apps are running.
- **Its own drivers**, e.g. the RK N80 keyboard, made from a recording of what the keyboard's own app sends.

## Install
Download the latest `LightDeck-<version>-Windows.zip` from **Releases**, extract it and run
`Install LightDeck.cmd`. Close SignalRGB, iCUE, Armoury Crate lighting and similar apps first:
only one app can drive the lights at a time. Full instructions are in `READ ME FIRST.txt` inside the zip.

## A device doesn't work?
1. In LightDeck, click **Report a device** (in Settings, or on the *Found, not controllable* page).
   It copies a short list of what LightDeck sees: device names, USB IDs and problems, nothing personal.
2. [Open a device request](../../issues/new?template=device.yml) and paste it.
3. Optional but very helpful: on the device's page, **Add support for it** records what the device's own
   lighting app sends to it (only lighting commands, never key presses). Attach that file too.

Requests are read by the maintainer; approved ones are handed to Claude (an AI assistant), which drafts
the driver as a pull request that the maintainer checks before anything is released.

## Make your own effects and drivers
Effects are small Python files in `effects/`, drivers in `drivers/`; both are loaded from next to
`LightDeck.exe`, so you can add one without rebuilding. Start from `_template.py` in either folder.
See [lightdeck/README.md](lightdeck/README.md) for the full guide.

## Run from source
Python 3 on Windows (developed on 3.15), then:
```
pip install openrgb-python
pythonw lightdeck/app.py
```
LightDeck starts OpenRGB 1.x itself if it's in `lightdeck/OpenRGB/`; otherwise run OpenRGB with its
SDK server on (port 6742) and LightDeck connects to it.

## License
LightDeck is free software under the **GNU GPL v3** (it uses openrgb-python, GPLv3).
The bundled OpenRGB is GPLv2. See `build/licenses/` and `build/pkg_src/THIRD-PARTY-NOTICES.txt`.
