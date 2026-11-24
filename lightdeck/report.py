"""'Report a device': a short text about this PC's lighting devices, to ask for support of a new one.

It lists what LightDeck sees (device names, USB IDs, which driver runs them, problems) and nothing
personal: no user names, network addresses, keys, serial numbers or file paths.
The person reviews it, then pastes it into a new issue on LightDeck's GitHub page.
"""
import platform
import re
import time

import winhid
from engine import USER_DIR, VERSION

# LightDeck's GitHub page, once it exists, e.g. "https://github.com/<name>/LightDeck".
# The report button then opens the "Report a device" form there.
REPO_URL = "https://github.com/muhidu1234/LightDeck"

REPORT_PATH = USER_DIR / "device-report.txt"


def issue_url():
    return f"{REPO_URL.rstrip('/')}/issues/new?template=device.yml" if REPO_URL else None


def _ids(text):
    ids = winhid.ids_in(text or "")
    return ", ".join(f"{v:04x}:{p:04x}" for v, p in sorted(ids)) or ""


def _clean_location(loc):
    """Keep the kind of connection and USB IDs, drop serial numbers and instance paths."""
    loc = loc or ""
    ids = _ids(loc)
    kind = re.split(r"[:\s]", loc.strip(), maxsplit=1)[0] if loc.strip() else "?"
    return f"{kind} {ids}".strip()


def build(engine):
    lines = [
        "LightDeck device report",
        "=======================",
        "Please describe the device that doesn't work: its exact model name, and what you expected.",
        "(Write it here.)",
        "",
        f"LightDeck {VERSION} on Windows {platform.release()} ({platform.version()}), {time.strftime('%Y-%m-%d')}",
        f"Status: {engine.status}",
        "",
        "Lights through OpenRGB:",
    ]
    for d in engine.ogb_info:
        lines.append(f"  - {d['name']}  [{_clean_location(d.get('location'))}]  control: {d.get('ctrl', '?')}"
                     f"{'  mode: ' + d['mode'] if d.get('mode') else ''}")
    if not engine.ogb_info:
        lines.append("  (none)")
    lines.append("")
    lines.append("Lights through LightDeck's own drivers:")
    for ex in engine.extras:
        ids = ", ".join(f"{v:04x}:{p:04x}" for v, p in getattr(ex, "usb_ids", []) or [])
        lines.append(f"  - {ex.display}  driver: {type(ex).__name__}  {ex.leds} LEDs  {ids}".rstrip())
    if not engine.extras:
        lines.append("  (none)")
    nets = engine.network_lights()
    if nets:
        lines.append("")
        lines.append("Wi-Fi lights added:")
        for cls, _entry, status in nets:
            lines.append(f"  - {cls.kind_name}: {status}")
    lines.append("")
    lines.append("Found, not controllable:")
    for d in engine.other_devices:
        lines.append(f"  - {d['name']}  maker: {d['maker']}  USB ID {d['vid']:04x}:{d['pid']:04x}  "
                     f"type: {', '.join(d['kinds']) or 'unknown'}")
    if not engine.other_devices:
        lines.append("  (none)")
    import apps
    lines.append("")
    lines.append("Other RGB apps running:")
    running = apps.running_rgb_apps()
    for name, how, _tip in running:
        lines.append(f"  - {name}  ({'LightDeck works through it' if how == 'bridge' else how})")
    if not running:
        lines.append("  (none)")
    problems = dict(engine.driver_problems)
    errs = list(engine.driver_errors) + list(engine.effect_errors)
    if problems or errs or engine.last_error:
        lines.append("")
        lines.append("Problems:")
        for name, msg in problems.items():
            lines.append(f"  - {name}: {msg}")
        for e in errs:
            lines.append(f"  - {e}")
        if engine.last_error and not problems:
            lines.append(f"  - last error: {engine.last_error}")
    text = "\n".join(lines) + "\n"
    # belt and braces: never let an IP address or a Windows user folder slip through
    text = re.sub(r"\b\d{1,3}(\.\d{1,3}){3}\b", "<ip>", text)
    text = re.sub(r"(?i)c:\\users\\[^\\\s]+", r"C:\\Users\\<you>", text)
    return text


def save(engine):
    text = build(engine)
    REPORT_PATH.write_text(text, encoding="utf-8")
    return REPORT_PATH, text
