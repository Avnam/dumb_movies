"""Pages of numbered thumbnails from a grow_movie 'aligned' folder, for choosing pictures.

Usage: python tools/review_sheets.py ALIGNED_FOLDER OUT_FOLDER [--per-page 60]

Each thumbnail shows its number (as in the file name and the movie order) and date.
"""
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ap = argparse.ArgumentParser()
ap.add_argument("folder"); ap.add_argument("out")
ap.add_argument("--per-page", type=int, default=60)
a = ap.parse_args()

files = sorted(Path(a.folder).glob("*.jpg"))
out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
for old in out.glob("review_*.jpg"):
    old.unlink()
TW, TH, COLS = 320, 180, 10
try:
    font = ImageFont.truetype("arialbd.ttf", 26)
except OSError:
    font = ImageFont.load_default()
for page in range(0, len(files), a.per_page):
    chunk = files[page:page + a.per_page]
    rows = (len(chunk) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * TW, rows * TH), "black")
    d = ImageDraw.Draw(sheet)
    for k, f in enumerate(chunk):
        with Image.open(f) as im:
            im = im.convert("RGB").resize((TW, TH))
        x, y = (k % COLS) * TW, (k // COLS) * TH
        sheet.paste(im, (x, y))
        num = int(f.name.split("_")[0])
        label = f"{num}"
        d.rectangle([x, y, x + 64, y + 32], fill=(0, 0, 0))
        d.text((x + 6, y + 2), label, fill=(255, 220, 0), font=font)
        d.rectangle([x, y, x + TW - 1, y + TH - 1], outline=(60, 60, 60))
    name = out / f"review_{page + 1:04d}-{page + len(chunk):04d}.jpg"
    sheet.save(name, quality=85)
    print(name)
