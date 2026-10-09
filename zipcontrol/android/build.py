"""Build the pinned scrcpy fork without changing the system scrcpy installation."""

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = "2926c06c5dc3064ae6d8db706f1a98a37cfcf3f0"
ARCHIVE_SHA = "537b2ade623cb94b6edddfa5c61bf0b0af21484aa8365ea2531b686ea573249a"


def replace(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError(f"Patch does not apply exactly once: {path.name}: {old[:60]}")
    path.write_text(text.replace(old, new))


def build():
    cache = ROOT / "artifacts/vendor"
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / "scrcpy-v4.1.tar.gz"
    if not archive.exists():
        urllib.request.urlretrieve(
            "https://github.com/Genymobile/scrcpy/archive/refs/tags/v4.1.tar.gz", archive
        )
    if hashlib.sha256(archive.read_bytes()).hexdigest() != ARCHIVE_SHA:
        raise RuntimeError("Upstream source checksum mismatch")
    with tarfile.open(archive) as tar:
        tar.extractall(cache, filter="data")
    upstream = cache / "scrcpy-4.1"
    package = upstream / "server/src/main/java/com/genymobile/scrcpy/control"
    shutil.copyfile(ROOT / "android/Guard.java", package / "Guard.java")
    for name in ["ControlMessage", "DeviceMessage"]:
        p = package / f"{name}.java"
        replace(
            p, "    private int type;", "    public static final int TYPE_GUARD = 200;\n    private int type;"
        )
        replace(
            p,
            "    public int getType() {",
            f"    public static {name} createGuard(String text) {{\n"
            f"        {name} msg = new {name}(); msg.type = TYPE_GUARD; msg.text = text; return msg;\n"
            "    }\n\n    public int getType() {",
        )
    replace(
        package / "ControlMessageReader.java",
        "        switch (type) {",
        """        switch (type) {
            case ControlMessage.TYPE_GUARD:
                int length = dis.readInt();
                if (length < 1 || length > 8192) throw new ControlProtocolException("Guard length");
                byte[] json = new byte[length]; dis.readFully(json);
                return ControlMessage.createGuard(new String(json, StandardCharsets.UTF_8));""",
    )
    replace(
        package / "DeviceMessageWriter.java",
        "            case DeviceMessage.TYPE_CLIPBOARD:",
        "            case DeviceMessage.TYPE_GUARD:\n            case DeviceMessage.TYPE_CLIPBOARD:",
    )
    controller = package / "Controller.java"
    replace(controller, "    private Thread thread;", "    private Thread thread;\n    private Guard guard;")
    replace(
        controller,
        "        sender = new DeviceMessageSender(controlChannel);",
        "        sender = new DeviceMessageSender(controlChannel);\n        guard = new Guard(this, sender);",
    )
    replace(
        controller,
        "        DisplayData data = new DisplayData(virtualDisplayId, positionMapper);",
        "        if (guard != null) guard.geometry(positionMapper.getVideoSize().getWidth(), positionMapper.getVideoSize().getHeight());\n"
        "        DisplayData data = new DisplayData(virtualDisplayId, positionMapper);",
    )
    replace(
        controller,
        '                Ln.d("Controller stopped");',
        '                if (guard != null) guard.close();\n                Ln.d("Controller stopped");',
    )
    replace(
        controller,
        "    public void stop() {",
        "    public void stop() {\n        if (guard != null) guard.close();",
    )
    replace(
        controller,
        "        int type = msg.getType();",
        """        if (guard != null) {
            if (msg.getType() != ControlMessage.TYPE_GUARD) {
                guard.close();
                return false; // no unguarded input in this fork
            }
            guard.accept(msg.getText());
            return true;
        }
        int type = msg.getType();""",
    )
    replace(
        controller,
        "    private boolean injectTouch(",
        """    boolean injectGuardTouch(int action, long pointer, Position position, float pressure) {
        if (getEventPointAndDisplayId(position) == null) {
            throw new IllegalStateException("Guard touch geometry mismatch");
        }
        boolean ok = injectTouch(action, pointer, position, pressure, 0, 0);
        if (!ok) Ln.e("Guard input rejected: action=" + action + " pointer=" + pointer + " position=" + position
            + " display=" + getEventPointAndDisplayId(position).second);
        return ok;
    }

    private boolean injectTouch(""",
    )
    script = upstream / "server/build_without_gradle.sh"
    replace(script, "SCRCPY_VERSION_NAME=4.1", "SCRCPY_VERSION_NAME=4.1-jipbul-guard-4")
    sdk = Path(os.environ.get("ANDROID_HOME", str(Path.home() / "Library/Android/sdk")))
    out = ROOT / "artifacts/android"
    out.mkdir(parents=True, exist_ok=True)
    env = dict(
        os.environ,
        ANDROID_HOME=str(sdk),
        ANDROID_PLATFORM="36",
        ANDROID_BUILD_TOOLS="36.0.0",
        BUILD_DIR=str(out),
    )
    subprocess.run(["bash", str(script)], env=env, check=True, cwd=upstream)
    binary = out / "scrcpy-server"
    manifest = {
        "version": "4.1-jipbul-guard-4",
        "protocol": "jipbul-guard-4",
        "upstream_commit": REVISION,
        "source_sha256": ARCHIVE_SHA,
        "guard_sha256": hashlib.sha256((ROOT / "android/Guard.java").read_bytes()).hexdigest(),
        "build_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copyfile(upstream / "LICENSE", out / "SCRCPY-LICENSE")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    build()
