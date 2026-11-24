"""Record what a device's own lighting app sends to it, so a LightDeck driver can be written for it.

This is how the RK N80 driver was made. It uses USBPcap (free, https://desowin.org/usbpcap/), which
records USB traffic; it needs administrator rights (Windows asks).

Privacy: a raw USB recording also holds every key you press. So right after recording, LightDeck keeps
ONLY the messages the computer SENT to the chosen device (lighting commands go that way; key presses
come the other way), writes them to a small text file, and deletes the raw recording.
"""
import ctypes
import shutil
import struct
import tempfile
import time
from pathlib import Path

USBPCAP = Path(r"C:\Program Files\USBPcap\USBPcapCMD.exe")
MAX_MINUTES = 15

SCRIPT = r"""
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cmd = "{cmd}"
$procs = @()
foreach ($i in 1..10) {{
    $procs += Start-Process $cmd -ArgumentList "-d", "\\.\USBPcap$i", "-o", "`"$here\hub$i.pcap`"", "-A", "--inject-descriptors" -PassThru -WindowStyle Hidden
}}
"started" | Out-File "$here\started.txt"
$deadline = (Get-Date).AddMinutes({minutes})
while (-not (Test-Path "$here\stop.txt") -and (Get-Date) -lt $deadline) {{ Start-Sleep -Milliseconds 400 }}
Start-Sleep 1
$procs | ForEach-Object {{ Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }}
"stopped" | Out-File "$here\stopped.txt"
"""


def installed():
    return USBPCAP.exists()


def start():
    """Start recording (Windows asks for admin). Returns the recording folder, or raises RuntimeError."""
    if not installed():
        raise RuntimeError("USBPcap isn't installed")
    folder = Path(tempfile.mkdtemp(prefix="lightdeck-capture-"))
    script = folder / "record.ps1"
    script.write_text(SCRIPT.format(cmd=USBPCAP, minutes=MAX_MINUTES), encoding="utf-8")
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
                                             f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script}"',
                                             str(folder), 0)
    if rc <= 32:
        shutil.rmtree(folder, ignore_errors=True)
        raise RuntimeError("the recording wasn't allowed (Windows' admin prompt was declined)")
    for _ in range(100):
        if (folder / "started.txt").exists():
            return folder
        time.sleep(0.2)
    stop(folder)
    discard(folder)
    raise RuntimeError("the recorder didn't start")


def stop(folder):
    (Path(folder) / "stop.txt").write_text("stop")
    for _ in range(60):
        if (Path(folder) / "stopped.txt").exists():
            return True
        time.sleep(0.25)
    return False


def discard(folder):
    shutil.rmtree(folder, ignore_errors=True)


def _packets(path):
    data = Path(path).read_bytes()
    if len(data) < 24 or struct.unpack_from("<I", data, 0)[0] not in (0xA1B2C3D4, 0xA1B23C4D):
        return
    if struct.unpack_from("<I", data, 20)[0] != 249:          # USBPcap link type
        return
    off = 24
    while off + 16 <= len(data):
        ts_s, ts_us, incl, _orig = struct.unpack_from("<IIII", data, off)
        off += 16
        pkt = data[off:off + incl]
        off += incl
        if len(pkt) < 27:
            continue
        hlen, _irp, _st, _fn, info, bus, dev, ep, xfer, dlen = struct.unpack_from("<HQIHBHHBBI", pkt, 0)
        yield dict(t=ts_s + ts_us / 1e6, bus=bus, dev=dev, ep=ep, xfer=xfer, info=info,
                   stage=pkt[27] if xfer == 2 and hlen >= 28 else None, data=pkt[hlen:hlen + dlen])


def sent_to(path, vid, pid):
    """Every message the computer sent to the device vid:pid in one recording: [(seconds, kind, bytes)]."""
    packets = list(_packets(path))
    addr = None
    for p in packets:                                         # device descriptor: 12 01 ... vid pid
        d = p["data"]
        if p["xfer"] == 2 and len(d) >= 18 and d[0] == 0x12 and d[1] == 0x01 and struct.unpack_from("<HH", d, 8) == (vid, pid):
            addr = (p["bus"], p["dev"])
            break
    if addr is None:
        return []
    mine = [p for p in packets if (p["bus"], p["dev"]) == addr]
    t0 = mine[0]["t"] if mine else 0
    out, pending = [], None
    for p in mine:
        d = p["data"]
        if p["xfer"] == 2:                                    # control transfers (SET_REPORT...)
            if p["stage"] == 0 and len(d) >= 8:
                bm, req, wval, widx, wlen = struct.unpack_from("<BBHHH", d, 0)
                kind = f"CTRL bm={bm:02x} req={req:02x} val={wval:04x} idx={widx}"
                if bm & 0x80 == 0 and wlen and len(d) > 8:
                    out.append((p["t"] - t0, kind, d[8:]))
                elif bm & 0x80 == 0 and wlen:
                    pending = (p["t"] - t0, kind)
            elif p["stage"] == 1 and pending and p["info"] & 1 == 0 and d:
                out.append((pending[0], pending[1], d))
                pending = None
        elif p["xfer"] in (1, 3) and not (p["ep"] & 0x80) and p["info"] & 1 == 0 and d:   # interrupt/bulk OUT
            out.append((p["t"] - t0, f"{'INT' if p['xfer'] == 1 else 'BULK'} OUT ep={p['ep']:02x}", d))
    return out


def extract(folder, vid, pid, name=""):
    """Turn a recording into the small text file to share, then delete the raw recording.
    Returns (text, number of messages)."""
    found = []
    for pcap in sorted(Path(folder).glob("hub*.pcap")):
        found += sent_to(pcap, vid, pid)
    discard(folder)
    lines = [f"LightDeck device recording: {name} (USB {vid:04x}:{pid:04x})",
             "Only messages the computer sent to this device. Seconds, kind, length, bytes (hex).", ""]
    lines += [f"{t:9.3f} {kind} len={len(d)} {d.hex()}" for t, kind, d in found]
    return "\n".join(lines) + "\n", len(found)
