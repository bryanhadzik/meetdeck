"""MeetDeck's icon now lives in app/static (meetdeck.svg is the source; meetdeck.png and
meetdeck.ico are rendered from it). Kept so old notes that mention this script still make sense:
it rebuilds the .ico from the .png.

    python windows/make_icon.py app/static
"""
import sys
from PIL import Image

out = sys.argv[1] if len(sys.argv) > 1 else "app/static"
img = Image.open(f"{out}/meetdeck.png").convert("RGBA")
img.save(f"{out}/meetdeck.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
