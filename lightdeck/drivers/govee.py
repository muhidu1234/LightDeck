"""Govee Wi-Fi lights, with Govee's "LAN Control" (switch it on per light in the Govee Home app).

Govee's LAN API, UDP and JSON:
  find      send {"msg": {"cmd": "scan", "data": {"account_topic": "reserve"}}} to 239.255.255.250:4001;
            lights answer on port 4002 with {"msg": {"cmd": "scan", "data": {"ip", "device", "sku", ...}}}
  control   to <ip>:4003:  {"msg": {"cmd": "turn", "data": {"value": 1}}}
                           {"msg": {"cmd": "brightness", "data": {"value": 1-100}}}
                           {"msg": {"cmd": "colorwc", "data": {"color": {"r", "g", "b"}, "colorTemInKelvin": 0}}}
The LAN API sets one color for the whole light, so the light shows the effect's average color.
"""
import json
import socket
import time

import nethelp
from driver_base import Driver

GROUP, SCAN_PORT, REPLY_PORT, CONTROL_PORT = "239.255.255.250", 4001, 4002, 4003


def message(cmd, data):
    return json.dumps({"msg": {"cmd": cmd, "data": data}}).encode()


class Govee(Driver):
    name = "Govee light"
    kind_name = "Govee"
    network = True
    bus = "Wi-Fi"
    zone_name = "Light"
    leds = 1
    max_fps = 10
    keepalive = None
    pair_hint = ("Govee lights need \"LAN Control\" switched on: open the Govee Home app, pick the light, "
                 "open its settings and turn on LAN Control.")
    note = ("Govee light over your network (LAN Control). Govee lets other apps set one color for the whole "
            "light, so it shows the effect's average color, up to 10 times a second.")

    @classmethod
    def discover(cls, timeout=2.0):
        rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        rx.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            rx.bind(("", REPLY_PORT))
        except OSError:
            rx.close()
            raise OSError("port 4002 is busy (is Govee's own app open?) - add the light by its IP address instead")
        rx.settimeout(0.2)
        try:
            for ip in nethelp.local_ipv4s() or ["0.0.0.0"]:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as tx:
                    tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                    if ip != "0.0.0.0":
                        tx.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(ip))
                    tx.sendto(message("scan", {"account_topic": "reserve"}), (GROUP, SCAN_PORT))
            found, end = {}, time.time() + timeout
            while time.time() < end:
                try:
                    data, (src, _p) = rx.recvfrom(4096)
                except (socket.timeout, OSError):
                    continue
                try:
                    d = json.loads(data)["msg"]["data"]
                except (ValueError, KeyError, TypeError):
                    continue
                ip = d.get("ip") or src
                found[ip] = {"address": ip, "name": f"Govee {d.get('sku', '')}".strip(), "id": d.get("device") or ip}
            return list(found.values())
        finally:
            rx.close()

    @classmethod
    def probe(cls, address):
        socket.inet_aton(address)            # just check it's an IP address; Govee has no "who are you" call
        return {"address": address, "name": f"Govee light {address}", "id": address}

    def connect(self, found):
        self.sock = nethelp.udp_sender(found["address"], CONTROL_PORT)
        self.sock.send(message("turn", {"value": 1}))
        self.sock.send(message("brightness", {"value": 100}))
        self.last = None

    def send(self, colors):
        r, g, b = colors[0]
        if self.last and max(abs(r - self.last[0]), abs(g - self.last[1]), abs(b - self.last[2])) < 4:
            return
        self.sock.send(message("colorwc", {"color": {"r": r, "g": g, "b": b}, "colorTemInKelvin": 0}))
        self.last = (r, g, b)

    def disconnect(self):
        sock = getattr(self, "sock", None)
        if sock:
            sock.close()
