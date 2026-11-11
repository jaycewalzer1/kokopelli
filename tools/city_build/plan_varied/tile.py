#!/usr/bin/env python
"""Tile PNGs into one contact sheet: tile.py OUT.jpg W a.png b.png ... (W = tile width px, 2 columns)."""
import sys
from PIL import Image, ImageDraw
out, tw, files = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
ims = [Image.open(f).convert("RGB") for f in files]
th = int(tw * 9 / 16)
cols = 2 if len(ims) > 1 else 1
rows = (len(ims) + cols - 1) // cols
sheet = Image.new("RGB", (tw * cols, th * rows), (0, 0, 0))
for i, (im, f) in enumerate(zip(ims, files, strict=False)):
    im = im.resize((tw, th))
    ImageDraw.Draw(im).text((6, 4), f.split("/")[-1], fill=(255, 255, 0))
    sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
sheet.save(out, quality=85)
