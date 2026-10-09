"""Optional diagnostic records; never an execution prerequisite."""

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def identity(bridge):
    from . import adb

    return {
        "serial": bridge.adb.serial,
        "server_sha256": bridge.transport.server_sha256,
        "transport_sha256": hashlib.sha256(Path(adb.__file__).read_bytes()).hexdigest(),
    }


def record(bridge, check, report, path=None):
    path = Path(path or ".runtime/diagnostic-records.json")
    key = identity(bridge)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        data = {}
    if data.get("identity") != key:
        data = {"identity": key, "checks": {}}
    data["checks"][check] = {"at": time.time(), "report": str(Path(report).resolve())}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as f:
            temporary = Path(f.name)
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
