"""Check a movie made with --section start or end: are the cuts on hits?

Usage: python tools/verify_cuts.py SONG MOVIE SORTED_FOLDER start|end [--video-beats 2]
"""
import argparse, json, re, subprocess
from _common import load_beat_movie, load_items

ap = argparse.ArgumentParser()
ap.add_argument("song"); ap.add_argument("movie"); ap.add_argument("folder")
ap.add_argument("section", choices=["start", "end"])
ap.add_argument("--video-beats", type=int, default=2)
a = ap.parse_args()

bm = load_beat_movie()
pts, dur = bm.find_points(a.song, "onsets", 0.12)
items = load_items(a.folder, bm)
slots = sum(a.video_beats if it["video"] else 1 for it in items)
times = [t for t, _ in pts]
offset = max(0.0, times[-slots] - 0.4) if a.section == "end" else 0.0   # same lead-in as render()
hits = [t - offset for t in times]

err = subprocess.run(["ffmpeg", "-i", a.movie, "-vf", "select='gt(scene,0.03)',showinfo", "-an", "-f", "null", "-"],
                     capture_output=True, text=True, errors="replace").stderr
cuts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", err)]
d = [min(abs(c - h) for h in hits) for c in cuts]
info = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", a.movie],
                                 capture_output=True, text=True).stdout)
durs = {s["codec_type"]: round(float(s["duration"]), 2) for s in info["streams"]}
print(f"{a.section}: {slots} slots, detected cuts {len(cuts)}, on a hit (<=40ms): {sum(x <= 0.04 for x in d)}, "
      f"worst {max(d) * 1000 if d else 0:.0f}ms, stream durations {durs}")
