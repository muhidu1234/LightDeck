"""Compare the N80 lighting commands step by step: which bytes change between messages."""
import sys

rows = []
for line in open(sys.argv[1]):
    parts = line.split()
    t = float(parts[0])
    data = bytes.fromhex(parts[-1])
    rows.append((t, data))

by_cmd = {}
for t, d in rows:
    by_cmd.setdefault(d[1], []).append((t, d))

for cmd, items in sorted(by_cmd.items()):
    print(f"\n===== command 0x{cmd:02x}: {len(items)} messages, header {items[0][1][:8].hex()} =====")
    first = items[0][1]
    last_nz = max((i for i, b in enumerate(first) if b), default=0)
    print(f"first message non-zero bytes up to offset {last_nz}:")
    print("   ", first[:min(len(first), last_nz + 1)].hex(" "))
    prev = first
    for t, d in items[1:]:
        diffs = [i for i in range(len(d)) if d[i] != prev[i]]
        if diffs:
            shown = ", ".join(f"[{i}] {prev[i]:02x}->{d[i]:02x}" for i in diffs[:24])
            print(f"  t={t:8.3f}: {len(diffs)} bytes changed: {shown}{' ...' if len(diffs) > 24 else ''}")
        prev = d
