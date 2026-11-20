"""
beat_movie.py - turn a pile of photos/videos into a movie cut to the music.

Steps:
  1. Collect every photo/video under INPUT (zip files are extracted too).
  2. Work out when each one was taken (Google Photos .json sidecar -> EXIF ->
     video metadata -> date in the filename -> file time) and copy them into
     OUTPUT/sorted/ named by date, so they're all in one place, in order.
  3. Find the "points" in the song (onsets = every hit/click, like a typewriter;
     or beats = the steady pulse).
  4. Put one photo per point (videos get a short clip over 2 points), in date
     order, and render OUTPUT/movie.mp4 with the song.

Usage:
  python beat_movie.py INPUT_FOLDER SONG_FILE OUTPUT_FOLDER [options]

Options:
  --mode onsets|beats   which points to cut on (default: onsets)
  --min-gap 0.12        shortest time a picture is shown, in seconds
  --video-beats 2       how many points each video clip lasts
  --sort-only           only collect + sort, don't make the movie
"""
import argparse, json, os, re, shutil, subprocess, sys, zipfile, tempfile
from datetime import datetime, timezone
from pathlib import Path

PHOTO_EXT = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp"}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".3gp", ".avi", ".mkv"}
W, H, FPS = 1920, 1080, 30


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(map(str, cmd))}\n{r.stderr[-2000:]}")
    return r.stdout


# ---------------------------------------------------------------- dates
def date_from_sidecar(p: Path):
    # Google Takeout: IMG_1.jpg.json or IMG_1.jpg.supplemental-metadata.json etc.
    for cand in p.parent.glob(p.name[:40] + "*.json"):
        try:
            d = json.loads(cand.read_text(encoding="utf-8"))
            ts = d.get("photoTakenTime", {}).get("timestamp")
            if ts:
                return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone().replace(tzinfo=None)
        except Exception:
            pass
    return None


def date_from_exif(p: Path):
    try:
        from PIL import Image
        with Image.open(p) as im:
            ex = im.getexif()
            val = ex.get_ifd(0x8769).get(36867) or ex.get(306)  # DateTimeOriginal / DateTime
            if val:
                return datetime.strptime(str(val).strip()[:19], "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def date_from_video(p: Path):
    try:
        out = run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(p)])
        tags = json.loads(out).get("format", {}).get("tags", {})
        ct = tags.get("creation_time") or tags.get("com.apple.quicktime.creationdate")
        if ct:
            dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
            if dt.year > 2000:
                return dt.astimezone().replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        pass
    return None


def date_from_name(p: Path):
    m = re.search(r"(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})[ _T-]?(\d{2})?[-_.:]?(\d{2})?[-_.:]?(\d{2})?", p.stem)
    if m:
        try:
            parts = [int(x) if x else 0 for x in m.groups()]
            return datetime(*parts)
        except ValueError:
            pass
    return None


def taken_date(p: Path, is_video: bool):
    m = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?!\d)", p.stem)
    if m:  # a full timestamp in the name (cameras, screenshot apps) is the most exact
        try:
            return datetime(*map(int, m.groups()))
        except ValueError:
            pass
    d = date_from_sidecar(p)
    if not d:
        d = date_from_video(p) if is_video else date_from_exif(p)
    if not d:
        d = date_from_name(p)
    if not d:
        d = datetime.fromtimestamp(p.stat().st_mtime)
    return d


