from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
IMAGE_DIR = PROJECT_ROOT / "images"
SAVE_FILE = PROJECT_ROOT / "save.json"

LOGICAL_SIZE = (1280, 720)
WINDOW_TITLE = "回响之刃 | Echo Blade"
FPS = 60

COLORS = {
    "ink": (7, 12, 25),
    "panel": (6, 16, 28),
    "cyan": (79, 220, 214),
    "ice": (211, 255, 232),
    "muted": (141, 184, 190),
    "red": (239, 102, 105),
    "gold": (243, 204, 116),
    "white": (245, 251, 247),
}
