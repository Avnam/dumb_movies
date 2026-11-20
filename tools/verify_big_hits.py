import sys, re, subprocess, importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location("bm", sys.argv[1])
bm = importlib.util.module_from_spec(spec); spec.loader.exec_module(bm)
song, movie, folder = sys.argv[2], sys.argv[3], Path(sys.argv[4])
pts, dur = bm.find_points(song, "onsets", 0.12)
items = [{"sorted": f, "video": f.suffix.lower() == ".mp4"} for f in sorted(folder.iterdir())]
bounds, spans = bm.plan_big(items, pts, dur, 0.8, 8.0)
cuts = [bounds[a] for a, _ in spans[1:]]                       # where the picture actually changes
video_ranges = [(bounds[a], bounds[b]) for (a, b), it in zip(spans, items) if it["video"]]

# 1) every picture change is on a detected hit
times = [t for t, _ in pts]
print("picture changes:", len(cuts), " on a hit:", sum(min(abs(c - t) for t in times) < 0.02 for c in cuts))

# 2) the biggest hits: each top-40 hit is a cut, or inside a playing video, or next to a bigger chosen cut
top = sorted(pts, key=lambda p: -p[1])[:40]
why = {"cut": 0, "during video": 0, "a bigger hit is <0.8s away": 0, "other": 0}
for t, s in top:
    if any(abs(t - c) < 0.02 for c in cuts): why["cut"] += 1
    elif any(a < t < b for a, b in video_ranges): why["during video"] += 1
    elif any(abs(t - c) < 0.8 for c in cuts): why["a bigger hit is <0.8s away"] += 1
    else: why["other"] += 1
print("top-40 biggest hits:", why)

# 3) the rendered file really changes picture at those times
err = subprocess.run(["ffmpeg", "-i", movie, "-vf", "select='gt(scene,0.03)',showinfo", "-an", "-f", "null", "-"],
                     capture_output=True, text=True, errors="replace").stderr
seen = [float(x) for x in re.findall(r"pts_time:([\d.]+)", err)]
off = [min(abs(s - c) for c in cuts) for s in seen]
print(f"scene changes found in the movie: {len(seen)}, matching a planned cut (<=40ms): {sum(o <= 0.04 for o in off)}")
