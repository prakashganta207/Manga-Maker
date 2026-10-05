"""Anime face detection helpers (lbpcascade_animeface + estimated fallback)."""

from PIL import Image

from app.vision import faces
from app.vision.faces import Face, crop_around, detect_faces, estimated_faces, reading_order


def test_cascade_is_available_and_blank_image_has_no_faces():
    assert faces.available()            # opencv-python-headless + the bundled cascade file
    assert detect_faces(Image.new("RGB", (512, 512), "white")) == []


def test_reading_order_rows_then_direction():
    a, b, c = Face(300, 10, 100, 100), Face(10, 20, 100, 100), Face(150, 300, 100, 100)
    assert reading_order([c, a, b]) == [b, a, c]
    assert reading_order([c, a, b], rtl=True) == [a, b, c]


def test_estimated_faces_spread_and_scale_with_shot():
    close = estimated_faces(800, 600, 1, "close-up")
    wide = estimated_faces(800, 600, 2, "wide")
    assert len(close) == 1 and close[0].w > wide[0].w and not close[0].detected
    assert wide[0].center[0] < wide[1].center[0]
    assert estimated_faces(800, 600, 0) == []


def test_crop_around_stays_inside_image():
    img = Image.new("RGB", (300, 300), "white")
    crop = crop_around(img, Face(250, 0, 80, 80))
    assert crop.width <= 300 and crop.height <= 300 and crop.width > 0
