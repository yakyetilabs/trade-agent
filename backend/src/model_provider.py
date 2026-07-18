"""The chat-model provider seam - the single place a concrete LLM provider is bound.

Everything downstream depends only on the abstract ``BaseChatModel`` this returns and on
langchain-core's standardized ``usage_metadata``, never on a provider class: the agent
loop (``src/agent.py``), the classifier (``src/tools/classify_import_restriction.py``),
and the streaming runner all go through here. So swapping the model - or adding a second
provider (e.g. AWS Bedrock) - is a change confined to this module plus a model id in
``config.py``; the orchestration, tools, safeguards, and audit trail do not move.

The serving path is Gemini on Vertex AI (via ``langchain-google-genai`` with
``vertexai=True``, ADC credentials, colocated with Firestore and the embeddings call).
Claude binds ``claude-*`` ids and is exercised only through the eval runner's
``model_id`` seam - the model-comparison arms behind the eval report; the production
model id in ``config.py`` stays Gemini. The Claude id's format picks its platform, so a
report row's ``model_id`` is self-describing: a Vertex snapshot id
(``claude-haiku-4-5@20251001``, ADC, no key) binds ``ChatAnthropicVertex``, while the
same snapshot's first-party dashed id (``claude-haiku-4-5-20251001``) binds
``ChatAnthropic`` against the direct Anthropic API - the sanctioned fallback for filling
eval rows while the Anthropic-on-Vertex quota grant is pending. It requires
``ANTHROPIC_API_KEY`` and is structurally unreachable in production, which sets no key.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_google_vertexai.model_garden import ChatAnthropicVertex
from pydantic import SecretStr

from src.config import ANTHROPIC_API_KEY, ANTHROPIC_VERTEX_REGION, GCP_PROJECT, GCP_REGION


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

    ``claude-*`` ids bind Claude instead - the eval-only comparison arms, on Vertex for
    ``@``-snapshot ids and on the direct Anthropic API for first-party dashed ids (same
    snapshot weights; the id records which platform served the row). Both Claude
    bindings pin ``temperature=0`` and ``max_tokens=4096`` to match the Gemini arms so
    the comparison isolates the model, which is also why extended thinking stays OFF
    here: enabling it would force the Anthropic default sampling (thinking rejects
    pinned temperature), and the eval path never streams reasoning - ``stream_thoughts``
    is deliberately ignored on these branches until Claude returns to the serving path.
    """
    if model_id.startswith("claude-"):
        if "@" in model_id:
            return ChatAnthropicVertex(
                project=GCP_PROJECT,
                location=ANTHROPIC_VERTEX_REGION,
                model_name=model_id,
                temperature=0.0,
                max_output_tokens=4096,
            )
        if not ANTHROPIC_API_KEY:
            raise ValueError(
                f"model id {model_id!r} selects the direct Anthropic API binding, which"
                " needs ANTHROPIC_API_KEY set; Vertex snapshot ids carry an '@' instead"
            )
        # Alias spellings (model_name/max_tokens_to_sample/timeout/stop are pydantic
        # aliases of model/max_tokens/default_request_timeout/stop_sequences) - the
        # form pyright validates; None values are the class defaults, made explicit.
        return ChatAnthropic(
            model_name=model_id,
            api_key=SecretStr(ANTHROPIC_API_KEY),
            temperature=0.0,
            max_tokens_to_sample=4096,
            timeout=None,
            stop=None,
        )
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
