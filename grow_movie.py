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


# ---------------------------------------------------------------- faces
def detect_faces(items, cache_file: Path, work_side=1600):
    """Faces in every photo: box, 5 landmarks, score, fingerprint, sharpness.
    Cached in cache_file (by file name + size), so re-runs are fast."""
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
            out[p.name] = cache[key]; continue
        try:
            img = load_bgr(p, work_side)
        except Exception as e:
            print(f"\n  skip {p.name}: {e}"); cache[key] = []; continue
        h, w = img.shape[:2]
        det.setInputSize((w, h))
        _, faces = det.detect(img)
        rows = []
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
                         "img_wh": [w, h]})
        cache[key] = out[p.name] = rows
        n_new += 1
        if n_new % 25 == 0:
            cache_file.write_text(json.dumps(cache))
        print(f"\r  faces: {k + 1}/{len(photos)} photos", end="")
    print()
    cache_file.write_text(json.dumps(cache))
    return out


def pick_person(items, faces, window_days=45, min_sim=0.30):
    """Choose the person's face in each photo (or none).
    Reference for a date = mean fingerprint of single-face photos within +-window_days
    (most single-face photos in a person's album are of that person). Each photo's face
    most similar to its reference wins, if similarity >= min_sim."""
    dated = [(it["date"], it["sorted"].name) for it in items if not it["video"]]
    single = [(d, np.array(faces[n][0]["feat"])) for d, n in dated if len(faces.get(n, [])) == 1]
    if not single:
        sys.exit("No single-face photos to learn the person from.")
    # 1st pass reference from all single-face photos, then drop outliers (other people
    # alone in a photo) and rebuild, so the reference is clean
    def reference(d, pool):
        near = [f for dd, f in pool if abs((dd - d).days) <= window_days]
        if len(near) < 3:
            near = [f for _, f in sorted(pool, key=lambda x: abs((x[0] - d).days))[:5]]
        m = np.mean(near, axis=0)
        return m / (np.linalg.norm(m) + 1e-9)
    clean = [(d, f) for d, f in single if float(f @ reference(d, single)) >= min_sim]
    pool = clean if len(clean) >= 5 else single
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
    return chosen


def quality(f):
    """Higher = better for the movie: big, sharp, facing the camera, confidently detected."""
    re_, le = np.array(f["lm"][0:2]), np.array(f["lm"][2:4])
    nose = np.array(f["lm"][4:6])
    eye_d = float(np.linalg.norm(le - re_))
    mid = (re_ + le) / 2
    frontal = 1 - min(1.0, abs(float(nose[0] - mid[0])) / (eye_d / 2 + 1e-6))   # 1 = straight on
    size = min(1.0, eye_d / 60)                         # eye distance >= 60 px counts as full size
    sharp = min(1.0, f["sharp"] / 300)
    return 0.35 * frontal + 0.25 * size + 0.25 * sharp + 0.15 * f["score"]


def choose_photos(items, chosen, count, min_quality=0.45):
    """Spread `count` photos evenly over time: split the time span into `count` slots
    and take the best photo in each (slots with no good photo are skipped)."""
    cand = [(it["date"], it["sorted"].name, quality(chosen[it["sorted"].name]))
            for it in items if it["sorted"].name in chosen]
    cand = [c for c in cand if c[2] >= min_quality]
    if not cand:
        return []
    cand.sort()
    t0, t1 = cand[0][0].timestamp(), cand[-1][0].timestamp()
    span = max(1.0, t1 - t0)
    best = {}
    for d, n, q in cand:
        slot = min(count - 1, int((d.timestamp() - t0) / span * count))
        if slot not in best or q > best[slot][2]:
            best[slot] = (d, n, q)
    return [best[s] for s in sorted(best)]


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


def render(picks, chosen, folder: Path, out_file: Path, size, fps, pps, style, fade,
           eye_y, eye_dist, label, birth):
    W, H = size
    frames_per_pic = max(1, round(fps / pps))
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264",
                          "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(out_file)],
                         stdin=subprocess.PIPE)
    prev = None
    nf = max(1, round(fade * fps)) if style == "crossfade" else 0
    for k, (d, name, q) in enumerate(picks):
        img = align(load_bgr(folder / name), chosen[name], size, eye_y, eye_dist)
        text = (age_text(d, birth) if label == "age" and birth else
                f"{d:%d.%m.%Y}" if label == "date" else "")
        cur = put_label(img, text)
        if prev is not None and nf:
            for i in range(1, nf + 1):                   # blend prev -> cur
                a = i / (nf + 1)
                p.stdin.write((prev * (1 - a) + cur * a).astype(np.uint8).tobytes())
            hold = max(1, frames_per_pic - nf)
        else:
            hold = frames_per_pic
        for _ in range(hold):
            p.stdin.write(cur.tobytes())
        prev = cur.astype(np.float32) if nf else cur
        print(f"\r  rendered {k + 1}/{len(picks)} pictures", end="")
    print()
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="folder or zip of photos (or a sorted folder from an earlier run)")
    ap.add_argument("output", help="output folder")
    ap.add_argument("--name", help="only files whose name matches this regex")
    ap.add_argument("--style", choices=["flipbook", "crossfade"], default="flipbook")
    ap.add_argument("--pps", type=float, default=10, help="pictures per second (default 10)")
    ap.add_argument("--fade", type=float, default=0.25, help="crossfade length in seconds")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--duration", type=float, help="movie length in seconds")
    g.add_argument("--count", type=int, help="number of pictures")
    ap.add_argument("--size", default="1920x1080", help="WIDTHxHEIGHT (default 1920x1080)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--eye-y", type=float, default=0.42, help="eye height, fraction of frame height")
    ap.add_argument("--eye-dist", type=float, default=0.09, help="eye distance, fraction of frame width")
    ap.add_argument("--min-sim", type=float, default=0.30,
                    help="how sure it must be that a face is the person (0-1, default 0.30)")
    ap.add_argument("--min-quality", type=float, default=0.45, help="skip worse photos (0-1)")
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
    count = a.count or round((a.duration or 60) * a.pps)
    picks = choose_photos(items, chosen, count, a.min_quality)
    print(f"  chose {len(picks)} pictures (asked for {count}), "
          f"{picks[0][0]:%d.%m.%Y} - {picks[-1][0]:%d.%m.%Y}" if picks else "  nothing to show")
    if not picks:
        return
    birth = datetime.strptime(a.birth, "%Y-%m-%d").date() if a.birth else None
    render(picks, chosen, out / "sorted", out / "grow.mp4", (W, H), a.fps, a.pps, a.style, a.fade,
           a.eye_y * H, a.eye_dist * W, a.label, birth)
    (out / "grow_plan.txt").write_text("".join(
        f"{k / a.pps:7.2f}s  {d:%Y-%m-%d %H:%M}  q={q:.2f}  sim={chosen[n]['sim']:.2f}  "
        f"faces={chosen[n]['n_faces']}  {n}\n" for k, (d, n, q) in enumerate(picks)), encoding="utf-8")
    secs = len(picks) / a.pps
    print(f"Done: {out / 'grow.mp4'}  ({len(picks)} pictures, {secs:.0f}s)")


if __name__ == "__main__":
    main()
