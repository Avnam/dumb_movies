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
    if m:  # full timestamp in the name (e.g. monitor screenshots) is the most exact
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
        name = f"{i:04d}_{it['date']:%Y-%m-%d_%H%M%S}_{it['path'].name}"
        dest = sorted_dir / name
        if not dest.exists():
            shutil.copy2(it["path"], dest)
        it["sorted"] = dest
    print(f"Collected {len(items)} files ({sum(i['video'] for i in items)} videos) -> {sorted_dir}")
    if items:
        print(f"  from {items[0]['date']:%Y-%m-%d} to {items[-1]['date']:%Y-%m-%d}")
    return items


# ---------------------------------------------------------------- music
def find_points(song: Path, mode: str, min_gap: float):
    import numpy as np
    sr, hop, nfft = 22050, 256, 1024
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(song), "-ac", "1", "-ar", str(sr),
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    y = np.frombuffer(raw, dtype=np.float32)
    dur = len(y) / sr
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
    # enforce minimum gap, keeping the stronger hit
    keep = []
    for t, s in sorted(zip(times, strength)):
        if keep and t - keep[-1][0] < min_gap:
            if s > keep[-1][1]:
                keep[-1] = (t, s)
        else:
            keep.append((t, s))
    return [(float(t), float(s)) for t, s in keep], dur


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


def render(items, song, out: Path, mode, min_gap, video_beats, section="whole",
           big_gap=0.8, video_max=8.0):
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
    ap.add_argument("--section", choices=["big", "whole", "start", "end"], default="big",
                    help="whole: spread over the song using the strongest hits; "
                         "start/end: a new picture on every hit of the song's opening/finale")
    ap.add_argument("--name", default=None,
                    help=r"only files whose name matches this regex, e.g. ^screensh_12345678_")
    a = ap.parse_args()
    out = Path(a.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    items = collect(Path(a.input).resolve(), out, a.name)
    if not items:
        sys.exit("No photos or videos found.")
    if a.sort_only or not a.song:
        return
    render(items, Path(a.song).resolve(), out, a.mode, a.min_gap, a.video_beats, a.section,
           a.gap, a.video_max)


if __name__ == "__main__":
    main()
