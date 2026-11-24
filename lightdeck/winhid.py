"""Talk to USB HID devices through Windows' own hid.dll (ctypes, nothing extra to install).

Most RGB keyboards, mice and LED controllers take their lighting commands as HID reports.
Drivers in the `drivers` folder use these helpers:

    for dev in winhid.devices(0x258A, 0x0187, interface=1, feature_len=520):
        h = winhid.open_path(dev.path)
        winhid.set_feature(h, data)          # or winhid.write(h, data) for output reports
        winhid.close(h)
"""
import ctypes
import ctypes.wintypes as wt
import re

_setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
_hid = ctypes.WinDLL("hid", use_last_error=True)
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

DIGCF_PRESENT, DIGCF_DEVICEINTERFACE = 0x2, 0x10
GENERIC_READ, GENERIC_WRITE = 0x80000000, 0x40000000
FILE_SHARE_READ, FILE_SHARE_WRITE = 1, 2
OPEN_EXISTING = 3
INVALID_HANDLE = ctypes.c_void_p(-1).value


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("InterfaceClassGuid", GUID), ("Flags", wt.DWORD),
                ("Reserved", ctypes.c_void_p)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wt.USHORT), ("UsagePage", wt.USHORT), ("InputReportByteLength", wt.USHORT),
                ("OutputReportByteLength", wt.USHORT), ("FeatureReportByteLength", wt.USHORT),
                ("Reserved", wt.USHORT * 17), ("rest", wt.USHORT * 10)]


_setupapi.SetupDiGetClassDevsW.restype = ctypes.c_void_p
_setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
_setupapi.SetupDiEnumDeviceInterfaces.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(GUID),
                                                  wt.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
_setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [ctypes.c_void_p, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                       ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD),
                                                       ctypes.c_void_p]
_setupapi.SetupDiDestroyDeviceInfoList.argtypes = [ctypes.c_void_p]
_k32.CreateFileW.restype = ctypes.c_void_p
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, ctypes.c_void_p]
_k32.CloseHandle.argtypes = [ctypes.c_void_p]
_k32.WriteFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
_hid.HidD_GetPreparsedData.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
_hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
_hid.HidD_SetFeature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]
_hid.HidD_GetFeature.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]
_hid.HidD_SetOutputReport.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]
_hid.HidD_GetProductString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
_hid.HidD_GetManufacturerString.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]


def hid_paths():
    """Windows device paths of every HID interface that is plugged in."""
    guid = GUID()
    _hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = _setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    paths, i = [], 0
    try:
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(SP_DEVICE_INTERFACE_DATA)
            if not _setupapi.SetupDiEnumDeviceInterfaces(info, None, ctypes.byref(guid), i, ctypes.byref(iface)):
                break
            i += 1
            need = wt.DWORD()
            _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(iface), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8   # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W (64-bit)
            if _setupapi.SetupDiGetDeviceInterfaceDetailW(info, ctypes.byref(iface), buf, need, None, None):
                paths.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        _setupapi.SetupDiDestroyDeviceInfoList(info)
    return paths


