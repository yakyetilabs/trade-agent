"""Vertex AI text-embeddings adapter: a thin LangChain ``Embeddings`` over
google-genai's ``embed_content`` on Vertex AI.

Why the raw call (explicit width + per-call task type) and how it feeds the
single-dense retrieval path: see the Retrieval section (§8) in
``docs/DESIGN_DECISIONS.md``.
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
                # Pin the output width explicitly: the GoogleGenerativeAIEmbeddings
                # wrapper defaults to 3072, which would silently mismatch the fixed
                # Pinecone index.
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

    # Documents and queries must embed under DIFFERENT task types; using one type
    # for both measurably degrades retrieval recall.
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents (RETRIEVAL_DOCUMENT)."""
        return self._embed(list(texts), "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> list[float]:
        """Embed a single search query (RETRIEVAL_QUERY)."""
        return self._embed([text], "RETRIEVAL_QUERY")[0]
