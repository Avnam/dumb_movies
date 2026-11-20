"""Check a movie made with --section runs.

Usage: python tools/verify_runs.py SONG MOVIE SORTED_FOLDER [--seed 1] [--video-target 3.5]

Re-plans with the same settings, then measures the movie frame by frame:
  1) picture changes: does the picture change at every planned segment start?
  2) zooms: inside push/pull/pulse segments, does the picture move right after each
     planned hit (and stay still between hits)?
"""
import argparse, subprocess
import numpy as np
from _common import load_beat_movie, load_items

ap = argparse.ArgumentParser()
ap.add_argument("song"); ap.add_argument("movie"); ap.add_argument("folder")
ap.add_argument("--seed", type=int, default=1)
ap.add_argument("--video-target", type=float, default=3.5)
a = ap.parse_args()

bm = load_beat_movie()
pts, dur = bm.find_points(a.song, "onsets", 0.06)
runs = bm.find_runs(pts, 0.35, 0.3, 3, bm.hit_levels(a.song, [t for t, _ in pts]))
segs, d = bm.plan_runs(load_items(a.folder, bm), pts, runs, dur, a.seed, a.video_target)

# decode the movie small and grey: one number array per frame
w, h = 192, 108
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", a.movie, "-vf", f"scale={w}:{h},format=gray",
                      "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
frames = np.frombuffer(raw, np.uint8).reshape(-1, h, w).astype(np.int16)
diff = np.concatenate([[0], np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2))])
fps = bm.FPS

# 1) picture changes: the biggest change near each planned start should be on it (or 1 frame
#    after). Consecutive pictures can be nearly identical, so no fixed threshold is used.
starts = [round(s[1] * fps) for s in segs[1:] if 2 <= round(s[1] * fps) < len(diff) - 2]
on_time = sum(int(np.argmax(diff[f - 2:f + 3])) - 2 in (0, 1) for f in starts)
similar = sum(diff[f - 1:f + 2].max() < 1 for f in starts)
print(f"picture changes: {len(starts)} planned, {on_time} happen on the planned frame (+1); "
      f"{similar} are between near-identical pictures")

# 2) zoom reacts to hits
on, off, n_hits = [], [], 0
for it, s, e, kind, clacks in segs:
    if kind not in ("push", "pull", "pulse"):
        continue
    f0, f1 = round(s * fps), round(e * fps)
    tick_frames = {round(c * fps) for c in clacks if f0 < round(c * fps) < f1}   # zoom jumps here
    for f in tick_frames:
        n_hits += 1
        on.append(diff[f])                                 # the jump frame itself
    off += [diff[f] for f in range(f0 + 1, f1) if f not in tick_frames]
print(f"zoom segments: {sum(1 for x in segs if x[3] in ('push', 'pull', 'pulse'))}, ticks checked {n_hits}")
print(f"  change on the tick frame:   median {np.median(on):.2f}, "
      f"{np.mean(np.array(on) > 1.0) * 100:.0f}% of ticks jump exactly on their frame")
print(f"  change between ticks:       median {np.median(off) if off else 0:.2f} (0 = still, no gliding)")
