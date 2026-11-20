# Changelog

Versions v1-v5 were written before version control started, so only their
descriptions are kept here; v5 is the first version stored in git.

## v7 - 2026-11-20 - "runs" mode: zoom and flurries on bursts of fast hits
- New `--section runs`. Finds runs: 3+ hits in a row with nearly the same short spacing
  (`find_runs`), and whether each gets louder/softer from the loudness after each hit
  (`hit_levels`; a single loud last hit doesn't count as a crescendo).
- Each run gets a style, varied through the song: crescendo -> flurry (new picture every
  1-3 hits), softer -> pull (zoom out per hit), steady -> push (zoom in per hit), pulse
  (zoom pulse on every other hit) or words (new picture every few hits). Runs under 5 hits
  that aren't crescendos are treated as ordinary hits. Between runs: big hits, min gap.
- A density knob is searched, then fine-tuned (split/merge), so the files fill the song
  exactly. `--seed` gives a different, repeatable mix; `--video-target` (default 3.5 s).
- Zoom is drawn frame by frame (PIL -> ffmpeg), 2-5% per hit. Writes `movie_runs_plan.txt`.
- Sorting an already-sorted folder no longer doubles the number/date prefix.
- New tools: `find_runs.py` (list runs in a song), `verify_runs.py` (checks cuts and zooms).
- Why: requested - on fast repeating hits, play with one picture instead of always cutting,
  and vary it (e.g. switch on every hit in a crescendo).

## v6 - 2026-11-20 - generic: nothing tied to one camera, person or song
- `beat_movie.py`: logic unchanged; help text and comments no longer mention a specific camera.
- Tools take settings instead of fixed values: `inspect_zip.py --pattern`,
  `analyze_song.py --slots`, `verify_big_hits.py --gap --video-max`, and
  `verify_cuts.py` counts the slots from the folder (was fixed at 98).
- Added `tools/_common.py` (shared loading of beat_movie and a sorted folder).
- README rewritten as a general guide; run-specific details live only in RENDER_LOG.md,
  without personal names. Work folder renamed `monitor_movie/` -> `work/`.
- `.gitignore` also excludes common photo/video/audio files anywhere in the project.

## Setup files - 2026-11-20
- Added `requirements.txt` (numpy 2.5.5, pillow 13.0.0, pillow-heif 1.8.1) and
  `setup.ps1`, which installs Python 3.12.10, FFmpeg 9.0.2 and Git 2.56.0 with winget,
  then the Python packages, and checks everything. The script itself is unchanged (still v5).

## v5 - 2026-11-19 - cut only on big hits (first version in git)
- New default mode `--section big`: uses the whole song; picks the strongest hits
  first and never puts two picture changes closer than `--gap` seconds (default 0.8).
- Videos play at normal speed for up to `--video-max` seconds (default 8) and still
  end on a hit. A clip shorter than its slot holds its last frame.
- Why: v4 changed the picture on every pluck - too fast, and videos were cut to ~1 s.

## v4 - 2026-11-19 - opening / finale sections
- `--section start`: a new picture on every hit of the song's opening, then fade out.
- `--section end`: a new picture on every hit of the finale, ending on the song's last note.
- Why: the song is 3 min with ~400 hits; 93 files need only ~98 of them.

## v3 - 2026-11-18 - read Google Takeout zips
- `--name REGEX` keeps only matching files and extracts only those from the zip.
- The date comes from a full timestamp in the file name first (most exact for the
  monitor), then Google's .json sidecar, EXIF, video metadata, file time.
- Why: the export holds all 2026 photos; only the monitor files are wanted.

## v2 - 2026-11-17 - numpy-only hit detection
- Replaced librosa with a small spectral-flux detector (numpy + ffmpeg decoding).
- Fixed a timing bug: cuts were 70 ms early; the analysis window is now centred.
- Why: librosa needs a Microsoft C++ runtime that is missing on this PC.

## v1 - 2026-11-17 - first version
- Collect photos/videos, sort by date, detect hits (librosa), render with ffmpeg.
