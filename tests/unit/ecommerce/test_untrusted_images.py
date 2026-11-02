"""Customer photos are decoded as untrusted input: expected formats, one frame, sane size."""

import pytest
from PIL import Image

import automatron_ecommerce as ecommerce


def save(tmp_path, name, image, **options):
    path = tmp_path / name
    image.save(path, **options)
    return path


@pytest.fixture
def photo():
    return Image.new("RGB", (64, 48), (120, 80, 40))


@pytest.mark.parametrize("name, fmt", [("ok.png", "PNG"), ("ok.jpg", "JPEG"),
                                       ("ok.webp", "WEBP")])
def test_the_formats_a_camera_produces_open(tmp_path, photo, name, fmt):
    with ecommerce.open_untrusted_image(save(tmp_path, name, photo, format=fmt)) as image:
        assert image.size == (64, 48)


@pytest.mark.parametrize("name, fmt", [("doc.tiff", "TIFF"), ("pic.bmp", "BMP"),
                                       ("pic.gif", "GIF")])
def test_other_formats_are_refused_even_behind_an_image_name(tmp_path, photo, name, fmt):
    # Saved under a .png name: the decoder is chosen by content, so the name buys nothing.
    path = save(tmp_path, "looks-like.png", photo, format=fmt)
    with pytest.raises(Image.UnidentifiedImageError):
        ecommerce.open_untrusted_image(path)


def test_an_animated_image_is_refused(tmp_path, photo):
    frames = [photo, Image.new("RGB", (64, 48), (0, 0, 0))]
    path = save(tmp_path, "anim.png", frames[0], format="PNG", save_all=True,
                append_images=frames[1:])
    with pytest.raises(ValueError, match="multi-frame"):
        ecommerce.open_untrusted_image(path)


def test_an_image_claiming_huge_dimensions_is_refused(tmp_path, monkeypatch, photo):
    monkeypatch.setattr(ecommerce, "MAX_UNTRUSTED_IMAGE_PIXELS", 1000)
    with pytest.raises(ValueError, match="out of range"):
        ecommerce.open_untrusted_image(save(tmp_path, "big.png", photo, format="PNG"))


def test_a_refused_photo_is_a_finding_not_a_crash(tmp_path, photo):
    path = save(tmp_path, "claim.png", photo, format="TIFF")
    with pytest.raises(Image.UnidentifiedImageError):
        ecommerce.image_phash(path)
