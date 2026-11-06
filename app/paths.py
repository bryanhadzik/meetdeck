"""Where MeetDeck keeps its data: /data in the Docker server, Documents\\MeetDeck on Windows
(the Windows launcher sets MEETDECK_DATA)."""
import os
from pathlib import Path

DATA_ROOT = Path(os.environ.get("MEETDECK_DATA", "/data"))
DATA_ROOT.mkdir(parents=True, exist_ok=True)
