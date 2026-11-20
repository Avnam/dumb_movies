import sys, re, subprocess, importlib.util, json
spec = importlib.util.spec_from_file_location("bm", sys.argv[1])
bm = importlib.util.module_from_spec(spec); spec.loader.exec_module(bm)
song, movie, section = sys.argv[2], sys.argv[3], sys.argv[4]
pts, dur = bm.find_points(song, "onsets", 0.12)
times = [t for t, _ in pts]
err = subprocess.run(["ffmpeg", "-i", movie, "-vf", "select='gt(scene,0.03)',showinfo", "-an", "-f", "null", "-"],
                     capture_output=True, text=True, errors="replace").stderr
cuts = [float(x) for x in re.findall(r"pts_time:([\d.]+)", err)]
offset = max(0.0, times[-98] - 0.4) if section == "end" else 0.0
hits = [t - offset for t in times]
d = [min(abs(c - h) for h in hits) for c in cuts]
info = json.loads(subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", movie],
                                 capture_output=True, text=True).stdout)
durs = {s["codec_type"]: round(float(s["duration"]), 2) for s in info["streams"]}
print(f"{section}: detected cuts {len(cuts)}, on a hit (<=40ms): {sum(x <= 0.04 for x in d)}, "
      f"worst {max(d)*1000:.0f}ms, stream durations {durs}")