# ---------------------------------------------------------------- collect
def collect(inp: Path, out: Path, name_re=None):
    work = out / "_unzipped"
    zips = [inp] if inp.is_file() and inp.suffix.lower() == ".zip" else list(inp.rglob("*.zip"))
    if inp.is_file():
        inp = inp.parent / "__no_loose_files__"
    for z in zips:
        dest = work / z.stem
        print(f"Reading {z.name}...")
        with zipfile.ZipFile(z) as zf:
            n = 0
            for m in zf.infolist():
                base = m.filename.rsplit("/", 1)[-1]
                media = base.split(".json")[0] if base.endswith(".json") else base
                if name_re and not re.search(name_re, media, re.I):
                    continue
                if not (dest / m.filename).exists():
                    zf.extract(m, dest)
                n += 1
            print(f"  extracted {n} matching files")
    items, seen = [], set()
    for root in [inp, work]:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            ext = p.suffix.lower()
            if not p.is_file() or ext not in PHOTO_EXT | VIDEO_EXT:
                continue
            if name_re and not re.search(name_re, p.name, re.I):
                continue
            if out in p.parents and work not in p.parents:
                continue  # skip our own output
            key = (p.name.lower(), p.stat().st_size)
            if key in seen:
                continue  # duplicate
            seen.add(key)
            is_video = ext in VIDEO_EXT
            items.append({"path": p, "video": is_video, "date": taken_date(p, is_video)})
    items.sort(key=lambda x: x["date"])

    sorted_dir = out / "sorted"
    sorted_dir.mkdir(parents=True, exist_ok=True)
    for i, it in enumerate(items, 1):
        orig = re.sub(r"^\d{4}_\d{4}-\d{2}-\d{2}_\d{6}_", "", it["path"].name)  # from an earlier sort
        name = f"{i:04d}_{it['date']:%Y-%m-%d_%H%M%S}_{orig}"
        dest = sorted_dir / name
        if not dest.exists():
            shutil.copy2(it["path"], dest)
        it["sorted"] = dest
    print(f"Collected {len(items)} files ({sum(i['video'] for i in items)} videos) -> {sorted_dir}")
    if items:
        print(f"  from {items[0]['date']:%Y-%m-%d} to {items[-1]['date']:%Y-%m-%d}")
    return items


