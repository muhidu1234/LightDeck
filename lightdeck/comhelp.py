"""Talk to Windows COM objects by name (late binding through IDispatch), with nothing but ctypes.

Used by bridges to vendor apps that offer a COM interface (e.g. ASUS Armoury Crate's Aura SDK).

    import comhelp
    comhelp.init()                                  # once per thread that uses COM
    sdk = comhelp.create("aura.sdk.1")
    sdk.call("SwitchMode")
    devices = sdk.call("Enumerate", 0)              # -> Dispatch
    n = devices.get("Count")
    dev = devices.get("Item", 0)
    light.put("Color", 0x0000FF)

Every object must be used on the thread that created it.
"""
import ctypes
import ctypes.wintypes as w

ole32 = ctypes.OleDLL("ole32")
oleaut32 = ctypes.WinDLL("oleaut32")
oleaut32.SysAllocString.restype = ctypes.c_void_p
oleaut32.SysAllocString.argtypes = [ctypes.c_wchar_p]
oleaut32.VariantClear.argtypes = [ctypes.c_void_p]

VT_EMPTY, VT_I2, VT_I4, VT_R4, VT_R8, VT_BSTR, VT_DISPATCH, VT_BOOL = 0, 2, 3, 4, 5, 8, 9, 11
VT_UNKNOWN, VT_I1, VT_UI1, VT_UI2, VT_UI4, VT_I8, VT_UI8, VT_INT, VT_UINT = 13, 16, 17, 18, 19, 20, 21, 22, 23
METHOD, GET, PUT = 1, 2, 4
DISPID_PROPERTYPUT = -3


class GUID(ctypes.Structure):
    _fields_ = [("a", w.DWORD), ("b", w.WORD), ("c", w.WORD), ("d", ctypes.c_ubyte * 8)]


IID_NULL = GUID()
IID_IDispatch = GUID(0x00020400, 0, 0, (ctypes.c_ubyte * 8)(0xC0, 0, 0, 0, 0, 0, 0, 0x46))


class _Val(ctypes.Union):
    _fields_ = [("llVal", ctypes.c_longlong), ("lVal", ctypes.c_long), ("ulVal", ctypes.c_ulong),
                ("iVal", ctypes.c_short), ("bVal", ctypes.c_ubyte), ("fltVal", ctypes.c_float),
                ("dblVal", ctypes.c_double), ("ptr", ctypes.c_void_p), ("pad", ctypes.c_void_p * 2)]


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("v", _Val)]


class DISPPARAMS(ctypes.Structure):
    _fields_ = [("rgvarg", ctypes.POINTER(VARIANT)), ("rgdispidNamedArgs", ctypes.POINTER(ctypes.c_long)),
                ("cArgs", ctypes.c_uint), ("cNamedArgs", ctypes.c_uint)]


class EXCEPINFO(ctypes.Structure):
    _fields_ = [("wCode", w.WORD), ("wReserved", w.WORD), ("bstrSource", ctypes.c_void_p),
                ("bstrDescription", ctypes.c_void_p), ("bstrHelpFile", ctypes.c_void_p),
                ("dwHelpContext", w.DWORD), ("pvReserved", ctypes.c_void_p), ("pfnDeferredFillIn", ctypes.c_void_p),
                ("scode", ctypes.c_long)]


_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
_GetIDsOfNames = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.POINTER(GUID),
                                    ctypes.POINTER(ctypes.c_wchar_p), ctypes.c_uint, w.DWORD,
                                    ctypes.POINTER(ctypes.c_long))
_Invoke = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, ctypes.c_long, ctypes.POINTER(GUID), w.DWORD,
                             w.WORD, ctypes.POINTER(DISPPARAMS), ctypes.POINTER(VARIANT),
                             ctypes.POINTER(EXCEPINFO), ctypes.POINTER(ctypes.c_uint))


def init():
    """Start COM on this thread (single-threaded apartment). Safe to call twice."""
    try:
        ole32.CoInitialize(None)
    except OSError:
        pass                                   # already started on this thread (in another mode)


def uninit():
    try:
        ole32.CoUninitialize()
    except OSError:
        pass


def registered(progid):
    """True if a COM object with this name is installed (e.g. "aura.sdk.1")."""
    clsid = GUID()
    try:
        ole32.CLSIDFromProgID(progid, ctypes.byref(clsid))
        return True
    except OSError:
        return False


