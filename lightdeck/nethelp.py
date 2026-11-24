"""Small network helpers for Wi-Fi light drivers (standard library only).

    mdns_browse("_wled._tcp.local")   -> [{"name", "host", "address", "port"}]  lights that announce themselves
    http_json("GET", "http://192.168.1.20/json/info")                          JSON over HTTP
    udp_sender(address, port)         -> a socket connected to the light, for fast color streams

Everything stays on the local network; nothing goes to the internet.
"""
import json
import random
import socket
import struct
import time
import urllib.error
import urllib.request

MDNS_GROUP, MDNS_PORT = "224.0.0.251", 5353


def http_json(method, url, body=None, timeout=2.0):
    """Send a request and return the JSON reply (or None for an empty reply).
    Raises OSError if the light can't be reached or answers with an error."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        raise OSError(f"HTTP {e.code} from {url.split('/')[2]}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        raise OSError(f"can't reach {url.split('/')[2]} ({reason})") from None
    return json.loads(raw) if raw.strip() else None


def udp_sender(address, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((address, port))
    return s


def local_ipv4s():
    """This PC's IPv4 addresses on its networks (to send discovery messages from each)."""
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except OSError:
        pass
    try:   # the address used for the default route
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))      # documentation address: nothing is actually sent
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in ips if not ip.startswith("127.") and not ip.startswith("169.254."))


# ---------- mDNS (how WLED, Nanoleaf and Hue announce themselves) ----------
def _encode_name(name):
    out = b""
    for part in name.strip(".").split("."):
        out += bytes([len(part)]) + part.encode()
    return out + b"\x00"


def _read_name(data, off, depth=0):
    labels = []
    while off < len(data):
        n = data[off]
        if n == 0:
            return ".".join(labels), off + 1
        if n & 0xC0 == 0xC0:                       # compressed: pointer to an earlier name
            if depth > 10:
                raise ValueError("bad name")
            ptr = struct.unpack_from(">H", data, off)[0] & 0x3FFF
            rest, _ = _read_name(data, ptr, depth + 1)
            labels.append(rest)
            return ".".join(l for l in labels if l), off + 2
        labels.append(data[off + 1:off + 1 + n].decode("utf-8", "replace"))
        off += 1 + n
    raise ValueError("name runs past the packet")


def _parse_records(data):
    """All answer/authority/additional records of a DNS packet: [(name, type, rdata offset, rdlen)]"""
    _id, _flags, qd, an, ns, ar = struct.unpack_from(">6H", data, 0)
    off = 12
    for _ in range(qd):
        _, off = _read_name(data, off)
        off += 4
    recs = []
    for _ in range(an + ns + ar):
        name, off = _read_name(data, off)
        rtype, _cls, _ttl, rdlen = struct.unpack_from(">HHIH", data, off)
        off += 10
        recs.append((name.lower(), rtype, off, rdlen))
        off += rdlen
    return recs


def mdns_browse(service, timeout=2.0):
    """Ask the network which devices offer a service (e.g. "_wled._tcp.local").
    Returns [{"name", "host", "address", "port"}]."""
    query = struct.pack(">6H", random.randrange(65536), 0, 1, 0, 0, 0) + _encode_name(service) \
        + struct.pack(">HH", 12, 0x8001)          # PTR question, "please answer me directly"
    socks = []
    for ip in local_ipv4s() or ["0.0.0.0"]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
            if ip != "0.0.0.0":
                s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
            s.bind((ip, 0))
            s.setblocking(False)
            s.sendto(query, (MDNS_GROUP, MDNS_PORT))
            socks.append(s)
        except OSError:
            continue
    instances, srv, addrs, from_ip = {}, {}, {}, {}
    end = time.time() + timeout
    while time.time() < end and socks:
        got = False
        for s in socks:
            try:
                data, (src, _p) = s.recvfrom(9000)
            except (BlockingIOError, OSError):
                continue
            got = True
            try:
                for name, rtype, off, rdlen in _parse_records(data):
                    if rtype == 12 and name == service.lower():             # PTR -> instance
                        inst, _ = _read_name(data, off)
                        instances[inst.lower()] = inst
                        from_ip[inst.lower()] = src
                    elif rtype == 33:                                        # SRV -> host, port
                        port = struct.unpack_from(">H", data, off + 4)[0]
                        host, _ = _read_name(data, off + 6)
                        srv[name] = (host.lower(), port)
                    elif rtype == 1 and rdlen == 4:                          # A -> IPv4
                        addrs[name] = socket.inet_ntoa(data[off:off + 4])
            except (ValueError, struct.error, IndexError):
                continue
        if not got:
            time.sleep(0.03)
    for s in socks:
        s.close()
    out = []
    for key, inst in instances.items():
        host, port = srv.get(key, ("", 0))
        address = addrs.get(host) or from_ip.get(key)
        if address:
            nice = inst[:-len(service) - 1] if inst.lower().endswith("." + service.lower()) else inst
            out.append({"name": nice, "host": host, "address": address, "port": port})
    return out
