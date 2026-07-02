"""The chat-model provider seam - the single place a concrete LLM provider is bound.

Everything downstream depends only on the abstract ``BaseChatModel`` this returns and on
langchain-core's standardized ``usage_metadata``, never on a provider class: the agent
loop (``src/agent.py``), the classifier (``src/tools/classify_import_restriction.py``),
and the streaming runner all go through here. So swapping the model - or adding a second
provider (e.g. AWS Bedrock) - is a change confined to this module plus a model id in
``config.py``; the orchestration, tools, safeguards, and audit trail do not move.

Today that provider is Gemini on Vertex AI (via ``langchain-google-genai`` with
``vertexai=True`` - Vertex ADC credentials, no API key, colocated with Firestore and the
embeddings call). A Claude-on-Vertex binding lived here previously (git ``fdaf3a1``) and
slots back in as a second branch when its Vertex quota clears.
"""

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI

from src.config import GCP_PROJECT, GCP_REGION


def build_chat_model(model_id: str) -> BaseChatModel:
    """Construct a fresh chat model for ``model_id``, configured for this deployment.

    Built per call, never memoized: a chat model carries per-invocation tool bindings, so
    the agent loop needs a clean instance each run (the Vertex SDK init underneath is the
    singleton). ``temperature=0`` for deterministic, reproducible output - grounding is
    enforced by the system prompt and tools, not by sampling.
    """
    return ChatGoogleGenerativeAI(
        model=model_id,
        vertexai=True,
        project=GCP_PROJECT,
        location=GCP_REGION,
        temperature=0.0,
    )
