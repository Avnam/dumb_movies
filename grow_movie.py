"""
grow_movie.py - "watch them grow": one person's face stays fixed in the middle while
the photos change around it, in date order.

Steps:
  1. Collect + date-sort photos (same as beat_movie.py: folder or zip, --name filter).
  2. Find every face and its 5 landmarks (eyes, nose, mouth corners) - OpenCV YuNet.
  3. Pick the person: each face gets a fingerprint (OpenCV SFace). Single-face photos
     near the same date form a reference ("what they looked like that month"), and in
     every photo the face most like that reference is chosen - so a baby who changes a
     lot is still followed. Photos where no face matches well enough are skipped.
  4. Choose photos: face big, sharp and facing the camera, spread evenly over time.
  5. Align: rotate/scale/move each photo so the eyes land on the same spot.
  6. Render: flip-book (hard cuts) or crossfade, at a chosen pace and length.

Usage:
  python grow_movie.py INPUT OUTPUT [options]

Main options (see --help for all):
  --style flipbook|crossfade   how pictures change (default flipbook)
  --pps 10                     pictures per second
  --duration 60 | --count 600  movie length in seconds, or number of pictures
  --size 1920x1080             frame size (horizontal by default)
  --birth 2024-01-15 --label age|date|none   optional caption
Results: OUTPUT/grow.mp4, OUTPUT/grow_plan.txt (which photo, when, scores),
         OUTPUT/faces.json (cache of detected faces - delete it to re-detect).
"""
import argparse, json, re, subprocess, sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models"
YUNET = MODELS / "face_detection_yunet_2023mar.onnx"
SFACE = MODELS / "face_recognition_sface_2021dec.onnx"


