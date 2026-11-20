# beat_movie

Turns a set of photos and short videos into a movie cut to music: the pictures appear
in the order they were taken, and the picture changes on the song's hits.

Works with any photos/videos - a phone gallery, a Google Takeout export, a camera folder.

## How it works

1. **Collect** - takes every photo/video in a folder or zip (optionally only names matching `--name`).
2. **Sort** - by the time each was taken: a full timestamp in the file name, else Google's
   `.json` sidecar, EXIF, video metadata, or the file time. Copies them to `<output>/sorted/`.
3. **Find the hits** - measures where new sound starts in the song (plucks, drums, clicks).
4. **Plan the cuts** - by `--section` (see below).
5. **Render** - each photo is upright-corrected and fitted to 1920x1080, videos play at
   normal speed, the song goes underneath -> `<output>/movie_<section>.mp4`.

## Usage

```
python beat_movie.py INPUT [SONG] OUTPUT [options]
```

| Option | Default | Meaning |
|---|---|---|
| `--name REGEX` | all files | only files whose name matches, e.g. `_screenshot\.jpg$` |
| `--sort-only` | | only collect and sort, no movie |
| `--section big` | yes | whole song; cut on the strongest hits first, at least `--gap` apart |
| `--gap` | 0.8 | `big`: shortest time between picture changes (s) |
| `--video-max` | 8 | `big`: longest time a video plays (s) |
| `--section runs` | | bursts of fast hits get varied styles: flurry (crescendo), zoom out (softer), zoom in / pulse / "words" (steady); big hits between bursts |
| `--seed` | 1 | `runs`: a different, repeatable mix of styles |
| `--video-target` | 3.5 | `runs`: how long a video plays (s) |
| `--focus` | auto | `runs`: where zooms aim - `auto` (what differs from nearby shots; best for a fixed camera) or `center` |
| `--focus-file` | | `runs`: manual focus, lines of `<number>, x, y` (fractions; numbers as on the contact sheets) |
| `--section start` / `end` | | a new picture on every hit of the song's opening / finale |
| `--section whole` | | whole song, strongest hits, no minimum gap |
| `--video-beats` | 2 | `start`/`end`/`whole`: how many hits a video lasts |
| `--min-gap` | 0.12 | ignore hits closer together than this (s) |

Example - from a Google Takeout zip, keeping only one camera's files:

```
python tools\inspect_zip.py takeout.zip                        # see the file-name patterns
python beat_movie.py takeout.zip work --name "_screenshot\.jpg$" --sort-only
python tools\contact_sheet.py work\sorted work\contact_sheet.jpg  # check the picks
python beat_movie.py work\sorted song.mp3 work\render --section big --gap 0.8
```

`INPUT` can be the `sorted` folder of an earlier run - it keeps its order and dates.

## Files

| File | What it does |
|---|---|
| `beat_movie.py` | The main script (above). |
| `grow_movie.py` | "Watch them grow": one face fixed in the middle while photos change. Work in progress - see its `--help`. |
| `tools/inspect_zip.py` | File-name patterns inside a zip; `--pattern` counts matches. |
| `tools/contact_sheet.py` | One image with numbered thumbnails of a sorted folder. |
| `tools/analyze_song.py` | Hits per 5 seconds; `--slots N` shows how long N hits last. |
| `tools/verify_big_hits.py` | Checks a `big` movie: cuts on hits, biggest hits used. |
| `tools/verify_cuts.py` | Checks a `start`/`end` movie: cuts on hits. |
| `tools/find_runs.py` | Lists the runs (bursts of fast hits) in a song and whether they get louder/softer. |
| `tools/verify_runs.py` | Checks a `runs` movie: picture changes and zoom jumps on their frames, still between. |
| `tools/check_timing.py` | How close detected hits are to the real sound; audio delay in a movie. |
| `tools/focus_sheet.py` | Contact sheet showing where each zoom aims (`--focus-file` to include overrides). |
| `tools/grid_sheet.py` | Chosen pictures, large, with a 10% grid - to read coordinates for a focus file. |
| `focus/` | Manual focus files per run (small text files, versioned). |
| `setup.ps1` | Installs Python, FFmpeg, Git and the Python packages (pinned), then checks them. |
| `requirements.txt` | The Python packages and their exact versions. |
| `CHANGELOG.md` | What changed in the script, version by version, and why. |
| `RENDER_LOG.md` | Every movie made: script version, inputs and settings. |

Photos, videos, songs and movies are not versioned (see `.gitignore`); keep them in `work/`
or anywhere outside the project.

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

`-CheckOnly` only reports what's installed. librosa was used in v1 but is no longer needed:
it requires a Microsoft C++ runtime that may be missing, so v2 replaced it.
