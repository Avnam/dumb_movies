# dumb_movies

Two small tools that turn your own photos into short movies, entirely on your own Windows PC:

- **`grow_movie.py` - "watch them grow".** One person's face stays fixed in the middle of the
  screen - same place, same size, always facing the camera - while the photos around it change
  in date order. A baby turns into a toddler in a minute. Optional age caption and music.
- **`beat_movie.py` - movies cut to music.** Photos and short videos in date order, with the
  picture changing on the song's beats (or zooming on fast bursts, like typewriter clacks).

Nothing is uploaded anywhere: face detection, choosing and editing all run locally.

---

## Contents

1. [Install (once)](#1-install-once)
2. [Get the photos of one person from Google Photos](#2-get-the-photos-of-one-person-from-google-photos)
3. [Make a "watch them grow" movie](#3-make-a-watch-them-grow-movie)
4. [Fine-tune: remove pictures, dwell on favourites](#4-fine-tune-remove-pictures-dwell-on-favourites)
5. [Add music (and shorten a long song)](#5-add-music-and-shorten-a-long-song)
6. [Movies cut to music (`beat_movie.py`)](#6-movies-cut-to-music-beat_moviepy)
7. [All options](#7-all-options)
8. [For AI agents helping someone run this](#8-for-ai-agents-helping-someone-run-this)
9. [Privacy and troubleshooting](#9-privacy-and-troubleshooting)

---

## 1. Install (once)

You need **Windows 10/11**.

1. Get the project: on GitHub click **Code -> Download ZIP**, unzip it (for example to
   `Documents\dumb_movies`). Or, with Git: `git clone https://github.com/Avnam/dumb_movies.git`
2. Open **PowerShell** in that folder (in File Explorer: click the address bar, type
   `powershell`, press Enter).
3. Run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup.ps1
   ```

   This installs Python 3.12, FFmpeg and Git (with `winget`), the Python packages from
   `requirements.txt`, and downloads two small face models from the official OpenCV model zoo
   (checked by SHA-256). It skips anything already installed and ends with **"All set."**
   Run `.\setup.ps1 -CheckOnly` any time to just check.

After installing, close and reopen PowerShell so the new programs are found. In the commands
below, `python` means the Python that setup installed; if `python` isn't found, use
`& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"` instead.

---

## 2. Get the photos of one person from Google Photos

The best input is an album that holds **only that person**. Google Photos can build and keep it
up to date by itself, and Google Takeout lets you download just that album.

### a. Make a live album of the person (2 minutes)

1. Open **photos.google.com**.
2. Click **+** (Create) -> **Album**, and give it a name, e.g. `Noa_AUTO`.
3. Click **Select people & pets** (not "Select photos") and pick the person's face.
4. The album fills with every photo Google recognises them in, and keeps adding new ones.
   Check its date range under the title - it should start at the date you expect.
   - **Babies:** Google often splits one child into several face groups (baby / toddler).
     If the album starts too late, go to **People & pets**, give each of their faces the
     same name (Google asks "same person?" - answer yes), and the album fills in.
   - An album only points at your photos: no copies, no extra storage.

### b. Download just that album with Google Takeout

1. Go to **takeout.google.com**.
2. Click **Deselect all**, then tick only **Google Photos**.
3. Click **All photo albums included**, then **Deselect all**, tick only your album, **OK**.
4. **Next step**: *Send download link via email*, *Export once*, file type **.zip**, size
   **50 GB** (so it comes as one file). Click **Create export**.
5. Google emails you when it's ready (minutes to hours). Click the button in the email ->
   **Download**. Keep the zip in `Downloads`; you don't need to unzip it.

Notes:
- Google sends a security email "a request was made to create an archive of your Google
  data" - that's expected. Takeout only makes a **copy**; it never deletes anything.
- Takeout can also repeat the export every 2 months for a year (step 4, frequency).
- Photos from a phone folder or a camera work too - point the tool at the folder instead.

---

## 3. Make a "watch them grow" movie

```powershell
python grow_movie.py "$env:USERPROFILE\Downloads\takeout-XXXX.zip" work\grow --name "\.(jpe?g|png|heic|webp)$" --per10 70 --label age --birth 2024-01-15 --save-frames
```

- First argument: the Takeout zip (or a folder of photos). Second: an output folder.
- `--name ...` takes only photos (videos are skipped - this movie uses photos only).
- `--per10 70` = 70 pictures per 10 seconds. Slower: 37. Faster: 100.
- `--label age --birth YYYY-MM-DD` shows the age ("3 months", "1.2 years") at the bottom.
- `--save-frames` also saves every picture as it appears in the movie, for reviewing.

The first run finds the faces in every photo (a few minutes for ~1,000 photos) and remembers
them in `work\grow\faces.json`, so every later run takes a minute or two.

**What it does, step by step**
1. Sorts the photos by the date they were taken.
2. Finds every face and its eyes, nose and mouth (OpenCV YuNet).
3. Works out which face is the person, photo by photo, by comparing each face with the person's
   look around the same date (OpenCV SFace) - so it keeps following a baby whose face changes.
4. Keeps only photos where the head faces the camera and the face is big enough to need **no
   enlarging** (nothing gets blurry). One face size is used for the whole movie.
5. Rotates, scales and shifts every photo so the eyes land on exactly the same spot.
6. Writes `work\grow\grow.mp4` and `work\grow\grow_plan.txt` (which photo shows when).

The output folder also has `sorted\` (all photos, in date order) and, with `--save-frames`,
`aligned\` (each movie picture, numbered: `0001_2024-01-20__<original name>.jpg`).

---

## 4. Fine-tune: remove pictures, dwell on favourites

1. Make numbered contact sheets of the movie pictures:

   ```powershell
   python tools\review_sheets.py work\grow\aligned work\grow\review --plan work\grow\grow_plan.txt
   ```

   Each page shows 60 pictures with big numbers; pictures that already dwell have a green frame.

2. Write an **edits file**, e.g. `my_edits.txt`. Use each photo's **original name** (the part
   after `__` in the `aligned` file name) - names stay valid even when numbers shift:

   ```text
   # remove a photo (someone else, a blurry face, ...)
   exclude IMG_20240301_101500
   # show a photo longer: name and seconds
   dwell   IMG_20240115_093000 4
   dwell   IMG_20240620_174512 2.2
   ```

3. Run again with `--edits my_edits.txt`. The last picture dwells 3 s by default
   (`--dwell-last`).

---

## 5. Add music (and shorten a long song)

Add `--song song.mp3`. The pictures are **not** synced to the beat in this movie - the music
just plays underneath. If the song is longer than the pictures, the last picture stays until the
song ends; if it's shorter, the song fades out at the end.

**Shorten a song without an obvious cut.** `tools\cut_song.py` finds two places in the song that
sound the same (same chords and sound, several beats before and after), and jumps from one to
the other exactly on the beat, with a tiny 30 ms blend. The intro and the real ending are kept.

```powershell
# see the 5 best ways to reach ~90 seconds
python tools\cut_song.py song.mp3 --target 90 --plan
# write plan 1 (or --choice 2, ...)
python tools\cut_song.py song.mp3 --target 90 --choice 1 --out work\song_cut.mp3
```

To know the target: run the movie once without a song - the last line says how long it is.
Listen to the result around the jump times it prints; if a jump lands mid-word, try another plan.

**Where to get the mp3.** Use music you own, or royalty-free music - the YouTube Audio Library
and Pixabay Music are free and safe to post online. People also mention tools like
*Spotimate* (spotimate.app) that save songs from Spotify as mp3; be aware that this usually
breaks Spotify's terms of use and the song's copyright, so it's at your own risk, and a movie
with such a song may be blocked if you post it publicly.

---

## 6. Movies cut to music (`beat_movie.py`)

Photos **and videos** in date order; the picture changes on the music.

```powershell
# 1) collect + sort (optionally only some file names, e.g. one camera's)
python beat_movie.py "$env:USERPROFILE\Downloads\takeout-XXXX.zip" work\beat --name "_screenshot\.jpg$" --sort-only
python tools\contact_sheet.py work\beat\sorted work\beat\contact_sheet.jpg
# 2) the movie
python beat_movie.py work\beat\sorted song.mp3 work\beat\render --section big --gap 0.8
```

Styles (`--section`):
- `big` (default): a new picture on the song's biggest hits, at least `--gap` seconds apart;
  videos play up to `--video-max` seconds.
- `runs`: fast bursts of hits (typewriter clacks, drum rolls) hold one picture and zoom in /
  out / pulse on the hits; crescendos flip pictures quickly. `--seed` gives another mix.
- `start` / `end`: a new picture on every hit of the song's opening / finale.

`tools\inspect_zip.py ZIP` lists the file-name patterns inside a zip (useful for `--name`).

---

## 7. All options

Every script explains itself: `python grow_movie.py --help`, `python beat_movie.py --help`,
`python tools\cut_song.py --help`.

`grow_movie.py` (most useful):

| Option | Default | Meaning |
|---|---|---|
| `--per10 N` / `--pps N` | 10 per s | pace: pictures per 10 seconds / per second |
| `--duration S` / `--count N` | all good photos | limit the length (keeps a spread over time) |
| `--edits FILE` | | `exclude` / `dwell` lines (section 4) |
| `--dwell-last S` | 3 | seconds on the last picture |
| `--song FILE` | | music underneath |
| `--label age\|date\|none` + `--birth` | none | caption at the bottom |
| `--style flipbook\|crossfade` | flipbook | hard cuts, or blend (`--fade` seconds) |
| `--size WxH` | 1920x1080 | frame size, e.g. `1080x1920` for phones |
| `--eye-dist` | auto | face size (auto = largest size most photos reach without enlarging) |
| `--max-upscale` | 1.0 | allow enlarging a little (1.2) to keep more photos |
| `--max-yaw` / `--max-pitch` | 0.25 / 0.12 | how turned / tilted a head may be |
| `--min-sim` | 0.363 | how sure "this face is the person" must be |
| `--save-frames` | | save every movie picture to `aligned\` |

---

## 8. For AI agents helping someone run this

- **Platform:** Windows, PowerShell 5.1. Python 3.12 at
  `%LOCALAPPDATA%\Programs\Python\Python312\python.exe` (the Microsoft Store `python` alias is
  not it). FFmpeg/ffprobe/git on PATH after `setup.ps1` (open a new shell, or reload PATH from
  the registry). Verify with `.\setup.ps1 -CheckOnly`.
- **PowerShell gotchas:** don't put double quotes inside arguments to native programs (5.1
  mangles them) - write commit messages / Python snippets to a file instead; write files with
  UTF-8 *without* BOM; Hebrew or other non-ASCII names print fine only if Python's stdout is
  reconfigured to UTF-8. `2>&1` on native programs shows harmless `NativeCommandError` lines.
- **Inputs:** a Takeout zip or a folder. Never unzip a whole Takeout - the scripts extract only
  matching files (`--name`). Keep all outputs under `work\` (ignored by git).
- **Caching:** `OUTPUT\faces.json` holds detected faces. Re-run into the **same** output folder
  (or copy `faces.json` and keep the same `sorted\` names) - otherwise detection starts over.
- **Long runs:** face detection is ~0.5 s per phone photo; run it in the background and read
  the log ("faces: N/M photos").
- **Check results by eye before handing over a movie:** contact sheet of frames, e.g.
  `ffmpeg -i grow.mp4 -vf "select='not(mod(n\,12))',scale=192:-1,tile=10x10" -frames:v 1 sheet.jpg`.
  Look for other people (other children, faces in paintings, dolls, ID cards). Remove them with
  `exclude` lines - and ask the human; never guess who is who.
- **Verification tools:** `tools\verify_runs.py`, `tools\verify_big_hits.py`,
  `tools\verify_cuts.py` (beat movies: are cuts on hits), `tools\check_timing.py` (hit accuracy,
  audio delay), `tools\focus_sheet.py` (where zooms aim).
- **Personal data:** photos, movies, songs, `faces.json`, edits files, focus files and any run
  log are personal. `.gitignore` excludes `work/`, media files, `RENDER_LOG.md`, `grow/`,
  `focus/` - keep personal files there and never commit them. Don't put names or birth dates in
  code or commit messages.
- **Music:** don't download copyrighted songs for the user; work with files they provide.

---

## 9. Privacy and troubleshooting

**Privacy.** Everything runs on your PC. The only downloads are the installers and the two face
models (from github.com/opencv/opencv_zoo, checked by SHA-256). Your photos never leave your
computer. Output, photos and your edits stay in folders git ignores.

**Troubleshooting**
- *"Face models missing"* - run `.\setup.ps1`.
- *"python is not recognized" / opens the Microsoft Store* - use the full path in section 1.
- *The movie shows someone else* - add `exclude` lines, or raise `--min-sim` (e.g. 0.42).
- *Too few pictures* - allow slightly turned heads (`--max-yaw 0.3`) or a little enlarging
  (`--max-upscale 1.2`), or add more photos to the album.
- *Black areas around pictures* - expected when a photo is rotated or shrunk to fit the face
  size; a bigger `--eye-dist` fills more, but drops photos with small faces.
- *Takeout zip "is not a zip file"* - it's still downloading; wait for the browser to finish.

---

Files: `grow_movie.py`, `beat_movie.py`, `tools\` (helpers listed above), `setup.ps1`,
`requirements.txt`, `CHANGELOG.md` (what changed and why).
