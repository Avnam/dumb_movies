"""Larger view of chosen pictures with a 10% grid, to read focus coordinates for --focus-file.

Usage: python tools/grid_sheet.py SORTED_FOLDER OUT.jpg 7 18 21 ...

Grid lines every 0.1 (labelled along the top and left); numbers = positions in the folder.
"""
import sys
from PIL import Image, ImageDraw
from _common import load_beat_movie, load_items

bm = load_beat_movie()
items = load_items(sys.argv[1], bm)
nums = [int(n) for n in sys.argv[3:]]
TW, TH, COLS = 480, 270, 4
rows = (len(nums) + COLS - 1) // COLS
sheet = Image.new("RGB", (COLS * TW, rows * TH), "white")
d = ImageDraw.Draw(sheet)
for k, n in enumerate(nums):
    with Image.open(items[n - 1]["sorted"]) as im:
        im = im.convert("RGB").resize((TW, TH))
    x0, y0 = (k % COLS) * TW, (k // COLS) * TH
    sheet.paste(im, (x0, y0))
    for g in range(1, 10):
        d.line([x0 + g * TW / 10, y0, x0 + g * TW / 10, y0 + TH], fill=(0, 255, 255), width=1)
        d.line([x0, y0 + g * TH / 10, x0 + TW, y0 + g * TH / 10], fill=(0, 255, 255), width=1)
        d.text((x0 + g * TW / 10 + 2, y0 + 2), str(g), fill=(255, 255, 0))
        d.text((x0 + 2, y0 + g * TH / 10 + 2), str(g), fill=(255, 255, 0))
    d.text((x0 + TW - 40, y0 + TH - 18), f"#{n}", fill=(255, 0, 0))
sheet.save(sys.argv[2], quality=88)
print(sys.argv[2])
