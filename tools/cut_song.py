"""Shorten a song by skipping repeated parts, with jumps that are hard to hear.

Usage:
  python tools/cut_song.py SONG --target 89 [--out cut.mp3] [--jumps 2] [--keep-intro S]
         [--keep-outro S] [--crossfade 0.03] [--plan]

How:
  1. Beats: beat_movie's beat tracker (refined to the exact attack).
  2. Each beat gets a description: harmony (12-note chroma) + sound colour (energy in
     24 frequency bands).
  3. A jump from beat i to beat j (j later) is smooth when the 4 beats before and after i
     sound like the 4 beats before and after j - then the music continues naturally.
     Jumps keep the bar position (j - i is a multiple of 4 beats).
  4. Choose 1..N jumps that bring the length closest to --target with the best smoothness,
     keeping the intro and the ending untouched.
  5. Cut exactly on the beats, with a short crossfade (default 30 ms).
Writes the cut song and prints every jump: from/to times and how similar they are (0-1).
"""
import argparse, itertools, subprocess, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import load_beat_movie

SR = 22050


def decode(path):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def beat_features(y, beats):
    n_fft, hop = 4096, 512
    win = np.hanning(n_fft).astype(np.float32)
    n = 1 + (len(y) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(y[idx] * win, axis=1))              # frames x bins
    freqs = np.fft.rfftfreq(n_fft, 1 / SR)
    # chroma: bins 55 Hz - 5 kHz folded into 12 pitch classes
    ok = (freqs > 55) & (freqs < 5000)
    pc = (np.round(12 * np.log2(freqs[ok] / 440.0)) % 12).astype(int)
    chroma = np.zeros((n, 12))
    for k in range(12):
        chroma[:, k] = mag[:, ok][:, pc == k].sum(axis=1)
    # sound colour: 24 log-spaced bands 60 Hz - 10 kHz, log energy
    edges = np.geomspace(60, 10000, 25)
    bands = np.stack([np.log1p((mag[:, (freqs >= a) & (freqs < b)] ** 2).sum(axis=1))
                      for a, b in zip(edges[:-1], edges[1:])], axis=1)
    frame_t = (np.arange(n) * hop + n_fft / 2) / SR
    feats = []
    for a, b in zip(beats[:-1], beats[1:]):
        m = (frame_t >= a) & (frame_t < b)
        if not m.any():
            m = np.abs(frame_t - a) == np.abs(frame_t - a).min()
        c = chroma[m].mean(axis=0); c /= np.linalg.norm(c) + 1e-9
        feats.append((c, bands[m].mean(axis=0)))
    C = np.array([f[0] for f in feats])
    B = np.array([f[1] for f in feats])
    B = (B - B.mean(axis=0)) / (B.std(axis=0) + 1e-9)
    B /= np.linalg.norm(B, axis=1, keepdims=True) + 1e-9
    return C, B


