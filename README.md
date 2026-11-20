# beat_movie

Turns the baby monitor's screenshots and short recordings into a movie cut to music:
the picture changes on the song's hits.

## Files

| File | What it does |
|---|---|
| `beat_movie.py` | The main script: collects files, sorts them by date, finds the hits in the song, renders the movie. |
| `tools/inspect_zip.py` | Lists what's inside a Google Takeout zip (file-name patterns, counts). |
| `tools/contact_sheet.py` | Makes one image with thumbnails of all files, numbered in date order. |
| `tools/analyze_song.py` | Shows how many hits the song has per 5 seconds. |
| `tools/verify_big_hits.py` | Checks a "big" movie: are cuts on hits, are the biggest hits used. |
| `tools/verify_cuts.py` | Checks a "start"/"end" movie: are cuts on hits. |
| `setup.ps1` | Installs Python, FFmpeg, Git and the Python packages (pinned versions), then checks them. |
| `requirements.txt` | The Python packages and their exact versions. |
| `CHANGELOG.md` | What changed in the script, version by version, and why. |
| `RENDER_LOG.md` | Every movie made: which script version, song and settings. |

## Sources (not in version control)

- Photos: Google Takeout export of Google Photos, 2026 only
  (`takeout.zip`, 31 GB). Monitor files are named
  `<YYYYMMDDHHMMSS>_12345678_screenshot.jpg` and `..._record.mp4`.
- Song: `song.mp3`.

## Requirements

| Tool | Version | How |
|---|---|---|
| Python | 3.12.10 | winget `Python.Python.3.12` |
| FFmpeg | 9.0.2 (gyan.dev full build) | winget `Gyan.FFmpeg` |
| Git | 2.56.0 | winget `Git.Git` |
| Python packages | see `requirements.txt` | `pip install -r requirements.txt` |

To set up a PC, run in PowerShell from this folder:

```
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

`-CheckOnly` only reports what's installed. librosa was installed early on (v1) but is no
longer used: it needs a Microsoft C++ runtime this PC lacks, so v2 replaced it.

## How to remake the current movie

```
python beat_movie.py "<takeout zip>" monitor_movie --name "_12345678_" --sort-only
python beat_movie.py monitor_movie\sorted "<song.mp3>" monitor_movie\render --section big --gap 0.8 --video-max 8
```

Output: `monitor_movie\render\movie_big.mp4`. After rendering, add a line to `RENDER_LOG.md`.
