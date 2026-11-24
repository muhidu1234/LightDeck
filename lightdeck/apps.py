"""Other RGB apps: which ones are running, and how LightDeck gets along with each.

Two programs that both send colors to the same light make it flicker between them. For some apps
LightDeck can work *through* the app (a bridge in the drivers folder); for the others the app's
lighting has to be switched off or the app closed while LightDeck runs.
"""
import ctypes
import ctypes.wintypes as w
import os
import time

# how LightDeck works with each app:
#   "bridge" = LightDeck drives that app's devices through it, so it may stay open
#   "close"  = it fights LightDeck over the lights: close it (or turn its lighting off)
#   "ok"     = no conflict
RGB_APPS = [
    # name,                       process names (lower case),                                   how,     tip
    ("SignalRGB",                 ["signalrgb.exe", "signalrgblauncher.exe"],                    "close",
     "SignalRGB drives the same lights. Quit it from its tray icon while LightDeck runs."),
    ("Corsair iCUE",              ["icue.exe", "icuedevicepluginhost.exe"],                      "bridge",
     "LightDeck can drive Corsair devices through iCUE (needs Corsair's iCUESDK.x64_2019.dll in the drivers folder). "
     "Without it, quit iCUE so OpenRGB can drive them."),
    ("ASUS Armoury Crate / Aura", ["armourycrate.exe", "lightingservice.exe", "aurasyncservice.exe"], "bridge",
     "LightDeck drives ASUS (Aura) lights through Armoury Crate when OpenRGB doesn't already drive them."),
    ("Logitech G HUB",            ["lghub.exe", "lghub_agent.exe", "lghub_system_tray.exe"],     "bridge",
     "LightDeck drives Logitech lights through G HUB. In G HUB, Settings: leave "
     "\"Allow games & applications to control my lighting\" on."),
    ("Logitech Gaming Software",  ["lcore.exe"],                                                 "bridge",
     "LightDeck drives Logitech lights through it (same lighting link as G HUB)."),
    ("Razer Synapse",             ["razer synapse 3.exe", "razer synapse service.exe", "razerappengine.exe",
                                   "rzchromasdkservice.exe", "razer chroma sdk service.exe"],     "bridge",
     "LightDeck drives Razer devices through Synapse's Chroma SDK."),
    ("SteelSeries GG",            ["steelseriesgg.exe", "steelseriesengine.exe", "steelseriesengine3.exe"], "bridge",
     "LightDeck drives SteelSeries devices through GG (GameSense)."),
    ("MSI Center / Mystic Light", ["ledkeeper2.exe", "ledkeeper.exe", "mysticlight.exe", "msi.centralserver.exe",
                                   "mystic_light_service.exe"],                                   "close",
     "OpenRGB drives MSI boards and graphics cards itself: turn Mystic Light off or close MSI Center."),
    ("Gigabyte RGB Fusion / Control Center", ["rgbfusion.exe", "gcc.exe", "gigabytecontrolcenter.exe"], "close",
     "OpenRGB drives Gigabyte boards and cards itself: close RGB Fusion / Gigabyte Control Center."),
    ("ASRock Polychrome",         ["polychrome rgb.exe", "asrpolychromergb.exe", "polychromergb.exe"], "close",
     "OpenRGB drives ASRock boards itself: close Polychrome RGB."),
    ("NZXT CAM",                  ["nzxt cam.exe"],                                              "close",
     "NZXT CAM keeps sending its own lighting: in CAM turn lighting control off, or close it."),
    ("Cooler Master MasterPlus",  ["masterplus.exe", "masterctrl.exe", "masterplusapp.exe"],     "close",
     "Close MasterPlus so OpenRGB can drive Cooler Master devices."),
    ("HyperX NGENUITY",           ["ngenuity2.exe", "hyperx ngenuity.exe", "ngenuity.exe"],      "close",
     "Close NGENUITY so OpenRGB can drive HyperX devices."),
    ("Wooting Wootility",         ["wootility.exe"],                                             "ok",
     "Wootility can stay open; OpenRGB drives Wooting keyboards."),
    ("Lian Li L-Connect",         ["l-connect 3.exe", "l-connect.exe", "lconnect3.exe"],         "close",
     "Close L-Connect so OpenRGB can drive Lian Li fans and hubs."),
    ("Thermaltake TT RGB Plus",   ["tt rgb plus.exe", "ttrgbplus.exe"],                          "close",
     "Close TT RGB Plus so OpenRGB can drive Thermaltake devices."),
    ("Alienware Command Center",  ["awcc.exe", "awcc.background.server.exe"],                    "close",
     "Turn AlienFX lighting off in Command Center so it doesn't override LightDeck."),
    ("Roccat Swarm",              ["roccat_swarm.exe", "roccat_swarm_monitor.exe"],              "close",
     "Close Roccat Swarm so OpenRGB can drive Roccat devices."),
    ("Philips Hue Sync",          ["huesync.exe"],                                               "close",
     "Hue Sync streams to the same Hue lights: stop syncing (or close it) to use them in LightDeck."),
    ("Artemis",                   ["artemis.ui.windows.exe", "artemis.exe"],                     "close",
     "Artemis is another RGB effects app: close it while LightDeck runs."),
    ("Aurora",                    ["aurora.exe"],                                                "close",
     "Aurora is another RGB effects app: close it while LightDeck runs."),
]


class _Entry(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ProcessID", w.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", w.DWORD), ("cntThreads", w.DWORD),
                ("th32ParentProcessID", w.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", w.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


_k32 = ctypes.WinDLL("kernel32", use_last_error=True) if os.name == "nt" else None
_cache = (0.0, set())


def running_processes():
    """Lower-case names of all running programs (e.g. {"icue.exe", ...}); cached for 2 s."""
    global _cache
    if _k32 is None:
        return set()
    if time.monotonic() - _cache[0] < 2:
        return _cache[1]
    _k32.CreateToolhelp32Snapshot.restype = w.HANDLE
    snap = _k32.CreateToolhelp32Snapshot(2, 0)          # TH32CS_SNAPPROCESS
    names = set()
    if snap and snap != w.HANDLE(-1).value:
        e = _Entry()
        e.dwSize = ctypes.sizeof(_Entry)
        ok = _k32.Process32FirstW(w.HANDLE(snap), ctypes.byref(e))
        while ok:
            names.add(e.szExeFile.lower())
            ok = _k32.Process32NextW(w.HANDLE(snap), ctypes.byref(e))
        _k32.CloseHandle(w.HANDLE(snap))
    _cache = (time.monotonic(), names)
    return names


def is_running(*process_names):
    procs = running_processes()
    return any(p.lower() in procs for p in process_names)


def running_rgb_apps():
    """[(name, how, tip)] for the RGB apps running right now."""
    procs = running_processes()
    return [(name, how, tip) for name, exes, how, tip in RGB_APPS if any(x in procs for x in exes)]


def conflicts():
    """The running apps that fight LightDeck over the lights."""
    return [a for a in running_rgb_apps() if a[1] == "close"]


def close_app(name):
    """Close a running RGB app (only when the user clicks "Close it"). True if it is gone afterwards.
    Apps that run as a Windows service can't be closed without admin rights: then it returns False."""
    import subprocess
    global _cache
    exes = next((e for n, e, _, _ in RGB_APPS if n == name), [])
    procs = running_processes()
    for exe in [x for x in exes if x in procs]:
        subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True, creationflags=0x08000000)
    time.sleep(0.5)
    _cache = (0.0, set())
    return not is_running(*exes)


if __name__ == "__main__":
    for name, how, tip in running_rgb_apps():
        print(f"{name}: {how} - {tip}")