def load_beat_movie():
    import importlib.util
    spec = importlib.util.spec_from_file_location("beat_movie", ROOT / "beat_movie.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_bgr(path: Path, max_side=None):
    """Open a photo upright (EXIF rotation applied), as an OpenCV BGR array."""
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        if max_side and max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        return np.ascontiguousarray(np.asarray(im)[:, :, ::-1])


def upright_size(path: Path):
    """Full width/height of a photo as displayed (EXIF rotation applied), without decoding it."""
    from PIL import Image
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        pass
    with Image.open(path) as im:
        w, h = im.size
        orient = im.getexif().get(274, 1)
    return [h, w] if orient in (5, 6, 7, 8) else [w, h]


# ---------------------------------------------------------------- faces
def detect_faces(items, cache_file: Path, work_side=1600):
    """Faces in every photo: box, 5 landmarks, score, fingerprint, sharpness, and the
    photo's full size (orig_wh). Landmarks are in the coordinates of a copy at most
    work_side pixels wide (img_wh). Cached in cache_file (by file name + size)."""
    import cv2
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    det = cv2.FaceDetectorYN.create(str(YUNET), "", (320, 320), 0.7, 0.3, 5000)
    rec = cv2.FaceRecognizerSF.create(str(SFACE), "")
    out, n_new = {}, 0
    photos = [it for it in items if not it["video"]]
    for k, it in enumerate(photos):
        p = it["sorted"]
        key = f"{p.name}|{p.stat().st_size}"
        if key in cache:
            rows = cache[key]
            for r in rows:                       # caches from before orig_wh existed
                if "orig_wh" not in r:
                    r["orig_wh"] = upright_size(p)
            out[p.name] = rows; continue
        try:
            img = load_bgr(p, work_side)
        except Exception as e:
            print(f"\n  skip {p.name}: {e}"); cache[key] = []; continue
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        rows = []
        orig = upright_size(p)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for f in (faces if faces is not None else []):
            x, y, bw, bh = f[:4]
            crop = rec.alignCrop(img, f)
            feat = rec.feature(crop).flatten()
            feat = feat / (np.linalg.norm(feat) + 1e-9)
            x0, y0 = max(0, int(x)), max(0, int(y))
            face_px = gray[y0:int(y + bh), x0:int(x + bw)]
            sharp = float(cv2.Laplacian(face_px, cv2.CV_64F).var()) if face_px.size else 0.0
            rows.append({"box": [float(v) for v in f[:4]],
                         "lm": [float(v) for v in f[4:14]],      # r-eye, l-eye, nose, r-mouth, l-mouth
                         "score": float(f[14]), "sharp": sharp,
                         "feat": [round(float(v), 5) for v in feat],
                         "img_wh": [w, h], "orig_wh": orig})
        cache[key] = out[p.name] = rows
        n_new += 1
        if n_new % 25 == 0:
            cache_file.write_text(json.dumps(cache))
        print(f"\r  faces: {k + 1}/{len(photos)} photos", end="")
    print()
    cache_file.write_text(json.dumps(cache))
    return out


def pick_person(items, faces, window_days=45, min_sim=0.363, rounds=4):
    """Choose the person's face in each photo (or none).
    Start: the reference for a date is the mean fingerprint of single-face photos near
    that date. Then, a few rounds: in each photo take the face most like its reference
    (if similarity >= min_sim), and rebuild the references from those accepted faces only.
    This locks onto the person who appears most consistently, and drops others who happen
    to be alone in a photo. 0.363 is the match threshold recommended for SFace."""
    dated = [(it["date"], it["sorted"].name) for it in items if not it["video"]]
    pool = [(d, np.array(faces[n][0]["feat"])) for d, n in dated if len(faces.get(n, [])) == 1]
    if not pool:
        sys.exit("No single-face photos to learn the person from.")

    def reference(d, pool):
        near = [f for dd, f in pool if abs((dd - d).days) <= window_days]
        if len(near) < 3:
            near = [f for _, f in sorted(pool, key=lambda x: abs((x[0] - d).days))[:5]]
        m = np.mean(near, axis=0)
        return m / (np.linalg.norm(m) + 1e-9)

    chosen = {}
    for r in range(rounds):
        chosen = {}
        for d, n in dated:
            fs = faces.get(n, [])
            if not fs:
                continue
            ref = reference(d, pool)
            sims = [float(np.array(f["feat"]) @ ref) for f in fs]
            i = int(np.argmax(sims))
            if sims[i] >= min_sim:
                chosen[n] = dict(fs[i], sim=sims[i], n_faces=len(fs))
        new_pool = [(d, np.array(chosen[n]["feat"])) for d, n in dated if n in chosen]
        if len(new_pool) < 5:
            break
        pool = new_pool
    return chosen


def pose(f):
    """Where the head points, from the 5 landmarks (eye line levelled first):
    yaw   = nose offset from the eyes' midpoint, in half eye-distances (0 = straight on,
            +-1 = nose under an eye, i.e. turned well away)
    pitch = nose height between eyes (0) and mouth (1); compared with the person's usual
            value it tells looking up / down
    roll  = eye-line angle in degrees (corrected by the alignment)
    eye_px = eye distance in the full-resolution photo."""
    lm = np.array(f["lm"]).reshape(5, 2)
    a, b = (lm[0], lm[1]) if lm[0][0] < lm[1][0] else (lm[1], lm[0])
    ang = np.arctan2(b[1] - a[1], b[0] - a[0])
    R = np.array([[np.cos(-ang), -np.sin(-ang)], [np.sin(-ang), np.cos(-ang)]])
    p = (lm - (a + b) / 2) @ R.T                          # eyes now level, midpoint at 0
    eye_d = float(np.linalg.norm(b - a))
    nose, mouth = p[2], (p[3] + p[4]) / 2
    yaw = float(nose[0] / (eye_d / 2 + 1e-9))
    pitch = float(nose[1] / (mouth[1] + 1e-9)) if mouth[1] > 1e-6 else 0.5
    k = f.get("orig_wh", f["img_wh"])[0] / f["img_wh"][0]
    return {"yaw": yaw, "pitch": pitch, "roll": float(np.degrees(ang)), "eye_px": eye_d * k}


def choose_photos(items, chosen, count, size, eye_dist="auto", max_upscale=1.0,
                  max_yaw=0.25, max_pitch=0.12, max_roll=35.0):
    """Pick the pictures for the movie.
    1. Keep only front-facing faces: turned at most max_yaw, tilted up/down at most
       max_pitch from the person's usual proportion, rolled at most max_roll degrees.
    2. Decide one face size for the whole movie (eye distance in output pixels): 'auto'
       = the largest size (up to 9% of the frame width) that 70% of those photos reach
       without being enlarged more than max_upscale. Photos that would need more
       enlarging are dropped, so nothing is blown up blurry.
    3. Spread `count` pictures evenly over time; in each time slot take the most
       straight-on, sharpest photo.
    Returns (picks, eye_dist_px, report)."""
    W, H = size
    cand = []
    for it in items:
        n = it["sorted"].name
        if n in chosen:
            ps = pose(chosen[n])
            cand.append((it["date"], n, ps))
    report = {"person": len(cand)}
    if not cand:
        return [], 0, report
    med_pitch = float(np.median([c[2]["pitch"] for c in cand]))
    cand = [c for c in cand if abs(c[2]["yaw"]) <= max_yaw and abs(c[2]["pitch"] - med_pitch) <= max_pitch
            and abs(c[2]["roll"]) <= max_roll]
    report["front_facing"] = len(cand)
    if not cand:
        return [], 0, report
    if eye_dist == "auto":
        reach = np.array([c[2]["eye_px"] * max_upscale for c in cand])
        eye_px = float(min(0.09 * W, np.percentile(reach, 30)))
    else:
        eye_px = float(eye_dist) * W
    cand = [c for c in cand if c[2]["eye_px"] * max_upscale >= eye_px]
    report["sharp_enough_size"] = len(cand)

    def score(c):
        f, ps = chosen[c[1]], c[2]
        straight = 1 - min(1.0, abs(ps["yaw"]) / max_yaw)
        level = 1 - min(1.0, abs(ps["pitch"] - med_pitch) / max_pitch)
        sharp = min(1.0, f["sharp"] / 300)
        return 0.45 * straight + 0.2 * level + 0.2 * sharp + 0.15 * f["score"]

    cand.sort()
    scored = [(c[0], c[1], score(c)) for c in cand]
    if len(scored) <= count:                     # not more good photos than wanted: use them all
        return scored, eye_px, report
    # more than wanted: the best photo in each of `count` equal time slots first (spreads
    # them over time), then fill up with the best of the rest - photos come in bursts,
    # so many slots are empty
    t0, t1 = scored[0][0].timestamp(), scored[-1][0].timestamp()
    span = max(1.0, t1 - t0)
    best = {}
    for c in scored:
        slot = min(count - 1, int((c[0].timestamp() - t0) / span * count))
        if slot not in best or c[2] > best[slot][2]:
            best[slot] = c
    picked = {c[1] for c in best.values()}
    rest = sorted((c for c in scored if c[1] not in picked), key=lambda c: -c[2])
    picked |= {c[1] for c in rest[:count - len(picked)]}
    return [c for c in scored if c[1] in picked], eye_px, report


# ---------------------------------------------------------------- align + render
def align(img, f, size, eye_y, eye_dist):
    """Rotate/scale/shift so the eyes land on fixed points (same for every photo)."""
    import cv2
    W, H = size
    sx, sy = img.shape[1] / f["img_wh"][0], img.shape[0] / f["img_wh"][1]   # detection ran on a smaller copy
    re_ = np.array([f["lm"][0] * sx, f["lm"][1] * sy])
    le = np.array([f["lm"][2] * sx, f["lm"][3] * sy])
    # target: eyes level, centred horizontally, eye_dist apart (in the image the
    # person's right eye is on the left)
    left_pt, right_pt = (re_, le) if re_[0] < le[0] else (le, re_)
    dst_l = np.array([W / 2 - eye_dist / 2, eye_y])
    dst_r = np.array([W / 2 + eye_dist / 2, eye_y])
    src_v, dst_v = right_pt - left_pt, dst_r - dst_l
    scale = np.linalg.norm(dst_v) / (np.linalg.norm(src_v) + 1e-9)
    ang = np.arctan2(dst_v[1], dst_v[0]) - np.arctan2(src_v[1], src_v[0])
    c, s = scale * np.cos(ang), scale * np.sin(ang)
    M = np.array([[c, -s, 0], [s, c, 0]], dtype=np.float64)
    M[:, 2] = dst_l - M[:, :2] @ left_pt
    return cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT,
                          borderValue=(0, 0, 0))