def open_path(path):
    """Open a HID interface for sending. Returns a handle, or None (in use / no access)."""
    h = _k32.CreateFileW(path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                         OPEN_EXISTING, 0, None)
    if h in (None, INVALID_HANDLE):
        h = _k32.CreateFileW(path, 0, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    return None if h in (None, INVALID_HANDLE) else h


def close(h):
    if h:
        _k32.CloseHandle(h)


def caps(h):
    """Usage page, usage and report sizes of an open interface (HIDP_CAPS), or None."""
    pre = ctypes.c_void_p()
    if not _hid.HidD_GetPreparsedData(h, ctypes.byref(pre)):
        return None
    c = HIDP_CAPS()
    _hid.HidP_GetCaps(pre, ctypes.byref(c))
    _hid.HidD_FreePreparsedData(pre)
    return c


def _string(fn, h):
    buf = ctypes.create_unicode_buffer(128)
    return buf.value.strip() if fn(h, buf, ctypes.sizeof(buf)) else ""


def product_string(h):
    return _string(_hid.HidD_GetProductString, h)


def manufacturer_string(h):
    return _string(_hid.HidD_GetManufacturerString, h)


def ids_in(text):
    """All (vid, pid) pairs mentioned in a device path / location string."""
    return {(int(v, 16), int(p, 16)) for v, p in re.findall(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", text or "", re.I)}


class HidInterface:
    """One HID interface found by devices()."""

    def __init__(self, path, vid, pid, interface, caps_):
        self.path = path
        self.vid, self.pid = vid, pid
        self.interface = interface          # USB interface number (the MI_xx in the path), or None
        self.usage_page = caps_.UsagePage if caps_ else 0
        self.usage = caps_.Usage if caps_ else 0
        self.feature_len = caps_.FeatureReportByteLength if caps_ else 0
        self.output_len = caps_.OutputReportByteLength if caps_ else 0
        self.input_len = caps_.InputReportByteLength if caps_ else 0

    def __eq__(self, other):
        return isinstance(other, HidInterface) and other.path == self.path

    def __hash__(self):
        return hash(self.path)

    def __repr__(self):
        return (f"<HID {self.vid:04x}:{self.pid:04x} mi={self.interface} page={self.usage_page:04x} "
                f"usage={self.usage:02x} feature={self.feature_len} output={self.output_len}>")


def devices(vid=None, pid=None, interface=None, usage_page=None, usage=None, feature_len=None, output_len=None):
    """HID interfaces that match every filter given (None = any)."""
    out = []
    for path in hid_paths():
        ids = ids_in(path)
        if not ids:
            continue
        v, p = next(iter(ids))
        if (vid is not None and v != vid) or (pid is not None and p != pid):
            continue
        m = re.search(r"mi_([0-9a-f]{2})", path, re.I)
        mi = int(m.group(1), 16) if m else None
        if interface is not None and mi != interface:
            continue
        h = open_path(path)
        if not h:
            continue
        try:
            dev = HidInterface(path, v, p, mi, caps(h))
        finally:
            close(h)
        if usage_page is not None and dev.usage_page != usage_page:
            continue
        if usage is not None and dev.usage != usage:
            continue
        if feature_len is not None and dev.feature_len != feature_len:
            continue
        if output_len is not None and dev.output_len != output_len:
            continue
        out.append(dev)
    return out


def _buffer(data, length):
    data = bytes(data)
    if length and len(data) < length:
        data += bytes(length - len(data))
    return ctypes.create_string_buffer(data, len(data)), len(data)


def set_feature(h, data, length=None):
    """Send a feature report. data[0] is the report number (0 if the device doesn't use numbers).
    Shorter data is padded with zeros to `length`."""
    buf, n = _buffer(data, length)
    if not _hid.HidD_SetFeature(h, buf, n):
        raise OSError(ctypes.get_last_error(), "HidD_SetFeature failed")


def get_feature(h, report_id, length):
    buf = ctypes.create_string_buffer(length)
    buf[0] = report_id
    if not _hid.HidD_GetFeature(h, buf, length):
        raise OSError(ctypes.get_last_error(), "HidD_GetFeature failed")
    return buf.raw


def write(h, data, length=None):
    """Send an output report over the interrupt endpoint (what most keyboards and mice use).
    data[0] is the report number; padded with zeros to `length` (usually the output_len)."""
    buf, n = _buffer(data, length)
    done = wt.DWORD()
    if not _k32.WriteFile(h, buf, n, ctypes.byref(done), None):
        raise OSError(ctypes.get_last_error(), "WriteFile failed")


def set_output_report(h, data, length=None):
    """Send an output report over the control endpoint (some devices only accept this way)."""
    buf, n = _buffer(data, length)
    if not _hid.HidD_SetOutputReport(h, buf, n):
        raise OSError(ctypes.get_last_error(), "HidD_SetOutputReport failed")


def get_feature_into(h, buf):
    """Read a feature report into a ready buffer whose first byte is the report number."""
    if not _hid.HidD_GetFeature(h, buf, len(buf)):
        raise OSError(ctypes.get_last_error(), "HidD_GetFeature failed")


# ---------- reports by usage (Windows' HID parser does the bit packing) ----------
INPUT, OUTPUT, FEATURE = 0, 1, 2
HIDP_STATUS_SUCCESS = 0x00110000


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [("UsagePage", wt.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                ("BitField", wt.USHORT), ("LinkCollection", wt.USHORT), ("LinkUsage", wt.USHORT),
                ("LinkUsagePage", wt.USHORT), ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte),
                ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte), ("HasNull", ctypes.c_ubyte),
                ("Reserved", ctypes.c_ubyte), ("BitSize", wt.USHORT), ("ReportCount", wt.USHORT),
                ("Reserved2", wt.USHORT * 5), ("UnitsExp", wt.ULONG), ("Units", wt.ULONG),
                ("LogicalMin", wt.LONG), ("LogicalMax", wt.LONG), ("PhysicalMin", wt.LONG), ("PhysicalMax", wt.LONG),
                # union: Range (UsageMin, UsageMax, StringMin, StringMax, DesignatorMin, DesignatorMax,
                # DataIndexMin, DataIndexMax) or NotRange (Usage, -, StringIndex, -, DesignatorIndex, -, DataIndex, -)
                ("u", wt.USHORT * 8)]


class HIDP_LINK_COLLECTION_NODE(ctypes.Structure):
    _fields_ = [("LinkUsage", wt.USHORT), ("LinkUsagePage", wt.USHORT), ("Parent", wt.USHORT),
                ("NumberOfChildren", wt.USHORT), ("NextSibling", wt.USHORT), ("FirstChild", wt.USHORT),
                ("Bits", wt.ULONG), ("UserContext", ctypes.c_void_p)]


class HIDP_DATA(ctypes.Structure):
    _fields_ = [("DataIndex", wt.USHORT), ("Reserved", wt.USHORT), ("RawValue", wt.ULONG)]


_hid.HidP_MaxDataListLength.argtypes = [ctypes.c_int, ctypes.c_void_p]
_hid.HidP_MaxDataListLength.restype = wt.ULONG
_hid.HidP_GetValueCaps.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wt.USHORT), ctypes.c_void_p]
_hid.HidP_GetLinkCollectionNodes.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.ULONG), ctypes.c_void_p]
_hid.HidP_InitializeReportForID.argtypes = [ctypes.c_int, ctypes.c_ubyte, ctypes.c_void_p, ctypes.c_void_p,
                                            wt.ULONG]
