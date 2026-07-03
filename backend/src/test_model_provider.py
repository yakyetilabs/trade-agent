"""Unit test for the chat-model provider seam.

The provider class is patched so no real model is constructed (no Vertex SDK init or
credentials); the test locks in the construction contract the seam guarantees.
"""

import pytest

import src.model_provider as model_provider
from src.config import GCP_PROJECT, GCP_REGION


def _capture_ctor(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Patch the provider class so no real model is built, capturing its kwargs."""
    captured: dict[str, object] = {}

    def fake_ctor(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_provider, "ChatGoogleGenerativeAI", fake_ctor)
    return captured


def test_build_chat_model_configures_vertex_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_ctor(monkeypatch)

    model_provider.build_chat_model("gemini-2.5-flash")

    # vertexai=True is load-bearing: Vertex ADC, not the Gemini Developer API key path.
    # Default (no streaming): no thinking config is sent at all - a plain chat model.
    assert captured == {
        "model": "gemini-2.5-flash",
        "vertexai": True,
        "project": GCP_PROJECT,
        "location": GCP_REGION,
        "temperature": 0.0,
    }


def test_build_chat_model_enables_thoughts_when_streaming(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_ctor(monkeypatch)

    model_provider.build_chat_model("gemini-2.5-flash", stream_thoughts=True)

    # stream_thoughts surfaces Gemini's thought TEXT (2.5 thinks by default but omits it);
    # the rest of the deterministic config is unchanged.
    assert captured["include_thoughts"] is True
    assert captured["vertexai"] is True
    assert captured["temperature"] == 0.0
    assert captured["model"] == "gemini-2.5-flash"
