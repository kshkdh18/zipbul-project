import numpy as np
import pytest

from zipcontrol.bridge import Frame
from zipcontrol.gui import map_to_image
from zipcontrol.lab import locate_viewport


def test_letterbox_and_resize_use_video_coordinates():
    assert map_to_image(500, 500, 1000, 1000, 800, 1200) == pytest.approx((400, 600))
    assert map_to_image(50, 500, 1000, 1000, 800, 1200) is None
    assert map_to_image(300, 600, 600, 1200, 800, 1200) == pytest.approx((400, 600))
    assert map_to_image(300, 10, 600, 1200, 800, 1200) is None


def test_phone_browser_chrome_is_excluded_by_fiducials():
    rgb = np.zeros((1000, 600, 3), dtype=np.uint8)
    # CSS viewport width=600 height=800, offset below a 100px browser toolbar.
    for x in (12, 568):
        for y in (112, 868):
            rgb[y : y + 20, x : x + 20] = [255, 0, 255]
    frame = Frame(rgb, 1, 0, 0, 0, 1)
    assert locate_viewport(frame, {"width": 600, "height": 800}) == pytest.approx((0, 100, 1, 1))


def test_missing_diagnostic_markers_never_calibrates_arbitrary_app():
    frame = Frame(np.zeros((1000, 600, 3), dtype=np.uint8), 1, 0, 0, 0, 1)
    with pytest.raises(ValueError):
        locate_viewport(frame, {"width": 600, "height": 800})