# ---------------------------------------------------------------- music
def refine_attacks(y, sr, times, reach=0.025):
    """Move each hit to the exact moment its sound starts: the steepest rise of the
    loudness (1 ms steps) within +-25 ms, never past halfway to a neighbouring hit.
    The coarse detector alone is off by up to ~40 ms, enough to feel off-rhythm."""
    import numpy as np
    step = max(1, sr // 1000)
    win = step * 3
    env = np.sqrt(np.convolve(y ** 2, np.ones(win) / win, "same")[::step] + 1e-12)
    rise = np.diff(np.log(env), prepend=np.log(env[0]))
    times = np.asarray(times, float)
    out = times.copy()
    for k, t in enumerate(times):
        lo_t = max(t - reach, (times[k - 1] + t) / 2 if k else 0.0)
        hi_t = min(t + reach, (times[k + 1] + t) / 2 if k + 1 < len(times) else t + reach)
        lo, hi = int(lo_t * 1000), int(hi_t * 1000)
        if hi - lo > 2 and hi < len(rise):
            out[k] = (lo + int(np.argmax(rise[lo:hi]))) / 1000
    return out


def find_points(song: Path, mode: str, min_gap: float):
    import numpy as np
    sr, hop, nfft = 22050, 256, 1024
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(song), "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype=np.float32)
    dur = len(y) / sr
    y_orig = y
    y = np.concatenate([np.zeros(nfft // 2, np.float32), y])  # frame i is centred on i*hop
    # spectral flux: how much "new" sound appears in each ~23ms frame
    win = np.hanning(nfft).astype(np.float32)
    n = 1 + max(0, len(y) - nfft) // hop
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    mag = np.log1p(10 * np.abs(np.fft.rfft(y[idx] * win, axis=1)))
    env = np.concatenate([[0], np.maximum(mag[1:] - mag[:-1], 0).sum(axis=1)])
    env = env / (env.max() or 1)
    fps_env = sr / hop
    # peaks: local maximum and clearly above the surrounding average
    pre, post, avg = 6, 6, 24
    peaks = []
    for i in range(len(env)):
        lo, hi = max(0, i - pre), min(len(env), i + post + 1)
        if env[i] == env[lo:hi].max() and env[i] > env[max(0, i - avg):i + avg + 1].mean() + 0.07:
            peaks.append(i)
    peaks = np.array(peaks, dtype=int)
    if mode == "beats":
        # tempo from autocorrelation (70-180 BPM), then the best-aligned beat grid
        e = env - env.mean()
        ac = np.correlate(e, e, "full")[len(e) - 1:]
        lags = np.arange(int(fps_env * 60 / 180), int(fps_env * 60 / 70))
        period = lags[np.argmax(ac[lags])]
        phase = max(range(period), key=lambda p: env[p::period].sum())
        grid = np.arange(phase, len(env), period)
        # snap each grid beat to a real hit within ~50ms
        frames = []
        for g in grid:
            near = peaks[np.abs(peaks - g) <= 4] if len(peaks) else []
            frames.append(int(near[np.argmax(env[near])]) if len(near) else int(g))
        frames = np.array(frames)
        print(f"  tempo ~{60 * fps_env / period:.0f} BPM")
    else:
        frames = peaks
    times = frames * hop / sr
    strength = env[frames]
    times = refine_attacks(y_orig, sr, times)
    # enforce minimum gap, keeping the stronger hit
    keep = []
    for t, s in sorted(zip(times, strength)):
        if keep and t - keep[-1][0] < min_gap:
            if s > keep[-1][1]:
                keep[-1] = (t, s)
        else:
            keep.append((t, s))
    return [(float(t), float(s)) for t, s in keep], dur


def hit_levels(song: Path, times, window=0.08):
    """Loudness (RMS) just after each hit - used to tell if a run gets louder or softer."""
    import numpy as np
    sr = 22050
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(song), "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype=np.float32)
    n = int(window * sr)
    return [float(np.sqrt(np.mean(y[int(t * sr):int(t * sr) + n] ** 2) + 1e-12)) for t in times]


def find_runs(points, max_step=0.35, tolerance=0.3, min_len=3, levels=None):
    """Runs = min_len+ hits in a row, each at most max_step apart, with nearly the same
    spacing (within `tolerance`). Each run gets a trend from the loudness of its hits:
    'louder', 'softer' or 'steady'."""
    import numpy as np
    lv = levels if levels is not None else [s for _, s in points]
    runs, cur = [], [0]

    def close(run_idx):
        if len(run_idx) >= min_len:
            hits = [points[i] for i in run_idx]
            v = np.array([lv[i] for i in run_idx])
            body = v[:-1] if len(v) >= 5 else v            # one loud/soft accent at the end isn't a trend
            h = len(body) // 2
            ratio = body[-h:].mean() / (body[:h].mean() or 1) if h else 1.0
            rising = np.mean(np.diff(body) > 0) if len(body) > 1 else 0.5
            if ratio > 1.2 and rising >= 0.6:
                trend = "louder"
            elif ratio < 1 / 1.2 and rising <= 0.4:
                trend = "softer"
            else:
                trend = "steady"
            step = float(np.median(np.diff([t for t, _ in hits])))
            runs.append({"hits": hits, "idx": list(run_idx), "trend": trend, "step": step,
                         "levels": [float(x) for x in v]})

    for i in range(1, len(points)):
        d = points[i][0] - points[i - 1][0]
        if d <= max_step and (len(cur) < 2 or
                              abs(d - (points[cur[-1]][0] - points[cur[-2]][0])) <= tolerance * d):
            cur.append(i)
        else:
            close(cur)
            cur = [i - 1, i] if d <= max_step else [i]
    close(cur)
    return runs


def fit_points(points, n_slots):
    """Choose exactly n_slots+1 boundaries. If the song has more hits than we
    need, keep the strongest ones; if fewer, use them all (some photos left out)."""
    if len(points) <= n_slots + 1:
        return [t for t, _ in points]
    first, rest = points[0], points[1:]
    best = sorted(rest, key=lambda x: -x[1])[:n_slots]
    return sorted([first[0]] + [t for t, _ in best])


# ---------------------------------------------------------------- render
VF = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
      f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS},format=yuv420p")


def prep_photo(src: Path, tmp: Path):
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    dst = tmp / (src.stem + "_n.jpg")
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((W * 2, H * 2))
        im.save(dst, quality=92)
    return dst


def video_len(p: Path):
    try:
        return float(run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(p)]).strip())
    except Exception:
        return 0.0


def pick_big_hits(points, n, gap, song_dur):
    """The n strongest hits, biggest first, never two closer than `gap` seconds."""
    chosen = []
    for t, s in sorted(points, key=lambda p: -p[1]):
        if t < gap or t > song_dur - gap:
            continue
        if all(abs(t - c) >= gap for c in chosen):
            chosen.append(t)
            if len(chosen) == n:
                break
    return sorted(chosen)


def plan_big(items, points, song_dur, gap, video_max):
    """Cut only on big hits across the whole song. Photos get one interval,
    videos get as many intervals as needed to play up to `video_max` seconds."""
    want = [None if not it["video"] else min(video_len(it["sorted"]), video_max) for it in items]
    def assign(bounds):
        spans, k = [], 0
        for i, w in enumerate(want):
            max_end = len(bounds) - 1 - (len(items) - i - 1)   # keep one interval per remaining item
            end = k + 1
            if w is not None:
                while end < max_end and bounds[end] - bounds[k] < w * 0.85:
                    end += 1
            end = min(end, max_end)
            spans.append((k, end))
            k = end
        return spans, k

    # start from an estimate, then adjust until the pictures exactly fill the song
    avg = song_dur / len(items)
    n_cuts = len(items) - 1 + sum(max(0, round(w / avg) - 1) for w in want if w)
    best = None
    for _ in range(40):
        cuts = pick_big_hits(points, n_cuts, gap, song_dur)
        bounds = [0.0] + cuts + [song_dur]
        spans, used = assign(bounds)
        leftover = (len(bounds) - 1) - used
        short = sum(1 for (a, b), w in zip(spans, want)
                    if w and bounds[b] - bounds[a] < w * 0.85 and b - a == 1)
        best = (bounds, spans)
        if leftover == 0 and short == 0:
            break
        step = (1 if short else 0) - leftover
        if step == 0 or len(cuts) < n_cuts and step > 0:
            break
        n_cuts += step
    bounds, spans = best
    spans[-1] = (spans[-1][0], len(bounds) - 1)              # last picture holds to the final note
    return bounds, spans


# ---------------------------------------------------------------- "runs" mode
# Bursts of fast, evenly spaced hits ("runs") each get a style, varied through the song:
#   flurry - a new picture on every hit            (runs that get louder)
#   pull   - one picture that steps out on each hit (runs that get softer)
#   push   - one picture that steps in on each hit  (steady runs, some of them)
#   pulse  - one picture, a zoom pulse on every other hit (steady runs, some of them)
#   words  - a new picture every few hits, pushing in within each  (steady runs, some)
# Between runs the picture changes on big hits. A "density" knob is searched so the
# files exactly fill the song. The variety is seeded, so the same settings give the same movie.

def _rng(seed, i, salt):
    import random
    return random.Random(f"{seed}-{i}-{salt}").random()


def _run_style(run, i, d, seed):
    n = len(run["hits"])
    if run["trend"] == "louder":
        return "flurry"
    if run["trend"] == "softer":
        return "pull"
    if n >= 8 and _rng(seed, i, "words") < d:
        return "words"
    return "push" if _rng(seed, i, "push") < 0.5 else "pulse"


def _strong_phase(levels, every):
    """Which of the `every` possible offsets lands on the stronger hits (louder on average)."""
    if every <= 1 or not levels:
        return 0
    return max(range(every), key=lambda p: sum(levels[p::every]) / max(1, len(levels[p::every])))


def _zoom_ticks(ts, levels, step):
    """The hits a zoom reacts to: every hit if they are >=150 ms apart, else every 2nd
    hit, on the stronger of each pair."""
    every = 1 if step >= 0.15 else 2
    p = _strong_phase(levels, every)
    return ts[p::every]


def _build_slots(points, runs, song_dur, d, seed):
    """Timeline of slots (start, end, kind, clacks) for density d in 0..1."""
    gap = 2.5 - 2.0 * d                                    # between runs: 2.5 s .. 0.5 s
    word = max(4, round(12 - 6 * d))                       # words: 12 .. 6 hits per picture
    every = 1 if d > 0.66 else 2 if d > 0.33 else 3        # flurry: new picture every 1..3 hits
    blocks = []
    for i, r in enumerate(runs):
        if len(r["hits"]) < 5 and r["trend"] != "louder":
            continue                                       # short bursts: treat as ordinary hits
        ts = [t for t, _ in r["hits"]]
        blocks.append((ts[0], ts[-1] + r["step"], _run_style(r, i, d, seed), ts,
                       r.get("levels", []), r["step"]))
    slots, cursor = [], 0.0
    zones = []
    for b in blocks:
        zones.append((cursor, b[0])); cursor = b[1]
    zones.append((cursor, song_dur))
    in_run = lambda t: any(b[0] - 0.05 <= t <= b[1] for b in blocks)
    free = [(t, s) for t, s in points if not in_run(t)]

    def zone_slots(z0, z1):
        if z1 - z0 < 0.05:
            return []
        cand = sorted([p for p in free if z0 + gap <= p[0] <= z1 - gap], key=lambda p: -p[1])
        cuts = []
        for t, _ in cand:
            if all(abs(t - c) >= gap for c in cuts):
                cuts.append(t)
        b = [z0] + sorted(cuts) + [z1]
        return [(b[k], b[k + 1], "plain", []) for k in range(len(b) - 1)]

    for (z0, z1), blk in zip(zones, blocks + [None]):
        slots += zone_slots(z0, z1)
        if blk is None:
            continue
        b0, b1, style, ts, lv, step = blk
        if style == "flurry":
            # a new picture on every `every`-th hit, starting on the stronger hits
            p = _strong_phase(lv, every)
            marks = sorted(set([ts[0]] + ts[p::every]))
            for k, m in enumerate(marks):
                slots.append((m, marks[k + 1] if k + 1 < len(marks) else b1, "plain", []))
        elif style == "words":
            for k in range(0, len(ts), word):
                chunk, chunk_lv = ts[k:k + word], lv[k:k + word]
                end = ts[k + word] if k + word < len(ts) else b1
                slots.append((chunk[0], end, "push", _zoom_ticks(chunk, chunk_lv, step)))
        else:
            slots.append((b0, b1, style, _zoom_ticks(ts, lv, step)))
    # merge slots too short to see (under 2 frames) into the previous one
    out = []
    for s in slots:
        if out and s[1] - s[0] < 2 / FPS:
            p = out[-1]; out[-1] = (p[0], s[1], p[2], p[3])
        else:
            out.append(s)
    return out


def _assign(items, slots, video_target):
    """Walk files and slots in order. A video takes slots until it has played ~video_target s."""
    segs, k = [], 0
    for idx, it in enumerate(items):
        if k >= len(slots):
            return segs, len(items) - idx, 0
        if it["video"]:
            want = min(video_len(it["sorted"]), video_target)
            e = k
            while e + 1 < len(slots) and slots[e][1] - slots[k][0] < want * 0.85:
                e += 1
            segs.append((it, slots[k][0], slots[e][1], "video", []))
            k = e + 1
        else:
            s = slots[k]
            segs.append((it, s[0], s[1], s[2], s[3]))
            k += 1
    return segs, 0, len(slots) - k


def _fine_tune(slots, points, items, video_target):
    """Make the files fit exactly: split the longest plain slot at its strongest hit
    (one more picture) or merge the shortest plain slot into its neighbour (one fewer)."""
    slots = list(slots)
    for _ in range(40):
        segs, unused, left = _assign(items, slots, video_target)
        if unused:
            best = None
            for k, (a, b, kind, cl) in enumerate(slots):
                if kind != "plain":
                    continue
                inside = [p for p in points if a + 0.4 <= p[0] <= b - 0.4]
                if inside and (best is None or b - a > best[0]):
                    best = (b - a, k, max(inside, key=lambda p: p[1])[0])
            if not best:
                break
            _, k, t = best
            a, b, kind, cl = slots[k]
            slots[k:k + 1] = [(a, t, "plain", []), (t, b, "plain", [])]
        elif left:
            plain = [k for k, s in enumerate(slots) if s[2] == "plain" and k > 0]
            if not plain:
                break
            k = min(plain, key=lambda k: slots[k][1] - slots[k][0])
            p = slots[k - 1]
            slots[k - 1:k + 1] = [(p[0], slots[k][1], p[2], p[3])]
        else:
            break
    return slots


def plan_runs(items, points, runs, song_dur, seed=1, video_target=3.5):
    best = None
    for i in range(101):
        d = i / 100
        slots = _build_slots(points, runs, song_dur, d, seed)
        segs, unused, left = _assign(items, slots, video_target)
        score = (unused + left, abs(d - 0.5))
        if best is None or score < best[0]:
            best = (score, d, slots)
    _, d, slots = best
    slots = _fine_tune(slots, points, items, video_target)
    segs, unused, left = _assign(items, slots, video_target)
    if left:   # slots left over: the last file holds to the end
        it, a, _, kind, cl = segs[-1]
        segs[-1] = (it, a, song_dur, kind, cl)
    if unused:
        print(f"  note: {unused} files did not fit and were left out (the last ones)")
    return segs, d


def find_focus(items, neighbours=8, size=(160, 90)):
    """Where to zoom in each photo: the part that differs most from nearby shots.
    For a fixed camera (baby monitor, doorbell, webcam) the nearby shots share the same
    background, so their median is the 'empty' scene and the difference is the subject.
    Returns {file name: (x, y) as fractions}; pictures with no clear subject get the centre."""
    import numpy as np
    from PIL import Image, ImageFilter
    photos = [it for it in items if not it["video"]]
    small = {}
    for it in photos:
        try:
            with Image.open(it["sorted"]) as im:
                a = np.asarray(im.convert("L").resize(size), np.float32)
            small[it["sorted"].name] = (im.size, (a - a.mean()) / (a.std() + 1e-6))  # even out brightness
        except Exception:
            pass
    # prefer the middle: subjects are rarely at the very edge, fixed edges (bars, frames) always are
    yy, xx = np.mgrid[0:size[1], 0:size[0]]
    prior = np.exp(-(((xx / size[0] - 0.5) / 0.28) ** 2 + ((yy / size[1] - 0.5) / 0.30) ** 2) / 2)
    names = [it["sorted"].name for it in photos if it["sorted"].name in small]
    focus = {}
    for i, name in enumerate(names):
        shape, img = small[name]
        near = [names[j] for j in sorted(range(len(names)), key=lambda j: abs(j - i))
                if j != i and small[names[j]][0] == shape][:neighbours]
        if len(near) < 3:
            focus[name] = (0.5, 0.5); continue
        bg = np.median(np.stack([small[n][1] for n in near]), axis=0)
        diff = np.clip(np.abs(img - bg) * 60, 0, 255)
        diff = np.asarray(Image.fromarray(diff.astype(np.uint8)).filter(ImageFilter.BoxBlur(10)), np.float32)
        diff *= prior
        y, x = np.unravel_index(np.argmax(diff), diff.shape)
        clear = diff.max() > 2.0 * (diff.mean() + 1e-6)
        focus[name] = ((x + 0.5) / size[0], (y + 0.5) / size[1]) if clear else (0.5, 0.5)
    return focus


def load_focus_file(path, items):
    """Manual focus overrides, one per line:  <number or file name>, <x>, <y>
    x, y are fractions of the picture (0,0 = top-left, 1,1 = bottom-right), e.g.  23, 0.6, 0.3
    Numbers are positions in the sorted folder (#1 = first, as on the contact sheets)."""
    out = {}
    names = [it["sorted"].name for it in items]
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()            # '#' starts a comment
        if not line:
            continue
        key, x, y = [p.strip() for p in line.split(",")]
        name = names[int(key) - 1] if key.isdigit() else key
        out[name] = (float(x), float(y))
    return out


ZOOM_STEPS = (1.0, 1.25, 1.5)


def zoom_curve(kind, ticks, f0, n_frames, steps=ZOOM_STEPS):
    """Zoom factor for each frame of a photo segment - hard jumps on the ticks, no gliding.
    The segment opens on the first level; every later tick jumps to the next one:
      push:  100% -> 125% -> 150% -> 100% ...
      pull:  150% -> 125% -> 100% -> 150% ...
      pulse: 100% -> 125% -> 100% ...
    `f0` is the segment's first frame (absolute), so ticks land on the same frames as cuts."""
    seq = {"push": list(steps), "pull": list(steps)[::-1], "pulse": [steps[0], steps[1]]}.get(kind)
    if not seq:
        return [1.0] * n_frames
    tick_frames = sorted(round(c * FPS) - f0 for c in ticks)
    tick_frames = [f for f in tick_frames if f > 0]
    z, n = [], 0
    for f in range(n_frames):
        while n < len(tick_frames) and tick_frames[n] <= f:
            n += 1
        z.append(seq[n % len(seq)])
    return z


def render_photo_zoom(img: Path, zooms, seg: Path, focus=(0.5, 0.5)):
    """Render a photo with a per-frame zoom, piped to ffmpeg. The zoom is centred on
    `focus` (x, y as fractions of the picture), kept inside the picture."""
    from PIL import Image
    with Image.open(img) as im:
        im = im.convert("RGB")
        k = min(W / im.width, H / im.height)              # fit to the frame - enlarge small images too
        im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H))
        ox, oy = (W - im.width) // 2, (H - im.height) // 2
        canvas.paste(im, (ox, oy))
        fx, fy = ox + focus[0] * im.width, oy + focus[1] * im.height   # focus in canvas pixels
    cache = {}
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264",
                          "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", str(seg)],
                         stdin=subprocess.PIPE)
    for z in zooms:
        if z not in cache:                                # only a few levels: render each once
            if z <= 1.001:
                cache[z] = canvas.tobytes()
            else:
                cw, ch = W / z, H / z
                x0 = min(max(fx - cw / 2, 0), W - cw)
                y0 = min(max(fy - ch / 2, 0), H - ch)
                cache[z] = canvas.resize((W, H), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch)).tobytes()
        p.stdin.write(cache[z])
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg failed rendering {img.name}")