def smoothness(C, B, i, j, ctx=4):
    """How alike the music is around beat i and beat j (1 = identical), 4 beats each way."""
    s = []
    for k in range(-ctx, ctx):
        a, b = i + k, j + k
        if 0 <= a < len(C) and 0 <= b < len(C):
            s.append(0.6 * float(C[a] @ C[b]) + 0.4 * (float(B[a] @ B[b]) + 1) / 2)
    return float(np.mean(s)) if s else 0.0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("song")
    ap.add_argument("--target", type=float, required=True, help="wanted length in seconds")
    ap.add_argument("--out", help="output file (default: <song name>_cut.mp3 next to this run)")
    ap.add_argument("--jumps", type=int, default=2, help="at most this many skips (default 2)")
    ap.add_argument("--keep-intro", type=float, default=None,
                    help="don't cut in the first N seconds (default: 15, or a quarter of --target if shorter)")
    ap.add_argument("--keep-outro", type=float, default=None,
                    help="don't cut in the last N seconds (default: 20, or a third of --target if shorter)")
    ap.add_argument("--crossfade", type=float, default=0.03, help="blend at each jump, seconds")
    ap.add_argument("--min-between", type=float, default=10,
                    help="at least this many seconds of music between two jumps")
    ap.add_argument("--tolerance", type=float, default=3, help="allowed +- seconds from --target")
    ap.add_argument("--choice", type=int, default=1, help="use the Nth best plan (see --plan)")
    ap.add_argument("--plan", action="store_true", help="only show the best plans, don't write")
    a = ap.parse_args()
    if not Path(a.song).is_file():
        sys.exit(f"Song not found: {a.song}")
    # the untouched intro and ending must leave room to cut: for short targets they shrink
    if a.keep_intro is None:
        a.keep_intro = min(15.0, a.target / 4)
    if a.keep_outro is None:
        a.keep_outro = min(20.0, a.target / 3)

    bm = load_beat_movie()
    y = decode(a.song)
    dur = len(y) / SR
    pts, _ = bm.find_points(Path(a.song), "beats", 0.12)
    beats = np.array([t for t, _ in pts] + [dur])
    C, B = beat_features(y, beats)
    nb = len(C)
    period = float(np.median(np.diff(beats[:-1])))
    print(f"song {dur:.1f}s, {nb} beats (~{60 / period:.0f} BPM), target {a.target:.1f}s, "
          f"remove ~{dur - a.target:.1f}s")

    # all good single jumps i -> j (bar-aligned, inside the allowed zone)
    lo = np.searchsorted(beats, a.keep_intro)
    hi = np.searchsorted(beats, dur - a.keep_outro)
    cands = []
    for i in range(lo, hi):
        for j in range(i + 8, hi, 4):                       # >= 2 bars, keep bar position
            s = smoothness(C, B, i, j)
            if s > 0.80:
                cands.append((s, i, j))
    # keep the best jumps for every skip length (5 s buckets), not just the overall best -
    # those are mostly short repeats, and long skips are needed to shorten a lot
    cands.sort(reverse=True)
    buckets = {}
    for c in cands:
        key = int((beats[c[2]] - beats[c[1]]) // 5)
        if len(buckets.setdefault(key, [])) < 40:
            buckets[key].append(c)
    cands = sorted((c for b in buckets.values() for c in b), reverse=True)
    print(f"  smooth jump candidates: {len(cands)} (best {cands[0][0]:.3f})" if cands else "  no smooth jumps")
    if not cands:
        sys.exit(1)

    plans = []
    for n in range(1, a.jumps + 1):
        for combo in itertools.combinations(cands, n):
            combo = sorted(combo, key=lambda c: c[1])
            # jumps in order, and enough music between landing and the next jump
            if any(beats[combo[k + 1][1]] - beats[combo[k][2]] < a.min_between for k in range(n - 1)):
                continue
            removed = sum(beats[j] - beats[i] for _, i, j in combo)
            length = dur - removed
            err = abs(length - a.target)
            if err > a.tolerance:
                continue
            worst = min(c[0] for c in combo)
            score = worst - 0.01 * err - 0.02 * (n - 1)     # fewer jumps better, close to target
            plans.append((score, combo, length))
    if not plans:
        sys.exit(f"No combination of jumps reaches {a.target:.0f}s. Try: --tolerance 5 (accept a length a bit "
                 f"further off), --jumps {a.jumps + 1} (more skips), or a smaller --keep-intro / --keep-outro "
                 f"(now {a.keep_intro:.0f}s / {a.keep_outro:.0f}s kept untouched)")
    plans.sort(key=lambda p: -p[0])
    # drop near-duplicates (same jumps shifted by a beat or two)
    uniq = []
    for p in plans:
        if all(any(abs(beats[i] - beats[i2]) > 4 or abs(beats[j] - beats[j2]) > 4
                   for (_, i, j), (_, i2, j2) in zip(p[1], q[1])) or len(p[1]) != len(q[1]) for q in uniq):
            uniq.append(p)
        if len(uniq) == 5:
            break
    for r, (score, combo, length) in enumerate(uniq, 1):
        print(f"  plan {r}: {len(combo)} jump(s), result {length:.1f}s, weakest jump {min(c[0] for c in combo):.3f}")
        for s, i, j in combo:
            print(f"    jump {beats[i]:7.2f}s -> {beats[j]:7.2f}s  (skips {beats[j] - beats[i]:5.1f}s, "
                  f"similarity {s:.3f})")
    if a.plan:
        return
    _, combo, length = uniq[a.choice - 1]
    print(f"Using plan {a.choice}")

    # cut on the beats with a short crossfade at each jump
    keep, start = [], 0.0
    for _, i, j in combo:
        keep.append((start, beats[i])); start = beats[j]
    keep.append((start, dur))
    out = Path(a.out or Path(a.song).stem + "_cut.mp3")
    cf = a.crossfade
    chains, labels = [], []
    for k, (s0, s1) in enumerate(keep):
        # each piece runs cf/2 past its cut so the crossfade overlaps both sides evenly
        s0p = max(0.0, s0 - (cf / 2 if k else 0)); s1p = min(dur, s1 + (cf / 2 if k < len(keep) - 1 else 0))
        chains.append(f"[0:a]atrim={s0p:.4f}:{s1p:.4f},asetpts=PTS-STARTPTS[p{k}]")
        labels.append(f"p{k}")
    cur = labels[0]
    for k in range(1, len(labels)):
        nxt = f"x{k}"
        chains.append(f"[{cur}][{labels[k]}]acrossfade=d={cf:.4f}:c1=tri:c2=tri[{nxt}]")
        cur = nxt
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(a.song), "-filter_complex",
                    ";".join(chains), "-map", f"[{cur}]", "-c:a", "libmp3lame", "-q:a", "2", str(out)],
                   check=True)
    got = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout)
    print(f"Done: {out}  ({got:.1f}s)")


if __name__ == "__main__":
    main()
