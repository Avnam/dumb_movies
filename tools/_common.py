"""Shared helpers for the tools: load beat_movie.py and list a sorted folder."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_beat_movie():
    spec = importlib.util.spec_from_file_location("beat_movie", ROOT / "beat_movie.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_items(folder, bm):
    """The files in a sorted folder, in order, as beat_movie items."""
    exts = bm.PHOTO_EXT | bm.VIDEO_EXT
    files = sorted(f for f in Path(folder).iterdir() if f.suffix.lower() in exts)
    return [{"sorted": f, "video": f.suffix.lower() in bm.VIDEO_EXT} for f in files]