_hid.HidP_SetData.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wt.ULONG), ctypes.c_void_p,
                              ctypes.c_void_p, wt.ULONG]
_hid.HidP_GetData.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wt.ULONG), ctypes.c_void_p,
                              ctypes.c_void_p, wt.ULONG]
_hid.HidP_SetUsageValueArray.argtypes = [ctypes.c_int, wt.USHORT, wt.USHORT, wt.USHORT, ctypes.c_void_p,
                                         wt.USHORT, ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]
_hid.HidP_GetUsageValueArray.argtypes = [ctypes.c_int, wt.USHORT, wt.USHORT, wt.USHORT, ctypes.c_void_p,
                                         wt.USHORT, ctypes.c_void_p, ctypes.c_void_p, wt.ULONG]
for _f in ("HidP_GetValueCaps", "HidP_GetLinkCollectionNodes", "HidP_InitializeReportForID", "HidP_SetData",
           "HidP_GetData", "HidP_SetUsageValueArray", "HidP_GetUsageValueArray", "HidP_GetCaps"):
    getattr(_hid, _f).restype = ctypes.c_long


def _ok(status, what):
    if (status & 0xFFFFFFFF) != HIDP_STATUS_SUCCESS:
        raise OSError(status & 0xFFFFFFFF, f"{what} failed (0x{status & 0xFFFFFFFF:08x})")


