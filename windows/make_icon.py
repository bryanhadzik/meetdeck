"""MeetDeck icon (tray + shortcuts): a blue rounded square with three lane lines and 'MD'."""
import sys
from PIL import Image, ImageDraw, ImageFont

out = sys.argv[1]
S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.rounded_rectangle([8, 8, S - 8, S - 8], radius=48, fill=(31, 111, 235))
for y in (150, 180, 210):
    d.line([40, y, S - 40, y], fill=(255, 255, 255, 140), width=6)
try:
    f = ImageFont.truetype("DejaVuSans-Bold.ttf", 110)
except Exception:
    f = ImageFont.load_default()
d.text((S // 2, 82), "MD", fill="white", font=f, anchor="mm")
img.save(f"{out}/meetdeck.png")
img.save(f"{out}/meetdeck.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
