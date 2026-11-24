"""Build LightDeck.exe and the shareable zip for friends.

Run from the folder that contains `lightdeck` and `build`:
    python build/make_package.py
Creates  build/package/LightDeck-<version>/  and  Desktop/LightDeck-<version>-Windows.zip
(no personal settings are included - each PC starts fresh).
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

root = pathlib.Path(__file__).resolve().parent.parent
src = root / "lightdeck"
build = root / "build"
version = re.search(r'VERSION = "([^"]+)"', (src / "engine.py").read_text(encoding="utf-8")).group(1)

# 1. the .exe
cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--windowed", "--name", "LightDeck",
       "--icon", str(src / "lightdeck.ico"), "--distpath", str(build / "dist"), "--workpath", str(build / "work"),
       "--specpath", str(build), "--paths", str(src)]
for m in ("openrgb", "devscan", "winhid", "driver_base", "nethelp", "report", "usbcapture", "hud", "effect_base"):
    cmd += ["--hidden-import", m]
cmd.append(str(src / "app.py"))
print("building LightDeck.exe ...")
subprocess.run(cmd, check=True, capture_output=True)

# 2. the package folder
pkg = build / "package" / f"LightDeck-{version}"
if pkg.exists():
    shutil.rmtree(pkg)
app = pkg / "LightDeck"
shutil.copytree(build / "dist" / "LightDeck", app)
for sub in ("effects", "drivers"):        # editable: hot-loaded from next to the exe
    (app / sub).mkdir()
    for f in (src / sub).glob("*.py"):
        shutil.copy2(f, app / sub)
for f in ("lightdeck.ico", "README.md"):
    shutil.copy2(src / f, app / f)
orgb = pathlib.Path(os.environ["LOCALAPPDATA"]) / "Programs" / "OpenRGB" / "OpenRGB Windows 64-bit"
if not orgb.exists():
    orgb = pathlib.Path(os.environ["LOCALAPPDATA"]) / "Programs" / "LightDeck" / "OpenRGB"
shutil.copytree(orgb, app / "OpenRGB", ignore=shutil.ignore_patterns("*.log"))
lic = app / "LICENSES"
lic.mkdir()
for f in ("GPL-3.0.txt", "GPL-2.0.txt"):
    shutil.copy2(build / "licenses" / f, lic / f)
shutil.copy2(build / "pkg_src" / "THIRD-PARTY-NOTICES.txt", lic)

# 3. source code (GPL v3: the source travels with the program)
s = pkg / "source"
(s / "effects").mkdir(parents=True)
(s / "drivers").mkdir()
for f in ("app.py", "engine.py", "hud.py", "effect_base.py", "driver_base.py", "winhid.py", "nethelp.py", "report.py", "usbcapture.py", "devscan.py", "startup.py", "lightdeck.ico", "README.md"):
    shutil.copy2(src / f, s / f)
for sub in ("effects", "drivers"):
    for f in (src / sub).glob("*.py"):
        shutil.copy2(f, s / sub)
shutil.copy2(build / "licenses" / "GPL-3.0.txt", s / "LICENSE")
shutil.copy2(__file__, s / "make_package.py")

# 4. installer
for f in ("Install LightDeck.cmd", "Uninstall LightDeck.cmd", "READ ME FIRST.txt"):
    shutil.copy2(build / "pkg_src" / f, pkg / f)
shutil.copytree(build / "pkg_src" / "setup", pkg / "setup")
assert not (app / "config.json").exists(), "personal settings must not ship"

# 5. zip on the Desktop
out = pathlib.Path(os.path.expanduser("~")) / "Desktop" / f"LightDeck-{version}-Windows.zip"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for p in pkg.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts:
            z.write(p, p.relative_to(pkg.parent))
print(f"done: {out}  ({out.stat().st_size / 1e6:.1f} MB)")
