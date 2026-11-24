"""Streams a test pattern to the N80 (re-sent every 0.3 s); the pattern is chosen by n80_mode.txt."""
import os, sys, time
sys.path[:0] = [sys.argv[1], os.path.join(sys.argv[1], "drivers")]   # argv[1] = the lightdeck folder
import winhid
from rk_n80 import SLOTS, ROWS, find_path, frame_bytes
mode_file = os.path.join(os.environ["TEMP"], "n80_mode.txt")
PAL = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255), (255, 255, 255)]
def frame(mode):
    out = []
    for i in range(SLOTS):
        c, r = i // ROWS, i % ROWS
        if mode == "groups":
            out.append(PAL[c // 3])
        elif mode == "rows":
            out.append(PAL[r])
        elif mode.startswith("cols:"):
            cols = [int(x) for x in mode[5:].split(",")]
            out.append(PAL[cols.index(c)] if c in cols else (0, 0, 0))
        elif mode.startswith("slot:"):
            out.append((255, 255, 255) if i == int(mode[5:]) else (0, 0, 20))
        else:
            out.append((0, 0, 0))
    return out
kb = winhid.open_path(find_path()); t0 = time.time()
try:
    while time.time() - t0 < 900:
        mode = open(mode_file).read().strip() if os.path.exists(mode_file) else "groups"
        if mode == "stop": break
        winhid.set_feature(kb, frame_bytes(frame(mode))); time.sleep(0.25)
finally:
    winhid.close(kb)