def render_runs(items, song, out: Path, seed=1, video_target=3.5, focus=None):
    points, song_dur = find_points(song, "onsets", 0.06)
    levels = hit_levels(song, [t for t, _ in points])
    runs = find_runs(points, 0.35, 0.3, 3, levels)
    segs, d = plan_runs(items, points, runs, song_dur, seed, video_target)
    from collections import Counter
    kinds = Counter(k for _, _, _, k, _ in segs)
    print(f"Found {len(points)} hits, {len(runs)} runs in the song ({song_dur:.0f}s); "
          f"density {d:.2f}; segments: {dict(kinds)}")
    tmp = Path(tempfile.mkdtemp(prefix="beatmovie_"))
    files, f0 = [], 0
    for n, (it, a, b, kind, clacks) in enumerate(segs):
        f1 = round(b * FPS)
        nframes = f1 - f0
        if nframes <= 0:
            continue
        seg = tmp / f"seg{n:05d}.mp4"
        if kind == "video":
            vl = video_len(it["sorted"])
            start = max(0.0, vl / 2 - nframes / FPS / 2)
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(it["sorted"]),
                 "-vf", VF + ",tpad=stop_mode=clone:stop=-1", "-frames:v", str(nframes),
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(seg)])
        else:
            fc = focus.get(it["sorted"].name, (0.5, 0.5)) if focus else (0.5, 0.5)
            render_photo_zoom(prep_photo(it["sorted"], tmp), zoom_curve(kind, clacks, f0, nframes), seg, fc)
        files.append(seg)
        f0 = f1
        print(f"\r  rendered {len(files)}/{len(segs)} segments", end="")
    print()
    total = f0 / FPS
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in files), encoding="utf-8")
    final = out / "movie_runs.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-i", str(song),
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-af", f"afade=t=out:st={total - 0.3:.2f}:d=0.3",
         "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", str(final)])
    (out / "movie_runs_plan.txt").write_text(
        "".join(f"{a:7.2f}-{b:7.2f}  {k:6s} {len(c):3d} hits  {it['sorted'].name}\n"
                for it, a, b, k, c in segs), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Done: {final}  ({total:.0f}s, {len(files)} segments)")


def render(items, song, out: Path, mode, min_gap, video_beats, section="whole",
           big_gap=0.8, video_max=8.0, seed=1, video_target=3.5, focus_mode="auto", focus_file=None):
    if section == "runs":
        focus = find_focus(items) if focus_mode == "auto" else {}
        if focus_file:
            focus.update(load_focus_file(focus_file, items))
        return render_runs(items, song, out, seed, video_target, focus)
    points, song_dur = find_points(song, mode, min_gap)
    print(f"Found {len(points)} {mode} in the song ({song_dur:.0f}s)")
    slots_needed = sum(video_beats if it["video"] else 1 for it in items)
    offset, fade_in, fade_out = 0.0, 0.0, 2.0
    times = [t for t, _ in points]
    spans = None
    if section == "big":
        bounds, spans = plan_big(items, points, song_dur, big_gap, video_max)
        fade_out = 0.3
        print(f"  {len(bounds) - 2} cuts on the biggest hits (at least {big_gap}s apart)")
    elif section == "start" and len(times) > slots_needed:
        # a new picture on every hit from the beginning; fade out after the last one
        bounds = [0.0] + times[1:slots_needed + 1]
    elif section == "end" and len(times) > slots_needed:
        # a new picture on every hit of the finale; end on the song's real last note
        tail = times[-slots_needed:]
        offset = max(0.0, tail[0] - 0.4)          # a short lead-in before the first cut
        bounds = [offset] + tail[1:] + [song_dur]
        bounds = [t - offset for t in bounds]
        fade_in, fade_out = 0.4, 0.3
    else:
        bounds = fit_points(points, slots_needed)
        if bounds[0] > 0.05:
            bounds = [0.0] + bounds  # first picture shows from the very start
    frames = [round(t * FPS) for t in bounds]

    # walk items in date order, assigning point-intervals
    if spans is None and slots_needed > len(frames) - 1:
        # more pictures than hits: spread evenly across the timeline
        step = slots_needed / (len(frames) - 1)
        print(f"  Song has fewer hits than files - using about 1 of every {step:.1f} files")
        chosen, acc = [], 0.0
        for it in items:
            acc += 1
            if acc >= step:
                chosen.append(it); acc -= step
        items = chosen

    tmp = Path(tempfile.mkdtemp(prefix="beatmovie_"))
    segs, k = [], 0
    for idx, it in enumerate(items):
        if spans is not None:
            k, end_k = spans[idx]
        else:
            if k >= len(frames) - 1:
                break
            span = video_beats if it["video"] else 1
            end_k = min(k + span, len(frames) - 1)
        nframes = frames[end_k] - frames[k]
        k = end_k
        if nframes <= 0:
            continue
        seg = tmp / f"seg{len(segs):05d}.mp4"
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-an", str(seg)]
        if it["video"]:
            vl = video_len(it["sorted"])
            start = max(0.0, vl / 2 - nframes / FPS / 2)  # take the middle of the clip
            # real speed; if the clip is shorter than its slot, hold its last frame
            run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-i", str(it["sorted"]),
                 "-vf", VF + ",tpad=stop_mode=clone:stop=-1", "-frames:v", str(nframes)] + enc)
        else:
            img = prep_photo(it["sorted"], tmp)
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(img),
                 "-vf", VF, "-frames:v", str(nframes)] + enc)
        segs.append(seg)
        print(f"\r  rendered {len(segs)} clips", end="")
    print()

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{s.as_posix()}'\n" for s in segs), encoding="utf-8")
    total = frames[k] / FPS
    final = out / f"movie_{section}.mp4"
    fade = min(fade_out, total / 4)
    af = f"afade=t=out:st={total - fade:.2f}:d={fade:.2f}"
    if fade_in:
        af = f"afade=t=in:d={fade_in}," + af
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-ss", f"{offset:.3f}", "-i", str(song), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-af", af,
         "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", str(final)])
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"Done: {final}  ({total:.0f}s, {len(segs)} cuts)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("song", nargs="?")
    ap.add_argument("output")
    ap.add_argument("--mode", choices=["onsets", "beats"], default="onsets")
    ap.add_argument("--min-gap", type=float, default=0.12)
    ap.add_argument("--video-beats", type=int, default=2)
    ap.add_argument("--sort-only", action="store_true")
    ap.add_argument("--gap", type=float, default=0.8,
                    help="big mode: shortest time between picture changes, in seconds")
    ap.add_argument("--video-max", type=float, default=8.0,
                    help="big mode: longest time a video plays, in seconds")
    ap.add_argument("--section", choices=["big", "runs", "whole", "start", "end"], default="big",
                    help="big: cut on the strongest hits; runs: bursts of fast hits get varied "
                         "zoom/flurry styles; whole: strongest hits, no gap; "
                         "start/end: a new picture on every hit of the song's opening/finale")
    ap.add_argument("--seed", type=int, default=1,
                    help="runs mode: change it for a different (repeatable) mix of styles")
    ap.add_argument("--video-target", type=float, default=3.5,
                    help="runs mode: how long a video plays, in seconds")
    ap.add_argument("--focus", choices=["auto", "center"], default="auto",
                    help="runs mode: where zooms aim. auto = what differs from nearby shots "
                         "(good for a fixed camera); center = the middle")
    ap.add_argument("--focus-file", default=None,
                    help="runs mode: manual focus per picture, lines of '<number or name>, x, y'")
    ap.add_argument("--name", default=None,
                    help=r"only files whose name matches this regex, e.g. _screenshot\.jpg$ or ^IMG_")
    a = ap.parse_args()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    items = collect(Path(a.input).resolve(), out, a.name)
    if not items:
        sys.exit("No photos or videos found.")
    if a.sort_only or not a.song:
        return
    render(items, Path(a.song).resolve(), out, a.mode, a.min_gap, a.video_beats, a.section,
           a.gap, a.video_max, a.seed, a.video_target, a.focus, a.focus_file)


if __name__ == "__main__":
    main()