def create(progid):
    clsid = GUID()
    ole32.CLSIDFromProgID(progid, ctypes.byref(clsid))
    ptr = ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(clsid), None, 0x17, ctypes.byref(IID_IDispatch), ctypes.byref(ptr))
    return Dispatch(ptr.value)


def _to_variant(value, var):
    if isinstance(value, bool):
        var.vt, var.v.iVal = VT_BOOL, -1 if value else 0
    elif isinstance(value, int):
        if -2 ** 31 <= value < 2 ** 31:
            var.vt, var.v.lVal = VT_I4, value
        else:
            var.vt, var.v.llVal = VT_I8, value
    elif isinstance(value, float):
        var.vt, var.v.dblVal = VT_R8, value
    elif isinstance(value, str):
        var.vt, var.v.ptr = VT_BSTR, oleaut32.SysAllocString(value)
    elif isinstance(value, Dispatch):
        var.vt, var.v.ptr = VT_DISPATCH, value.ptr
    elif value is None:
        var.vt = VT_EMPTY
    else:
        raise TypeError(f"can't pass {type(value).__name__} to COM")


def _from_variant(var):
    vt = var.vt
    if vt in (VT_EMPTY, 1):
        return None
    if vt == VT_DISPATCH:
        p = var.v.ptr
        var.vt = VT_EMPTY                       # the Dispatch below owns the reference now
        return Dispatch(p) if p else None
    if vt == VT_BSTR:
        s = ctypes.wstring_at(var.v.ptr) if var.v.ptr else ""
        oleaut32.VariantClear(ctypes.byref(var))
        return s
    if vt == VT_BOOL:
        return var.v.iVal != 0
    simple = {VT_I2: "iVal", VT_I4: "lVal", VT_INT: "lVal", VT_UI4: "ulVal", VT_UINT: "ulVal", VT_I8: "llVal",
              VT_UI8: "llVal", VT_UI1: "bVal", VT_I1: "bVal", VT_UI2: "iVal", VT_R4: "fltVal", VT_R8: "dblVal"}
    if vt in simple:
        return getattr(var.v, simple[vt])
    oleaut32.VariantClear(ctypes.byref(var))
    raise TypeError(f"COM returned a value of type {vt} that LightDeck can't read")


class Dispatch:
    """One COM object; call methods and read/write properties by name."""

    def __init__(self, ptr):
        self.ptr = ptr
        vtbl = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        self._release = _Release(vtbl[2])
        self._ids = _GetIDsOfNames(vtbl[5])
        self._invoke = _Invoke(vtbl[6])
        self._cache = {}

    def dispid(self, name):
        if name not in self._cache:
            out = ctypes.c_long()
            names = (ctypes.c_wchar_p * 1)(name)
            self._ids(self.ptr, ctypes.byref(IID_NULL), names, 1, 0x400, ctypes.byref(out))
            self._cache[name] = out.value
        return self._cache[name]

    def _do(self, name, flags, args):
        n = len(args)
        vargs = (VARIANT * max(1, n))()
        for i, a in enumerate(reversed(args)):          # COM wants the arguments last to first
            _to_variant(a, vargs[i])
        params = DISPPARAMS(vargs, None, n, 0)
        named = ctypes.c_long(DISPID_PROPERTYPUT)
        if flags == PUT:
            params.rgdispidNamedArgs, params.cNamedArgs = ctypes.pointer(named), 1
        result, exc, bad = VARIANT(), EXCEPINFO(), ctypes.c_uint()
        try:
            self._invoke(self.ptr, self.dispid(name), ctypes.byref(IID_NULL), 0x400, flags, ctypes.byref(params),
                         ctypes.byref(result), ctypes.byref(exc), ctypes.byref(bad))
        finally:
            for i, a in enumerate(reversed(args)):
                if isinstance(a, str):
                    oleaut32.VariantClear(ctypes.byref(vargs[i]))
        return _from_variant(result)

    def call(self, name, *args):
        return self._do(name, METHOD | GET, args)

    def get(self, name, *args):
        return self._do(name, GET | METHOD, args)

    def put(self, name, *args):
        """put("Color", value) or put("Item", index, value)."""
        return self._do(name, PUT, args)

    def items(self, count="Count", item="Item"):
        """The objects in a COM collection (Count + Item(i))."""
        return [self.get(item, i) for i in range(self.get(count))]

    def __del__(self):
        if self.ptr:
            try:
                self._release(self.ptr)
            except Exception:
                pass
            self.ptr = None
