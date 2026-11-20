"""Measure timing accuracy: where could a movie drift from the music?

Usage: python tools/check_timing.py SONG [MOVIE]

1) Hit accuracy: for each detected hit, find the audible attack (the fastest rise of
   loudness, 1 ms resolution, within +-50 ms) and report how far the hit is from it.
2) With MOVIE: cross-correlate the movie's audio with the original song to find any
   delay added when the audio was re-encoded.
"""
import argparse, subprocess
import numpy as np
from _common import load_beat_movie

ap = argparse.ArgumentParser()
ap.add_argument("song"); ap.add_argument("movie", nargs="?")
a = ap.parse_args()
bm = load_beat_movie()
SR = 22050


def decode(path, sr=SR):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


y = decode(a.song)
pts, dur = bm.find_points(a.song, "onsets", 0.06)
hop = SR // 1000                                         # 1 ms
env = np.sqrt(np.convolve(y ** 2, np.ones(hop * 3) / (hop * 3), "same")[::hop] + 1e-12)
loud = np.log(env)
rise = np.diff(loud, prepend=loud[0])
offs = []
for t, _ in pts:
    c = int(t * 1000)
    lo, hi = max(1, c - 30), min(len(rise) - 1, c + 30)   # +-30 ms: stays clear of the next clack
    attack = lo + int(np.argmax(rise[lo:hi]))
    offs.append(t * 1000 - attack)                       # + means the hit is detected late
offs = np.array(offs)
print(f"hits: {len(offs)}; detected minus audible attack (ms): median {np.median(offs):+.0f}, "
      f"10-90%: {np.percentile(offs, 10):+.0f} .. {np.percentile(offs, 90):+.0f}")

if a.movie:
    m = decode(a.movie)
    n = min(len(y), len(m), SR * 30)
    best = max(range(-2000, 2001, 1), key=lambda k: float(np.dot(y[2000:n - 2000], m[2000 + k:n - 2000 + k])))
    print(f"movie audio vs song: movie is {best / SR * 1000:+.1f} ms {'late' if best > 0 else 'early'}")
