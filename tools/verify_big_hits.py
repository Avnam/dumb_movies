"""Check a movie made with --section big.

Usage: python tools/verify_big_hits.py SONG MOVIE SORTED_FOLDER [--gap 0.8] [--video-max 8] [--top 40]

Use the same --gap / --video-max as the render. Reports:
  1) whether every planned picture change is on a hit,
  2) what happened to the song's biggest hits,
  3) whether the rendered file really changes picture at the planned times.
"""
import argparse, re, subprocess
from _common import load_beat_movie, load_items

ap = argparse.ArgumentParser()
ap.add_argument("song"); ap.add_argument("movie"); ap.add_argument("folder")
ap.add_argument("--gap", type=float, default=0.8)
ap.add_argument("--video-max", type=float, default=8.0)
ap.add_argument("--top", type=int, default=40)
a = ap.parse_args()

bm = load_beat_movie()
pts, dur = bm.find_points(a.song, "onsets", 0.12)
items = load_items(a.folder, bm)
bounds, spans = bm.plan_big(items, pts, dur, a.gap, a.video_max)
cuts = [bounds[s] for s, _ in spans[1:]]
video_ranges = [(bounds[s], bounds[e]) for (s, e), it in zip(spans, items) if it["video"]]

times = [t for t, _ in pts]
print("picture changes:", len(cuts), " on a hit:", sum(min(abs(c - t) for t in times) < 0.02 for c in cuts))

why = {"cut": 0, "during video": 0, f"a bigger hit is <{a.gap}s away": 0, "other": 0}
for t, _ in sorted(pts, key=lambda p: -p[1])[:a.top]:
    if any(abs(t - c) < 0.02 for c in cuts): why["cut"] += 1
    elif any(s < t < e for s, e in video_ranges): why["during video"] += 1
    elif any(abs(t - c) < a.gap for c in cuts): why[f"a bigger hit is <{a.gap}s away"] += 1
    else: why["other"] += 1
print(f"top-{a.top} biggest hits:", why)

err = subprocess.run(["ffmpeg", "-i", a.movie, "-vf", "select='gt(scene,0.03)',showinfo", "-an", "-f", "null", "-"],
                     capture_output=True, text=True, errors="replace").stderr
seen = [float(x) for x in re.findall(r"pts_time:([\d.]+)", err)]
ok = sum(min(abs(s - c) for c in cuts) <= 0.04 for s in seen) if cuts else 0
print(f"scene changes found in the movie: {len(seen)}, matching a planned cut (<=40ms): {ok}")
