import struct

import pytest

from youtube_kit.core.ops._common import image_size


def _jpeg(width: int, height: int, sof: int) -> bytes:
    exif = b"Exif\x00\x00" + b"\xff\xc0\x00\x11\x08\x00\x10\x00\x10"  # an embedded thumbnail's SOF, to skip
    app1 = b"\xff\xe1" + struct.pack(">H", len(exif) + 2) + exif
    dht = b"\xff\xc4" + struct.pack(">H", 4) + b"\x00\x00"
    frame = b"\xff" + bytes([sof]) + struct.pack(">HBHH", 11, 8, height, width) + b"\x01\x01\x11\x00"
    return b"\xff\xd8" + app1 + dht + frame


@pytest.mark.parametrize(
    ("data", "size"),
    [
        (_jpeg(1280, 720, 0xC0), (1280, 720)),
        (_jpeg(900, 900, 0xC2), (900, 900)),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + struct.pack(">II", 640, 480), (640, 480)),
        (b"\xff\xd8\xff\xe1\x00", None),
        (b"RIFF....WEBP", None),
        (b"", None),
    ],
)
def test_image_size(tmp_path, data, size):
    path = tmp_path / "image"
    path.write_bytes(data)
    assert image_size(path) == size
