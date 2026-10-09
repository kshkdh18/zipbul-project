#!/usr/bin/env -S uv run --script
"""Install one explicitly identified fixture into a Zipscan SIMULATOR container."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("zip", type=Path)
parser.add_argument("--simulator", required=True)
args = parser.parse_args()
container = Path(subprocess.check_output([
    "xcrun", "simctl", "get_app_container", args.simulator, "com.zipbul.zipscan", "data"
], text=True).strip())
fixture_id = "00000000-0000-4000-8000-000000000001"
with tempfile.TemporaryDirectory(prefix="zipscan-ui-") as temporary:
    staging = Path(temporary)
    with zipfile.ZipFile(args.zip) as archive:
        for item in archive.infolist():
            if item.is_dir() or Path(item.filename).name != item.filename or item.filename in {".", ".."}:
                raise ValueError("Expected flat Zipscan archive")
        archive.extractall(staging)
    manifest = json.loads((staging / "manifest.json").read_text())
    manifest["session_id"] = fixture_id
    manifest["started_at"] = "2020-01-01T00:00:00Z"
    (staging / "manifest.json").write_text(json.dumps(manifest))
    destination = container / "Documents" / "Sessions" / fixture_id
    if destination.exists():
        shutil.rmtree(destination)  # Only this tool's reserved simulator fixture.
    shutil.copytree(staging, destination)
    print(destination)
