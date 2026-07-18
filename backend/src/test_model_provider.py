"""Unit test for the chat-model provider seam.

The provider class is patched so no real model is constructed (no Vertex SDK init or
credentials); the test locks in the construction contract the seam guarantees.
"""

import pytest
from pydantic import SecretStr

import src.model_provider as model_provider
from src.config import ANTHROPIC_VERTEX_REGION, GCP_PROJECT, GCP_REGION


def _capture_ctor(
    monkeypatch: pytest.MonkeyPatch, class_name: str = "ChatGoogleGenerativeAI"
) -> dict[str, object]:
    """Patch the provider class so no real model is built, capturing its kwargs."""
    captured: dict[str, object] = {}

    def fake_ctor(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(model_provider, class_name, fake_ctor)
    return captured


def test_build_chat_model_configures_vertex_gemini(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_ctor(monkeypatch)

    model_provider.build_chat_model("gemini-2.5-flash")

    # vertexai=True is load-bearing: Vertex ADC, not the Gemini Developer API key path.
    # Default (no streaming): no thinking config is sent at all - a plain chat model.
    # max_retries=8 stretches 429 backoff past a per-minute quota window (~123s).
    assert captured == {
        "model": "gemini-2.5-flash",
        "vertexai": True,
        "project": GCP_PROJECT,
        "location": GCP_REGION,
        "temperature": 0.0,
        "max_retries": 8,
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


def test_build_chat_model_binds_claude_ids_on_vertex(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _capture_ctor(monkeypatch, "ChatAnthropicVertex")

    model_provider.build_chat_model("claude-haiku-4-5@20251001", stream_thoughts=True)

    # The eval-only Claude arm: temperature pinned to 0 like the Gemini arms, and no
    # thinking config even when the loop asks for streamed thoughts - thinking would
    # force Anthropic's default sampling, and the eval path never streams reasoning.
    assert captured == {
        "project": GCP_PROJECT,
        "location": ANTHROPIC_VERTEX_REGION,
        "model_name": "claude-haiku-4-5@20251001",
        "temperature": 0.0,
        "max_output_tokens": 4096,
    }


def test_build_chat_model_binds_dashed_claude_ids_to_direct_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = _capture_ctor(monkeypatch, "ChatAnthropic")
    monkeypatch.setattr(model_provider, "ANTHROPIC_API_KEY", "test-key")

    model_provider.build_chat_model("claude-haiku-4-5-20251001", stream_thoughts=True)

    # A first-party dashed id selects the direct-API fallback arm: same pinned
    # temperature and output cap as the Vertex form, no thinking config (see above).
    # Keys are the pydantic alias spellings (model_name = model, max_tokens_to_sample
    # = max_tokens); timeout/stop are the explicit class defaults.
    assert captured == {
        "model_name": "claude-haiku-4-5-20251001",
        "api_key": SecretStr("test-key"),
        "temperature": 0.0,
        "max_tokens_to_sample": 4096,
        "timeout": None,
        "stop": None,
    }


def test_build_chat_model_direct_api_refuses_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_provider, "ANTHROPIC_API_KEY", "")

    # Without the key the branch fails loudly at construction - production never sets
    # the key, so the direct-API arm is structurally unreachable there.
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        model_provider.build_chat_model("claude-haiku-4-5-20251001")
