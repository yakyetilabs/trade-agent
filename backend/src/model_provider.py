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


def build_chat_model(model_id: str, *, stream_thoughts: bool = False) -> BaseChatModel:
    """Construct a fresh chat model for ``model_id``, configured for this deployment.

    Built per call, never memoized: a chat model carries per-invocation tool bindings, so
    the agent loop needs a clean instance each run (the Vertex SDK init underneath is the
    singleton). ``temperature=0`` for deterministic, reproducible output - grounding is
    enforced by the system prompt and tools, not by sampling.

    ``stream_thoughts`` turns on Gemini's ``include_thoughts``: 2.5 models think by default
    but omit the thought TEXT from the response, so this is what surfaces it - as streamable
    ``thinking`` content blocks. The agent loop enables it to feed the SSE reasoning stream
    (see :func:`src.streaming.stream_agent_run`); the classifier leaves it off, because a
    structured router has no reasoning to show and shouldn't pay to return it. When off, no
    thinking config is sent, so the call is byte-identical to a plain chat model.
    """
    kwargs: dict[str, object] = {
        "model": model_id,
        "vertexai": True,
        "project": GCP_PROJECT,
        "location": GCP_REGION,
        "temperature": 0.0,
    }
    if stream_thoughts:
        kwargs["include_thoughts"] = True
    return ChatGoogleGenerativeAI(**kwargs)
