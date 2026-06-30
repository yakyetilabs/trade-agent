"""Vertex AI text-embeddings adapter (google-genai, explicit dimensionality).

A thin LangChain ``Embeddings`` over the unified ``google-genai`` SDK pointed at
Vertex AI. Calling ``embed_content`` directly (instead of a higher-level wrapper)
lets us pin ``output_dimensionality`` explicitly, so the vector width always matches
the fixed Pinecone index, and set the retrieval ``task_type`` per call -
``RETRIEVAL_DOCUMENT`` at ingest, ``RETRIEVAL_QUERY`` at search - for better recall.

The model and dimension come from ``config.py`` (the single source of truth); the
google-genai client is the shared singleton in ``gcp/client.py``.
"""

from google.genai.types import EmbedContentConfig
from langchain_core.embeddings import Embeddings

from src.config import VERTEX_EMBEDDING_DIM, VERTEX_EMBEDDING_MODEL
from src.gcp.client import get_genai_client


class VertexEmbeddings(Embeddings):
    """LangChain ``Embeddings`` backed by google-genai ``embed_content`` on Vertex AI."""

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        response = get_genai_client().models.embed_content(
            model=VERTEX_EMBEDDING_MODEL,
            contents=list(texts),
            config=EmbedContentConfig(
                output_dimensionality=VERTEX_EMBEDDING_DIM,
                task_type=task_type,
            ),
        )
        returned = response.embeddings
        if returned is None or len(returned) != len(texts):
            got = 0 if returned is None else len(returned)
            raise ValueError(f"Expected {len(texts)} embeddings, got {got}")
        vectors: list[list[float]] = []
        for index, embedding in enumerate(returned):
            if embedding.values is None:
                raise ValueError(f"Embedding {index} has no values")
            vectors.append(list(embedding.values))
        return vectors

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents (RETRIEVAL_DOCUMENT)."""
        return self._embed(list(texts), "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query (RETRIEVAL_QUERY)."""
        return self._embed([text], "RETRIEVAL_QUERY")[0]
