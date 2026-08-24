"""The PNG-size discriminator behind "fill template/missing avatars only":
real AI avatars are saved 512x512, template/failed fallbacks are 1024x1024."""

import struct

from utils.avatar_generator import _png_size


def _png_header(width: int, height: int) -> bytes:
    # 8-byte signature + IHDR length(13) + "IHDR" + width + height (big-endian).
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">I", width)
        + struct.pack(">I", height)
    )


def test_png_size_reads_dimensions(tmp_path):
    ai = tmp_path / "ai.png"
    ai.write_bytes(_png_header(512, 512) + b"\x00" * 32)
    tmpl = tmp_path / "tmpl.png"
    tmpl.write_bytes(_png_header(1024, 1024) + b"\x00" * 32)

    assert _png_size(ai) == (512, 512)
    assert _png_size(tmpl) == (1024, 1024)
    # The rule the batch uses: only a real AI avatar is 512x512.
    assert _png_size(ai) == (512, 512)
    assert _png_size(tmpl) != (512, 512)


def test_png_size_missing_or_not_png(tmp_path):
    assert _png_size(tmp_path / "nope.png") is None
    junk = tmp_path / "junk.png"
    junk.write_bytes(b"not a png at all")
    assert _png_size(junk) is None
