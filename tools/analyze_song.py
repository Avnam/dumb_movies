import sys, importlib.util
spec = importlib.util.spec_from_file_location("bm", sys.argv[1])
bm = importlib.util.module_from_spec(spec); spec.loader.exec_module(bm)
pts, dur = bm.find_points(sys.argv[2], "onsets", 0.12)
print(f"duration {dur:.1f}s, hits {len(pts)}")
# hits per 5-second window
for s in range(0, int(dur), 5):
    w = [p for p in pts if s <= p[0] < s + 5]
    bar = "#" * len(w)
    print(f"{s:4d}-{s+5:<4d} {len(w):3d} {bar}")
# when do the first 98 hits end, from various starts
for st in (0, 5, 10, 20, 30):
    after = [t for t, _ in pts if t >= st]
    if len(after) >= 99:
        print(f"start {st}s: 98 consecutive hits end at {after[98]:.1f}s ({after[98]-st:.1f}s long)")
