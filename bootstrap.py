"""Fetch the pinned upstream locally and create a narrowly patched entry module."""
from pathlib import Path
import argparse
import hashlib
import io
import json
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
COMMIT = "225454eb44f1ab6d5468e978b256b8767e5b760b"
REPO = "ShigetoshiMizuno/realtime-caption"
MAIN_BLOB = "70966dc1c04940060d2045d47ef39b4db430984d"
UPSTREAM = ROOT / "vendor" / "realtime-caption"
OLD = "            enable_realtime_transcription=False,"
NEW = """            enable_realtime_transcription=True,
            realtime_model_type=self._config.get('presense', {}).get('live_model', 'tiny.en'),
            realtime_processing_pause=self._config.get('presense', {}).get('partial_interval', 0.5),
            on_realtime_transcription_update=self._on_live,"""


def patch_main(source):
    if source.count(OLD) != 1:
        raise ValueError("Upstream hook differs; refusing an ambiguous patch")
    return source.replace(OLD, NEW, 1)


def setup():
    if not UPSTREAM.exists():
        url = f"https://github.com/{REPO}/archive/{COMMIT}.zip"
        print("Downloading pinned realtime-caption source...")
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(20 * 1024 * 1024 + 1)
        if len(data) > 20 * 1024 * 1024:
            raise ValueError("Unexpectedly large source archive")
        UPSTREAM.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=UPSTREAM.parent) as tmp:
            base = Path(tmp).resolve()
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for item in archive.infolist():
                    dest = (base / item.filename).resolve()
                    if not dest.is_relative_to(base):
                        raise ValueError("Unsafe archive path")
                archive.extractall(base)
            extracted = base / f"realtime-caption-{COMMIT}"
            verify(extracted / "main.py")
            shutil.move(str(extracted), UPSTREAM)
    verify(UPSTREAM / "main.py")
    text = (UPSTREAM / "main.py").read_text(encoding="utf-8")
    (UPSTREAM / "presense_upstream.py").write_text(patch_main(text), encoding="utf-8")
    config = ROOT / "config.yaml"
    if not config.exists():
        shutil.copyfile(ROOT / "config.yaml.example", config)
    print("Source ready. Original main.py remains available for baseline testing.")


def verify(path):
    raw = path.read_bytes()
    digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    if digest != MAIN_BLOB:
        raise ValueError("Upstream main.py does not match pinned source; no files patched")


if __name__ == "__main__":
    setup()
