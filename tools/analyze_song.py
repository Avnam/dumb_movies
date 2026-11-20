"""Show how the hits are spread through a song.

Usage: python tools/analyze_song.py SONG [--slots N] [--min-gap 0.12]

Prints hits per 5 seconds, and with --slots N (number of pictures, videos count
as 2) how long N consecutive hits last from a few starting points.
"""
import argparse
from _common import load_beat_movie

ap = argparse.ArgumentParser()
ap.add_argument("song")
ap.add_argument("--slots", type=int, help="how many cuts are needed")
ap.add_argument("--min-gap", type=float, default=0.12)
a = ap.parse_args()

bm = load_beat_movie()
pts, dur = bm.find_points(a.song, "onsets", a.min_gap)
print(f"duration {dur:.1f}s, hits {len(pts)}")
for s in range(0, int(dur) + 1, 5):
    n = sum(1 for t, _ in pts if s <= t < s + 5)
    print(f"{s:4d}-{s + 5:<4d} {n:3d} {'#' * n}")
if a.slots:
    for st in (0, 5, 10, 20, 30):
        after = [t for t, _ in pts if t >= st]
        if len(after) > a.slots:
            end = after[a.slots]
            print(f"start {st}s: {a.slots} consecutive hits end at {end:.1f}s ({end - st:.1f}s long)")
