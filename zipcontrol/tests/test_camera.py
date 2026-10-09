import base64
import io
import json
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image
from test_mission import LiveFrames, Rig, args, executor

from zipcontrol.astra import Astra, Decision
from zipcontrol.camera import CameraStore, camera_rect, crop_frame
from zipcontrol.mission import Mission


def test_api_receives_only_crop_for_both_current_and_previous_images(tmp_path):
    bridge, runner = executor(tmp_path, False)
    original = bridge.latest_frame()
    original.rgb[:] = (255, 0, 0)  # Android UI outside the camera is bright red.
    original.rgb[20:70, 30:100] = (0, 200, 0)
    bridge.latest_frame = lambda: original
    runner.camera_roi = [30, 20, 70, 50]
    previous = runner.observe("target")
    current = runner.observe("target")
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            status="completed",
            id="test",
            usage=None,
            output=[SimpleNamespace(type="function_call", name="observe", arguments="{}")],
        )

    Astra(SimpleNamespace(responses=SimpleNamespace(create=create))).decide(current, previous)
    content = requests[0]["input"][0]["content"]
    images = [item for item in content if item["type"] == "input_image"]
    assert len(images) == 2
    for item in images:
        image = Image.open(io.BytesIO(base64.b64decode(item["image_url"].split(",")[1])))
        assert image.size == (70, 50)
        pixels = np.asarray(image)
        assert pixels[:, :, 0].max() < 10 and pixels[:, :, 1].min() > 190
    assert json.loads(content[0]["text"])["camera_only"] is True
    assert current.frame.rgb.flags.c_contiguous and not current.frame.rgb.flags.writeable


@pytest.mark.parametrize(
    "roi",
    [None, [0, 0, 5, 50], [-1, 0, 40, 40], [90, 0, 40, 40], [0, 0, float("nan"), 40], [True, 0, 40, 40]],
)
def test_invalid_roi_never_falls_back_to_full_frame(roi):
    with pytest.raises(ValueError):
        crop_frame(Rig().latest_frame(), roi)


def test_fractional_roi_rounds_inward_and_store_matches_geometry(tmp_path):
    assert camera_rect([1.2, 2.8, 40, 50], 120, 100) == (2, 3, 39, 49)
    store = CameraStore(tmp_path)
    store.save("phone", 120, 100, [10, 20, 60, 50])
    assert store.load("phone", 120, 100) == [10, 20, 60, 50]
    assert store.load("other", 120, 100) is None
    assert store.load("phone", 100, 120) is None


def test_provider_rejects_uncropped_observation_before_api_call():
    provider = Astra(SimpleNamespace())
    with pytest.raises(ValueError, match="카메라"):
        provider.decide(SimpleNamespace(metadata={}))


def test_roi_change_discards_inflight_reply_and_previous_comparison(tmp_path):
    entered, deliver = threading.Event(), threading.Event()
    seen = []

    class Delayed:
        def decide(self, obs, previous):
            seen.append((obs, previous))
            if len(seen) == 1:
                entered.set()
                deliver.wait(2)
                return Decision("command_sticks", args(obs))
            return Decision("need_operator", {"reason": "test complete"})

        def close(self):
            deliver.set()

    bridge = LiveFrames()
    mission = Mission(bridge, Delayed(), "goal", live=True, camera_roi=[0, 0, 120, 40], output=tmp_path)
    mission.start()
    assert entered.wait(1)
    mission.set_camera_roi(None)
    assert mission.previous is None
    mission.set_camera_roi([10, 10, 60, 50])
    deliver.set()
    mission.thread.join(3)
    assert not mission.busy and mission.discarded == 1
    assert mission.executor.submissions == 0
    assert seen[1][0].frame.width == 60 and seen[1][1] is None


def test_missing_roi_prevents_mission_start_without_arming(tmp_path):
    bridge = LiveFrames()
    mission = Mission(bridge, None, "goal", live=True, output=tmp_path)
    with pytest.raises(ValueError, match="카메라"):
        mission.start()
    assert not bridge.calls
