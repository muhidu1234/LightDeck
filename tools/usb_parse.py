"""Read a USBPcap recording and pull out what the host sent to one USB device.

Usage: python parse.py capture.pcap VID PID
Prints the device addresses found, then every host->device transfer to the matching device.
"""
import struct
import sys
from collections import Counter

path, VID, PID = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16)
data = open(path, "rb").read()
magic = struct.unpack_from("<I", data, 0)[0]
assert magic in (0xA1B2C3D4, 0xA1B23C4D), "not a pcap file"
linktype = struct.unpack_from("<I", data, 20)[0]
assert linktype == 249, f"unexpected linktype {linktype}"

packets = []
off = 24
while off + 16 <= len(data):
    ts_s, ts_us, incl, orig = struct.unpack_from("<IIII", data, off)
    off += 16
    pkt = data[off:off + incl]
    off += incl
    if len(pkt) < 27:
        continue
    hlen, irp, status, func, info, bus, dev, ep, xfer, dlen = struct.unpack_from("<HQIHBHHBBI", pkt, 0)
    stage = pkt[27] if xfer == 2 and hlen >= 28 else None
    payload = pkt[hlen:hlen + dlen]
    packets.append(dict(t=ts_s + ts_us / 1e6, bus=bus, dev=dev, ep=ep, xfer=xfer, info=info,
                        stage=stage, data=payload, status=status))
print(f"{len(packets)} packets")

# find device addresses from device descriptors (18 bytes starting 12 01)
devices = {}
for p in packets:
    d = p["data"]
    if p["xfer"] == 2 and len(d) >= 18 and d[0] == 0x12 and d[1] == 0x01:
        vid, pid = struct.unpack_from("<HH", d, 8)
        devices[(p["bus"], p["dev"])] = (vid, pid)
for k, v in sorted(devices.items()):
    print(f"  bus {k[0]} dev {k[1]}: {v[0]:04x}:{v[1]:04x}")
target = [k for k, v in devices.items() if v == (VID, PID)]
print("target:", target)
if not target:
    sys.exit("device not found")
bus, dev = target[0]

mine = [p for p in packets if p["bus"] == bus and p["dev"] == dev]
print(f"{len(mine)} packets for the device;",
      Counter((p["xfer"], p["ep"], p["info"] & 1) for p in mine).most_common(12))

# host -> device: control SETUP with data (SET_REPORT etc.) and interrupt OUT (endpoint without 0x80)
t0 = mine[0]["t"]
out = []
pending_setup = None
for p in mine:
    d = p["data"]
    if p["xfer"] == 2:                       # control
        if p["stage"] == 0 and len(d) >= 8:  # setup stage: 8-byte setup packet (+ data for OUT)
            bm, req, wval, widx, wlen = struct.unpack_from("<BBHHH", d, 0)
            if bm & 0x80 == 0 and wlen and len(d) > 8:
                out.append((p["t"] - t0, f"CTRL bm={bm:02x} req={req:02x} val={wval:04x} idx={widx}", d[8:]))
            elif bm & 0x80 == 0 and wlen:
                pending_setup = (p["t"] - t0, f"CTRL bm={bm:02x} req={req:02x} val={wval:04x} idx={widx}")
            elif bm & 0x80:
                pass
        elif p["stage"] == 1 and pending_setup and p["info"] & 1 == 0 and d:   # data stage OUT
            out.append((pending_setup[0], pending_setup[1], d))
            pending_setup = None
    elif p["xfer"] == 1 and not (p["ep"] & 0x80) and p["info"] & 1 == 0 and d:   # interrupt OUT
        out.append((p["t"] - t0, f"INT OUT ep={p['ep']:02x}", d))

print(f"\n{len(out)} host->device transfers")
open(path + ".out.txt", "w").write("\n".join(f"{t:9.3f} {k} len={len(d)} {d.hex()}" for t, k, d in out))
for t, k, d in out[:60]:
    print(f"{t:9.3f} {k} len={len(d):3d} {d[:48].hex()}{'...' if len(d) > 48 else ''}")
