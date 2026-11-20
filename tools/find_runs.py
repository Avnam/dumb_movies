"""Find "runs" in a song: 3+ hits in a row with nearly the same short spacing
(e.g. a burst of typewriter clacks), and whether each run gets louder or softer.

Usage: python tools/find_runs.py SONG [--max-step 0.35] [--tolerance 0.3] [--min-len 3]
"""
import argparse
from _common import load_beat_movie

ap = argparse.ArgumentParser()
ap.add_argument("song")
ap.add_argument("--max-step", type=float, default=0.35)
ap.add_argument("--tolerance", type=float, default=0.3)
ap.add_argument("--min-len", type=int, default=3)
a = ap.parse_args()

bm = load_beat_movie()
pts, dur = bm.find_points(a.song, "onsets", 0.06)
levels = bm.hit_levels(a.song, [t for t, _ in pts])          # loudness, as --section runs uses
runs = bm.find_runs(pts, a.max_step, a.tolerance, a.min_len, levels)
print(f"duration {dur:.1f}s, hits {len(pts)}, runs {len(runs)}, "
      f"hits inside runs {sum(len(r['hits']) for r in runs)}")
for r in runs:
    t0, t1 = r["hits"][0][0], r["hits"][-1][0]
    loud = " ".join(f"{levels[i]:.3f}" for i in r["idx"])
    print(f"{t0:6.2f}-{t1:6.2f}s  {len(r['hits']):2d} hits every {r['step']*1000:3.0f}ms  {r['trend']:8s}  [{loud}]")