def age_text(d, birth):
    days = (d.date() - birth).days
    if days < 0:
        return ""
    months = days / 30.44
    if months < 1:
        return f"{days // 7} weeks" if days >= 7 else f"{days} days"
    if months < 24:
        return f"{int(months)} months"
    return f"{months / 12:.1f} years"


def put_label(frame, text):
    import cv2
    if not text:
        return frame
    H = frame.shape[0]
    scale = H / 900
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, scale, 2)
    org = (int(frame.shape[1] / 2 - tw / 2), int(H * 0.93))
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_DUPLEX, scale, (0, 0, 0), 6, cv2.LINE_AA)
    cv2.putText(frame, text, org, cv2.FONT_HERSHEY_DUPLEX, scale, (255, 255, 255), 2, cv2.LINE_AA)
    return frame


def render(picks, chosen, folder: Path, out_file: Path, size, fps, durations, style, fade,
           eye_y, eye_dist, label, birth, save_dir=None):
    """durations[k] = seconds picture k is shown. Frames are placed on the exact running
    time (rounded per picture), so a pace like 3.7 pictures/s keeps the right total.
    save_dir: also save each aligned picture as NNNN_YYYY-MM-DD__<original name>.jpg"""
    import cv2
    W, H = size
    if save_dir:
        save_dir.mkdir(parents=True, exist_ok=True)
        for old in save_dir.glob("*.jpg"):
            old.unlink()
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
                          "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(out_file)],
                         stdin=subprocess.PIPE)
    prev = None
    nf = max(1, round(fade * fps)) if style == "crossfade" else 0
    t, f_done = 0.0, 0
    for k, (d, name, q) in enumerate(picks):
        img = align(load_bgr(folder / name), chosen[name], size, eye_y, eye_dist)
        text = (age_text(d, birth) if label == "age" and birth else
                f"{d:%d.%m.%Y}" if label == "date" else "")
        cur = put_label(img, text)
        if save_dir:
            cv2.imwrite(str(save_dir / f"{k + 1:04d}_{d:%Y-%m-%d}__{Path(name).stem}.jpg"), cur,
                        [cv2.IMWRITE_JPEG_QUALITY, 90])
        t += durations[k]
        n_frames = max(1, round(t * fps) - f_done)
        f_done += n_frames
        fades = min(nf, n_frames - 1) if prev is not None else 0
        for i in range(1, fades + 1):                    # blend prev -> cur
            a = i / (fades + 1)
            p.stdin.write((prev * (1 - a) + cur * a).astype(np.uint8).tobytes())
        for _ in range(n_frames - fades):
            p.stdin.write(cur.tobytes())
        prev = cur.astype(np.float32) if nf else cur
        print(f"\r  rendered {k + 1}/{len(picks)} pictures", end="")
    print()
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return f_done / fps


