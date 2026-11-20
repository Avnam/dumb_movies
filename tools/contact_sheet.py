import sys, subprocess, io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

src, out = Path(sys.argv[1]), Path(sys.argv[2])
files = sorted(src.iterdir())
TW, TH, COLS, LAB = 240, 135, 8, 18
rows = (len(files) + COLS - 1) // COLS
sheet = Image.new("RGB", (COLS * TW, rows * (TH + LAB)), "white")
d = ImageDraw.Draw(sheet)
try:
    font = ImageFont.truetype("arial.ttf", 13)
except OSError:
    font = ImageFont.load_default()
for n, f in enumerate(files):
    if f.suffix.lower() == ".mp4":
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(f), "-frames:v", "1",
                              "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True).stdout
        im = Image.open(io.BytesIO(raw))
    else:
        im = Image.open(f)
    im = im.convert("RGB")
    im.thumbnail((TW, TH))
    x, y = (n % COLS) * TW, (n // COLS) * (TH + LAB)
    sheet.paste(im, (x + (TW - im.width) // 2, y))
    num, date = f.name.split("_")[0], f.name.split("_")[1]
    label = f"#{int(num)}  {date}" + ("  VIDEO" if f.suffix.lower() == ".mp4" else "")
    d.text((x + 4, y + TH + 2), label, fill="red" if "VIDEO" in label else "black", font=font)
sheet.save(out, quality=88)
print(out, sheet.size)
