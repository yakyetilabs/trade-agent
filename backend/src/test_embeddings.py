"""Unit tests for the Vertex embeddings adapter.

The google-genai client is mocked, so no Vertex call happens. Tests assert the
adapter pins ``output_dimensionality``, sets the retrieval ``task_type`` per call,
passes the configured model, and maps the response into plain float lists.
"""

from dataclasses import dataclass, field
from typing import cast

import pytest
from google.genai.types import EmbedContentConfig

import src.embeddings as embeddings_mod
from src.config import VERTEX_EMBEDDING_DIM, VERTEX_EMBEDDING_MODEL


@dataclass
class _FakeEmbedding:
    values: list[float] | None


@dataclass
class _FakeResponse:
    embeddings: list[_FakeEmbedding] | None


@dataclass
class _FakeModels:
    calls: list[dict[str, object]] = field(default_factory=list)

    def embed_content(
        self, *, model: str, contents: list[str], config: EmbedContentConfig
    ) -> _FakeResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        return _FakeResponse(embeddings=[_FakeEmbedding([0.1, 0.2, 0.3]) for _ in contents])


@dataclass
class _FakeClient:
    models: _FakeModels = field(default_factory=_FakeModels)


def _install_fake(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    client = _FakeClient()
    monkeypatch.setattr(embeddings_mod, "get_genai_client", lambda: client)
    return client


def test_embed_query_pins_dimension_model_and_query_task_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _install_fake(monkeypatch)

    vector = embeddings_mod.VertexEmbeddings().embed_query("duty rate for phones")

    assert vector == [0.1, 0.2, 0.3]
    call = client.models.calls[0]
    assert call["model"] == VERTEX_EMBEDDING_MODEL
    assert call["contents"] == ["duty rate for phones"]
    config = cast("EmbedContentConfig", call["config"])
    assert config.output_dimensionality == VERTEX_EMBEDDING_DIM
    assert config.task_type == "RETRIEVAL_QUERY"


def test_embed_documents_returns_one_vector_per_doc_with_document_task_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _install_fake(monkeypatch)

    vectors = embeddings_mod.VertexEmbeddings().embed_documents(["a", "b"])

    assert vectors == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    config = cast("EmbedContentConfig", client.models.calls[0]["config"])
    assert config.task_type == "RETRIEVAL_DOCUMENT"


def test_embed_raises_when_values_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install_fake(monkeypatch)

    def _no_values(*, model: str, contents: list[str], config: EmbedContentConfig) -> _FakeResponse:
        return _FakeResponse(embeddings=[_FakeEmbedding(None) for _ in contents])

    monkeypatch.setattr(client.models, "embed_content", _no_values)

    with pytest.raises(ValueError, match="no values"):
        embeddings_mod.VertexEmbeddings().embed_query("x")
