"""Vertex image response decoding + host routing.

The old Imagen ``:predict`` models were retired; the default is now the
Gemini-native image model ("Nano Banana") on the ``global`` endpoint via
``generateContent``. These cover both response shapes without hitting the API.
"""

import base64

import utils.vertex_image as vi


def test_api_host_global_vs_regional(monkeypatch):
    monkeypatch.setattr(vi, "_LOCATION", "global")
    assert vi._api_host() == "aiplatform.googleapis.com"
    monkeypatch.setattr(vi, "_LOCATION", "us-central1")
    assert vi._api_host() == "us-central1-aiplatform.googleapis.com"


def test_decode_gemini_image():
    raw = b"\x89PNG\r\n\x1a\nfake-image-bytes"
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "here you go"},
                        {"inlineData": {"mimeType": "image/png",
                                        "data": base64.b64encode(raw).decode()}},
                    ]
                },
                "finishReason": "STOP",
            }
        ]
    }
    assert vi._decode_image(payload, is_imagen=False) == raw


def test_decode_gemini_snake_case_inline_data():
    raw = b"\x89PNGxyz"
    payload = {
        "candidates": [
            {"content": {"parts": [{"inline_data": {"data": base64.b64encode(raw).decode()}}]}}
        ]
    }
    assert vi._decode_image(payload, is_imagen=False) == raw


def test_decode_gemini_no_image_raises():
    payload = {"candidates": [{"content": {"parts": [{"text": "blocked"}]},
                               "finishReason": "SAFETY"}]}
    try:
        vi._decode_image(payload, is_imagen=False)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "SAFETY" in str(exc)


def test_decode_imagen_predict_shape():
    raw = b"\x89PNGimagen"
    payload = {"predictions": [{"bytesBase64Encoded": base64.b64encode(raw).decode()}]}
    assert vi._decode_image(payload, is_imagen=True) == raw
