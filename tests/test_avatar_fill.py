"""The marker behind "fill template/missing avatars only": AI portraits are
tagged with a PNG text marker; templates/missing files aren't, so a fill pass
regenerates exactly the untagged ones (and the good AI avatars are left alone).

Existing avatars are otherwise indistinguishable — same 512x512 size, both
unique-looking painted headshots — so no image heuristic separates them; the
marker is the reliable discriminator.
"""

import pytest

from utils.avatar_generator import _avatar_is_ai, _save_ai_png

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def test_saved_ai_avatar_is_tagged(tmp_path):
    out = tmp_path / "p.png"
    _save_ai_png(Image.new("RGB", (512, 512), (10, 20, 30)), out)
    assert out.exists()
    assert _avatar_is_ai(out) is True


def test_plain_png_is_not_ai(tmp_path):
    # A template/other PNG saved without the marker reads as not-AI.
    out = tmp_path / "tmpl.png"
    Image.new("RGB", (512, 512), (0, 0, 0)).save(out, format="PNG")
    assert _avatar_is_ai(out) is False


def test_missing_file_is_not_ai(tmp_path):
    assert _avatar_is_ai(tmp_path / "nope.png") is False