class Reports:
    """Fill in and read an interface's reports by usage instead of byte positions.

    Windows reads the device's report description and does the bit packing, so a driver for a
    standard device (like a Dynamic Lighting lamp array) works whatever report numbers and sizes
    that particular device uses.
    """

    def __init__(self, h):
        self.pre = ctypes.c_void_p()
        if not _hid.HidD_GetPreparsedData(h, ctypes.byref(self.pre)):
            raise OSError(ctypes.get_last_error(), "HidD_GetPreparsedData failed")
        self.caps = HIDP_CAPS()
        _ok(_hid.HidP_GetCaps(self.pre, ctypes.byref(self.caps)), "HidP_GetCaps")
        n = wt.ULONG(max(1, self.caps.rest[0]))
        nodes = (HIDP_LINK_COLLECTION_NODE * n.value)()
        _ok(_hid.HidP_GetLinkCollectionNodes(nodes, ctypes.byref(n), self.pre), "HidP_GetLinkCollectionNodes")
        self.nodes = [(nodes[i].LinkUsagePage, nodes[i].LinkUsage) for i in range(n.value)]
        self.values = {}
        self.data_count = {}
        for rtype, count_i, data_i in ((INPUT, 2, 3), (OUTPUT, 5, 6), (FEATURE, 8, 9)):
            cnt = wt.USHORT(self.caps.rest[count_i])
            self.data_count[rtype] = max(self.caps.rest[data_i], _hid.HidP_MaxDataListLength(rtype, self.pre))
            if not cnt.value:
                self.values[rtype] = []
                continue
            arr = (HIDP_VALUE_CAPS * cnt.value)()
            _ok(_hid.HidP_GetValueCaps(rtype, arr, ctypes.byref(cnt), self.pre), "HidP_GetValueCaps")
            self.values[rtype] = [arr[i] for i in range(cnt.value)]

    def close(self):
        if self.pre:
            _hid.HidD_FreePreparsedData(self.pre)
            self.pre = None

    def length(self, rtype):
        return {INPUT: self.caps.InputReportByteLength, OUTPUT: self.caps.OutputReportByteLength,
                FEATURE: self.caps.FeatureReportByteLength}[rtype]

    def collection(self, page, usage):
        """Index of the (logical) collection with this usage, or None."""
        for i, node in enumerate(self.nodes):
            if node == (page, usage):
                return i
        return None

    def report_type(self, coll):
        """Which kind of report a collection's values travel in (FEATURE preferred), or None."""
        for rtype in (FEATURE, OUTPUT, INPUT):
            if any(c.LinkCollection == coll for c in self.values[rtype]):
                return rtype
        return None

    def report_id(self, rtype, coll):
        return next(c.ReportID for c in self.values[rtype] if c.LinkCollection == coll)

    def slots(self, rtype, coll, page, usage):
        """Where a usage sits in a collection's report, in report order: a list of
        ("index", data_index) for single values or ("array", cap) for a value array."""
        out = []
        for c in self.values[rtype]:
            if c.LinkCollection != coll or c.UsagePage != page:
                continue
            if c.IsRange:
                if c.u[0] <= usage <= c.u[1]:
                    out.append((c.u[6] + usage - c.u[0], ("index", c.u[6] + usage - c.u[0])))
            elif c.u[0] == usage:
                if c.ReportCount > 1:
                    out.append((c.u[6], ("array", c)))
                else:
                    out.append((c.u[6], ("index", c.u[6])))
        return [s for _, s in sorted(out, key=lambda x: x[0])]

    def count(self, rtype, coll, page, usage):
        """How many values of a usage fit in one report (e.g. lamps per update)."""
        return sum(c.ReportCount if kind == "array" else 1
                   for kind, c in self.slots(rtype, coll, page, usage))

    def new(self, rtype, report_id):
        n = self.length(rtype)
        buf = ctypes.create_string_buffer(n)
        _ok(_hid.HidP_InitializeReportForID(rtype, report_id, self.pre, buf, n), "HidP_InitializeReportForID")
        return buf

    def set(self, rtype, buf, coll, page, usage, values):
        """Write values (one per occurrence of the usage, in report order) into a report buffer."""
        values = list(values)
        singles = []
        for kind, x in self.slots(rtype, coll, page, usage):
            if not values:
                break
            if kind == "index":
                singles.append((x, values.pop(0)))
            else:
                part, values = values[:x.ReportCount], values[x.ReportCount:]
                part += [0] * (x.ReportCount - len(part))
                bits = 0
                for i, v in enumerate(part):
                    bits |= (int(v) & ((1 << x.BitSize) - 1)) << (i * x.BitSize)
                raw = bits.to_bytes((x.BitSize * x.ReportCount + 7) // 8, "little")
                _ok(_hid.HidP_SetUsageValueArray(rtype, page, coll, usage, raw, len(raw), self.pre, buf, len(buf)),
                    "HidP_SetUsageValueArray")
        if singles:
            data = (HIDP_DATA * len(singles))()
            for i, (idx, v) in enumerate(singles):
                data[i].DataIndex, data[i].RawValue = idx, int(v) & 0xFFFFFFFF
            n = wt.ULONG(len(singles))
            _ok(_hid.HidP_SetData(rtype, data, ctypes.byref(n), self.pre, buf, len(buf)), "HidP_SetData")

    def get(self, rtype, buf, coll, page, usage):
        """Read every occurrence of a usage from a report buffer, in report order."""
        slots = self.slots(rtype, coll, page, usage)
        if not slots:
            return []
        n = wt.ULONG(max(1, self.data_count[rtype]))
        data = (HIDP_DATA * n.value)()
        _ok(_hid.HidP_GetData(rtype, data, ctypes.byref(n), self.pre, buf, len(buf)), "HidP_GetData")
        by_index = {data[i].DataIndex: data[i].RawValue for i in range(n.value)}
        out = []
        for kind, x in slots:
            if kind == "index":
                out.append(by_index.get(x, 0))
            else:
                size = (x.BitSize * x.ReportCount + 7) // 8
                raw = ctypes.create_string_buffer(size)
                _ok(_hid.HidP_GetUsageValueArray(rtype, page, coll, usage, raw, size, self.pre, buf, len(buf)),
                    "HidP_GetUsageValueArray")
                bits = int.from_bytes(raw.raw, "little")
                out += [(bits >> (i * x.BitSize)) & ((1 << x.BitSize) - 1) for i in range(x.ReportCount)]
        return out