def load_edits(path):
    """Edits file, one per line ('#' starts a comment):
         exclude <original file name, or part of it>
         dwell   <original file name, or part of it>  <seconds>
       Names are the photo's original name (as in the review folder after the '__')."""
    excl, dwell = [], {}
    if not path:
        return excl, dwell
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if parts[0] == "exclude" and len(parts) >= 2:
            excl.append(parts[1])
        elif parts[0] == "dwell" and len(parts) >= 3:
            dwell[parts[1]] = float(parts[2])
        else:
            sys.exit(f"Can't read edits line: {line}")
    return excl, dwell


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="folder or zip of photos (or a sorted folder from an earlier run)")
    ap.add_argument("output", help="output folder")
    ap.add_argument("--name", help="only files whose name matches this regex")
    ap.add_argument("--style", choices=["flipbook", "crossfade"], default="flipbook")
    pace = ap.add_mutually_exclusive_group()
    pace.add_argument("--pps", type=float, help="pictures per second (default 10)")
    pace.add_argument("--per10", type=float, help="pictures per 10 seconds, e.g. 37 (= 3.7 per second)")
    ap.add_argument("--fade", type=float, default=0.25, help="crossfade length in seconds")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--duration", type=float,
                   help="movie length in seconds (default: as long as all good photos need)")
    g.add_argument("--count", type=int, help="number of pictures (default: all good photos)")
    ap.add_argument("--edits", help="file of 'exclude <name>' and 'dwell <name> <seconds>' lines")
    ap.add_argument("--dwell-last", type=float, default=3.0,
                    help="seconds to stay on the last picture (default 3; 0 = normal pace)")
    ap.add_argument("--song", help="music under the movie; the last picture is held until the "
                                   "song ends (if the song is longer), or the song fades out "
                                   "at the end (if it is shorter)")
    ap.add_argument("--save-frames", action="store_true",
                    help="also save each aligned picture to OUTPUT/aligned/ (numbered, for review)")
    ap.add_argument("--size", default="1920x1080", help="WIDTHxHEIGHT (default 1920x1080)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--eye-y", type=float, default=0.42, help="eye height, fraction of frame height")
    ap.add_argument("--eye-dist", default="auto",
                    help="face size: eye distance as a fraction of frame width, or 'auto' (default): "
                         "the biggest size most photos reach without enlarging, max 0.09")
    ap.add_argument("--max-upscale", type=float, default=1.0,
                    help="how much a photo may be enlarged to reach the face size (1.0 = never; "
                         "photos needing more are left out)")
    ap.add_argument("--max-yaw", type=float, default=0.25,
                    help="how far the head may be turned left/right (0 = straight on, 1 = nose under an eye)")
    ap.add_argument("--max-pitch", type=float, default=0.12,
                    help="how far the head may tilt up/down from the person's usual look")
    ap.add_argument("--min-sim", type=float, default=0.363,
                    help="how sure it must be that a face is the person (0-1, default 0.363)")
    ap.add_argument("--window-days", type=int, default=45,
                    help="the person's look is learned from photos within this many days")
    ap.add_argument("--label", choices=["none", "age", "date"], default="none")
    ap.add_argument("--birth", help="birth date YYYY-MM-DD (for --label age)")
    a = ap.parse_args()

    if not YUNET.exists() or not SFACE.exists():
        sys.exit("Face models missing in models/ - run setup.ps1")
    W, H = (int(v) for v in a.size.lower().split("x"))
    out = Path(a.output).resolve(); out.mkdir(parents=True, exist_ok=True)
    bm = load_beat_movie()
    items = bm.collect(Path(a.input).resolve(), out, a.name)
    if not items:
        sys.exit("No photos found.")
    faces = detect_faces(items, out / "faces.json")
    chosen = pick_person(items, faces, a.window_days, a.min_sim)
    n_photos = sum(1 for it in items if not it["video"])
    print(f"  person found in {len(chosen)} of {n_photos} photos")
    excl, dwell = load_edits(a.edits)
    for pat in excl:
        hits = [n for n in chosen if pat in n]
        if not hits:
            print(f"  note: exclude '{pat}' matched no photo")
        for n in hits:
            del chosen[n]
    if excl:
        print(f"  excluded by the edits file: {len(excl)} rule(s)")
    pps = a.pps or (a.per10 / 10 if a.per10 else 10.0)
    count = a.count or (round(a.duration * pps) if a.duration else 10 ** 6)
    picks, eye_px, rep = choose_photos(items, chosen, count, (W, H), a.eye_dist, a.max_upscale,
                                       a.max_yaw, a.max_pitch)
    print(f"  front-facing: {rep.get('front_facing', 0)}; big enough for the face size "
          f"({eye_px:.0f} px between the eyes = {eye_px / W * 100:.1f}% of the width, "
          f"enlarging at most x{a.max_upscale}): {rep.get('sharp_enough_size', 0)}")
    asked = "all good photos" if count == 10 ** 6 else f"asked for {count}"
    print(f"  chose {len(picks)} pictures ({asked}), "
          f"{picks[0][0]:%d.%m.%Y} - {picks[-1][0]:%d.%m.%Y}" if picks else "  nothing to show")
    if not picks:
        return
    durations = [1 / pps] * len(picks)
    used = set()
    for k, (d, n, q) in enumerate(picks):
        for pat, secs in dwell.items():
            if pat in n:
                durations[k] = secs; used.add(pat)
    for pat in set(dwell) - used:
        print(f"  note: dwell '{pat}' matched no chosen picture")
    if a.dwell_last > 0:
        durations[-1] = max(durations[-1], a.dwell_last)
    song_len = None
    if a.song:
        song_len = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                         "-of", "csv=p=0", a.song], capture_output=True, text=True).stdout)
        extra = song_len - sum(durations)
        if extra > 0:
            durations[-1] += extra                       # hold the last picture until the song ends
            print(f"  song is {song_len:.1f}s: last picture held {extra:.2f}s longer")
    birth = datetime.strptime(a.birth, "%Y-%m-%d").date() if a.birth else None
    video = out / ("grow_video_only.mp4" if a.song else "grow.mp4")
    total = render(picks, chosen, out / "sorted", video, (W, H), a.fps, durations, a.style,
                   a.fade, a.eye_y * H, eye_px, a.label, birth,
                   out / "aligned" if a.save_frames else None)
    if a.song:
        fade = min(2.0, total / 4)
        af = f"afade=t=out:st={total - fade:.3f}:d={fade:.3f}" if song_len > total + 0.05 else "anull"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", a.song, "-map", "0:v",
                        "-map", "1:a", "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "192k",
                        "-t", f"{total:.3f}", str(out / "grow.mp4")], check=True)
        video.unlink()
    lines, t = [], 0.0
    for k, (d, n, q) in enumerate(picks):
        ps = pose(chosen[n])
        lines.append(f"#{k + 1:<4d} {t:7.2f}s  +{durations[k]:.2f}s  {d:%Y-%m-%d %H:%M}  q={q:.2f}  "
                     f"sim={chosen[n]['sim']:.2f}  yaw={ps['yaw']:+.2f}  pitch={ps['pitch']:.2f}  "
                     f"scale=x{eye_px / ps['eye_px']:.2f}  faces={chosen[n]['n_faces']}  {n}\n")
        t += durations[k]
    (out / "grow_plan.txt").write_text("".join(lines), encoding="utf-8")
    print(f"Done: {out / 'grow.mp4'}  ({len(picks)} pictures, {total:.1f}s at {pps * 10:g} per 10 s"
          f"{', ' + str(sum(1 for x in durations if x != 1 / pps)) + ' dwelling' if any(x != 1 / pps for x in durations) else ''})")


if __name__ == "__main__":
    main()
