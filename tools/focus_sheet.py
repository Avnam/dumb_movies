"""Contact sheet showing where the zoom will focus in each photo.

Usage: python tools/focus_sheet.py SORTED_FOLDER OUT.jpg [--focus-file FILE]

Red dot = focus point; red box = what a 150% zoom keeps; grey box = 125%.
Numbers are positions in the sorted folder - the same numbers --focus-file uses.
"""
import sys
from PIL import Image, ImageDraw
from _common import load_beat_movie, load_items

bm = load_beat_movie()
items = load_items(sys.argv[1], bm)
focus = bm.find_focus(items)
if "--focus-file" in sys.argv:
    focus.update(bm.load_focus_file(sys.argv[sys.argv.index("--focus-file") + 1], items))
number = {it["sorted"].name: k + 1 for k, it in enumerate(items)}   # same numbers as --focus-file
photos = [it for it in items if not it["video"]]
TW, TH, COLS = 240, 135, 8
rows = (len(photos) + COLS - 1) // COLS
sheet = Image.new("RGB", (COLS * TW, rows * TH), "white")
d = ImageDraw.Draw(sheet)
centre = 0
for n, it in enumerate(photos):
    with Image.open(it["sorted"]) as im:
        im = im.convert("RGB").resize((TW, TH))
    x0, y0 = (n % COLS) * TW, (n // COLS) * TH
    sheet.paste(im, (x0, y0))
    fx, fy = focus.get(it["sorted"].name, (0.5, 0.5))
    centre += (fx, fy) == (0.5, 0.5)
    for z, col in ((1.25, (170, 170, 170)), (1.5, (255, 0, 0))):
        cw, ch = TW / z, TH / z
        bx = min(max(fx * TW - cw / 2, 0), TW - cw); by = min(max(fy * TH - ch / 2, 0), TH - ch)
        d.rectangle([x0 + bx, y0 + by, x0 + bx + cw, y0 + by + ch], outline=col, width=2)
    d.ellipse([x0 + fx * TW - 5, y0 + fy * TH - 5, x0 + fx * TW + 5, y0 + fy * TH + 5], fill=(255, 0, 0))
    d.text((x0 + 4, y0 + TH - 14), f"#{number[it['sorted'].name]}", fill=(255, 255, 0))
sheet.save(sys.argv[2], quality=85)
print(f"{sys.argv[2]}: {len(photos)} photos, {centre} fell back to the centre")
