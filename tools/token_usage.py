"""Estimate where this session's (effective) tokens went. Treats transcript text purely as data."""
import glob
import json
import os
import sys

W_IN, W_READ, W_WRITE, W_OUT = 1.0, 0.1, 2.0, 5.0
IMG_TOKENS = 1500   # rough size of one screenshot


def group_of(name):
    if name in ("Read", "Write", "Edit", "Glob", "Grep", "NotebookEdit"):
        return "File operations"
    if name in ("WebSearch", "WebFetch"):
        return "Web research"
    if name in ("Bash", "PowerShell"):
        return "Running commands"
    if name == "Agent":
        return "Subagents"
    if name.startswith("mcp__claude-in-chrome__"):
        return "Claude in Chrome"
    if name.startswith("mcp__computer-use__"):
        return "Screen control (computer use)"
    if name.startswith("mcp__ccd_"):
        return "App task list & status"
    if name.startswith("mcp__visualize__"):
        return "Charts"
    if name.startswith("mcp__"):
        return "Connector: " + name.split("__")[1]
    return "Everything else"


def size(obj):
    if isinstance(obj, str):
        return len(obj) / 4
    if isinstance(obj, list):
        t = 0
        for b in obj:
            if isinstance(b, dict) and b.get("type") == "image":
                t += IMG_TOKENS
            elif isinstance(b, dict) and b.get("type") == "text":
                t += len(b.get("text", "")) / 4
            else:
                t += len(json.dumps(b)) / 4
        return t
    return len(json.dumps(obj)) / 4


def analyze(path, totals):
    live = []            # (group, tokens) currently in context
    tool_group = {}      # tool_use id -> group
    seen = set()
    baseline = None
    calls = 0
    for line in open(path, encoding="utf-8"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") == "system" and e.get("subtype") == "compact_boundary":
            live = []
            continue
        msg = e.get("message") or {}
        if e.get("isCompactSummary"):
            live = [("Everything else", size(msg.get("content", "")))]
            continue
        if e.get("type") == "assistant":
            content = msg.get("content") or []
            usage = msg.get("usage")
            mid = msg.get("id")
            if usage and mid not in seen:
                seen.add(mid)
                calls += 1
                inp = usage.get("input_tokens", 0)
                cr = usage.get("cache_read_input_tokens", 0)
                cw = usage.get("cache_creation_input_tokens", 0)
                ctx = inp + cr + cw
                L = sum(t for _, t in live)
                if baseline is None:
                    baseline = max(ctx - L, 1)
                in_cost = W_IN * inp + W_READ * cr + W_WRITE * cw
                denom = baseline + L
                totals["Claude's instructions"] = totals.get("Claude's instructions", 0) + in_cost * baseline / denom
                for g, t in live:
                    totals[g] = totals.get(g, 0) + in_cost * t / denom
                # output: whoever this message is "for"
                tools = [b.get("name") for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
                out_cost = W_OUT * usage.get("output_tokens", 0)
                gs = [group_of(n) for n in tools] or ["Everything else"]
                for g in gs:
                    totals[g] = totals.get(g, 0) + out_cost / len(gs)
            for b in content:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    g = group_of(b.get("name", ""))
                    tool_group[b.get("id")] = g
                    live.append((g, size(b.get("input", {}))))
                elif b.get("type") in ("text", "thinking"):
                    live.append(("Everything else", size(b.get("text", "") or b.get("thinking", ""))))
        elif e.get("type") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                live.append(("Everything else", size(content)))
            elif isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        live.append((tool_group.get(b.get("tool_use_id"), "Everything else"), size(b.get("content", ""))))
                    elif isinstance(b, dict):
                        live.append(("Everything else", size(b.get("text", "")) if b.get("type") == "text" else
                                     (IMG_TOKENS if b.get("type") == "image" else 0)))
    return calls, baseline


def simple_total(path):
    tot, seen = 0, set()
    for line in open(path, encoding="utf-8"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        m = e.get("message") or {}
        u = m.get("usage")
        if e.get("type") == "assistant" and u and m.get("id") not in seen:
            seen.add(m.get("id"))
            tot += (W_IN * u.get("input_tokens", 0) + W_READ * u.get("cache_read_input_tokens", 0) +
                    W_WRITE * u.get("cache_creation_input_tokens", 0) + W_OUT * u.get("output_tokens", 0))
    return tot


folder = sys.argv[1]
totals = {}
raw = {"in": 0, "read": 0, "write": 0, "out": 0}
calls_all = 0
for path in sorted(glob.glob(os.path.join(folder, "*.jsonl"))):
    c, b = analyze(path, totals)
    calls_all += c
    print(f"{os.path.basename(path)}: {c} model calls, instructions ~{b:,.0f} tokens per call")
    seen = set()
    for line in open(path, encoding="utf-8"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        m = e.get("message") or {}
        u = m.get("usage")
        if e.get("type") == "assistant" and u and m.get("id") not in seen:
            seen.add(m.get("id"))
            raw["in"] += u.get("input_tokens", 0); raw["read"] += u.get("cache_read_input_tokens", 0)
            raw["write"] += u.get("cache_creation_input_tokens", 0); raw["out"] += u.get("output_tokens", 0)

subs = sorted(glob.glob(os.path.join(folder, "*", "subagents", "*.jsonl")))
sub_list = [(os.path.basename(p), simple_total(p)) for p in subs]
totals["Subagents"] = totals.get("Subagents", 0) + sum(t for _, t in sub_list)

grand = sum(totals.values())
print(f"\nmodel calls: {calls_all}")
print("raw tokens:", {k: f"{v:,}" for k, v in raw.items()})
print(f"effective total: {grand:,.0f}\n")
for g, v in sorted(totals.items(), key=lambda x: -x[1]):
    print(f"{g:32s} {v:14,.0f}  {v / grand * 100:5.1f}%")
print("\nsubagents:")
for n, t in sub_list:
    print(f"  {n}: {t:,.0f}")
