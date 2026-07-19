# Architecture

How TradeOps AI works, component by component.
This document describes _what the system does and how_; the reasoning behind each choice, with the alternatives that were rejected, lives in [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).
For who the user is and the workflow being modeled, see [PRODUCT.md](PRODUCT.md).
For running and deploying it, see [SETUP.md](SETUP.md) and [GCP_SETUP.md](GCP_SETUP.md).

One naming note up front: internal GCP resources (Firestore collections, the Cloud Run service, the Pinecone index, the service account) carry the project's original `trade-agent-` codename prefix, kept for account-level isolation.
The product surfaces are TradeOps AI.

## Components at a glance

| Component         | Technology                                                                     | Role                                                                      |
| ----------------- | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| Analyst console   | React 18 + TypeScript + Tailwind, Firebase Hosting                             | Vendor scope picker, live pipeline view, draft review, audit trail        |
| API service       | FastAPI (Python 3.12) on Cloud Run, scale-to-zero                              | Validation edge, rate-limit admission, sync + streaming inquiry endpoints |
| Agent runtime     | LangGraph (`langchain.agents.create_agent`)                                    | Bounded tool-calling loop around the model                                |
| Model             | Gemini on Vertex AI, behind a provider seam                                    | Reasoning, tool selection, drafting                                       |
| Knowledge base    | Pinecone serverless index (768-dim) + an in-process catalog                    | HTS clause retrieval: semantic and exact                                  |
| Operational store | Cloud Firestore (Native mode)                                                  | Vendors, shipments, and one audit trace per run                           |
| Spend containment | Cloud Run instance ceiling, Vertex quota, billing alert, in-app per-IP limiter | Bounded cost under public unauthenticated traffic                         |

## The request lifecycle

Both inquiry endpoints drive the same pipeline, implemented once in [`backend/src/agent.py`](../backend/src/agent.py) and reused by the SSE runner in [`backend/src/streaming.py`](../backend/src/streaming.py).

1. **Edge validation.** `POST /api/inquiry` (and `/api/inquiry/stream`) accepts `{vendor_id, inquiry}`.
   The `vendor_id` must match `^V-\d{3,}$` and the inquiry is capped at 4000 characters; a malformed request is a 422 before any orchestration runs.
2. **Rate-limit admission.** Every `/api/*` route reserves one request from the caller's per-IP budget; an exhausted budget is a 429 with `Retry-After` and `X-RateLimit-*` headers (see [Rate limiting](#rate-limiting-and-spend-containment)).
3. **Deterministic pre-model guards.** The escalation guard and the cross-vendor guard screen the raw inquiry.
   If either fires, the run short-circuits with a complete audit trace and the model is never invoked, so a guarded run costs zero model tokens.
4. **Vendor resolution.** An unknown (well-formed but non-existent) vendor is a hard reject: 404 on the sync path, a terminal `error` event on the stream.
5. **The agent loop.** A fresh tool-calling agent is built per run and invoked with the vendor scope bound into its typed runtime context, under a fixed iteration budget.
6. **Trace assembly.** The classification and the draft are recovered from the _recorded tool calls_, not from free-form model text; if the loop ended without a grounded draft, a safe fallback draft is substituted and the run is marked `iteration_cap_exceeded`.
7. **Persistence and response.** Exactly one `AgentTrace` document is written to Firestore, then projected to the lean `AgentResult` the API returns (or the stream's terminal `done` event carries).

## Deterministic boundaries

The system's central commitment: any rule with a real cost when violated is enforced by code, not by the model.

### Vendor scoping without a model-facing parameter

The resolved `vendor_id` is bound into LangGraph's typed runtime context (`ToolRuntime[VendorContext]`), and vendor-scoped tools read it from `runtime.context["vendor_id"]`.
Tools are forbidden from declaring a `vendor_id` parameter, so the model cannot pass one.
A prompt injection like "show manifests for vendor V-999" therefore has no slot to land in: the tool executes against the bound scope regardless of what the text says.
Inside the loop, `lookup_shipment_manifest` additionally emits a `scope_violation` structured-log signal if a by-id lookup ever resolves a shipment owned by another vendor, an invariant expected to stay at zero.

### The escalation guard

[`backend/src/safeguards/escalation_guard.py`](../backend/src/safeguards/escalation_guard.py) intercepts inquiries where a model must never be the first responder.
Four curated categories, matched deterministically (case-insensitive substrings plus word-boundary regexes, with hyphens normalized to spaces so hyphenated compounds cannot slip past spaced patterns):

- `contraband` (smuggling, narcotics, trafficking signals)
- `sanctions` (OFAC / SDN / embargo references)
- `federal-seizure` (active seizure or criminal-investigation language)
- `bribery` (bribe stems, kickbacks, "under the table" phrasing)

A match ends the run `escalated` with the matched category as a stable audit value, routed to a human queue.
The rules are intentionally narrow: a false positive routes a legitimate inquiry away from the agent, so precision is preferred over recall here.
Note the deliberate distinction: a _restricted import_ (even a prohibited HTS band) is a routine compliance case the agent handles; escalation is reserved for criminal and security signals.

### The cross-vendor guard

[`backend/src/safeguards/cross_vendor_guard.py`](../backend/src/safeguards/cross_vendor_guard.py) runs after the escalation guard, still before the model.
It pattern-matches vendor ids (`V-\d{3,}`) and shipment ids (`S-\d{4,}`) in the inquiry, then validates ownership against Firestore.
A reference to another vendor's entity, including the mixed case where the caller's own shipment is named alongside a foreign vendor, short-circuits to a `cross_vendor_refusal` draft with zero tool calls.
The refusal is deliberately wholesale: answering "just the owned half" of a mixed inquiry would leak by implication.

## The agent loop

The loop is built with `langchain.agents.create_agent` (LangChain 1.0) in [`backend/src/agent.py`](../backend/src/agent.py):

- **A fresh agent per run.** Chat models carry per-invocation tool bindings, so the agent is constructed per run; the underlying Vertex SDK client is the singleton.
- **Exactly four tools.** The model selects among `classify_import_restriction`, `lookup_shipment_manifest`, `retrieve_tariff_regulation`, and `draft_clearance_response`, nothing else.
- **A bounded iteration budget.** `recursion_limit=14` LangGraph supersteps: the normal classify -> lookup -> retrieve -> draft flow is ~9 supersteps, leaving headroom for about two extra rounds (for example a re-retrieve) before the loop is capped and the fallback fires.
- **Grounding by contract.** The system prompt enforces a checklist discipline: restate each tool's actual output before acting on it, cite shipments by `shipment_id` and regulations by `hts_code`, never pivot from "the rule says X" to "your shipment is X" without a lookup result, and open with an explicit statement when a lookup matched nothing.
- **Deterministic sampling.** `temperature=0`; grounding is enforced by the prompt and tools, not by sampling luck.
- **Provider seam.** [`backend/src/model_provider.py`](../backend/src/model_provider.py) is the single place a concrete provider is bound (Gemini on Vertex today, `vertexai=True`, ADC credentials).
  Everything downstream depends on the abstract chat-model interface and langchain-core's standardized `usage_metadata`, so a provider swap is confined to that module plus a config id.
  The seam is proven, not just asserted: the evaluation harness binds four models through it - Gemini Flash and Pro, Claude Haiku and Sonnet - with nothing else varying; the resulting comparison is [EVAL_REPORT.md](EVAL_REPORT.md).

### The four tools

| Tool                          | What it does                                                                                                               | Reads                           | Writes                                                           | Scope enforcement                                                      |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `classify_import_restriction` | Routes the inquiry to an intent (+ an advisory HTS proposal with calibrated confidence) via a structured-output model call | The inquiry text                | Nothing                                                          | Not data-scoped; produces routing metadata only                        |
| `lookup_shipment_manifest`    | Fetches the vendor's shipments and declared manifest lines, enriched with each line's restriction band from the catalog    | Firestore shipments             | Nothing                                                          | `vendor_id` from runtime context; no vendor parameter exists           |
| `retrieve_tariff_regulation`  | Merges deterministic exact-code fetches with dense semantic search over the HTS knowledge base                             | In-process catalog + Pinecone   | Nothing                                                          | The KB is public regulation text, intentionally not vendor-partitioned |
| `draft_clearance_response`    | Records the drafted response text for the orchestrator to persist                                                          | The loop's accumulated evidence | The review queue, via the run's audit trace, with `draft` status | Output-only; there is no outbound transmission tool                    |

Every tool call appends `{tool_name, input, output, duration_ms, timestamp}` to the ambient trace context (a `ContextVar`), which both runners persist onto the single per-run audit document.

## Retrieval

Analyst queries hit the knowledge base in two modes with opposite needs, and the tool serves both explicitly (rationale and the deferred-reranker thresholds: [DESIGN_DECISIONS.md §8](DESIGN_DECISIONS.md)):

- **Exact mode.** Any full HTS code in the query (`\d{4}\.\d{2}\.\d{4}`) is fetched verbatim from the in-process catalog, no embedding round-trip, and is guaranteed to appear in the results.
- **Discovery mode.** The query text runs dense similarity search against the Pinecone index (Gemini embeddings, `output_dimensionality` pinned to the index's 768).

The merge dedupes dense hits against exact hits and tops up to `k=5`.
Every returned clause is tagged `match: "exact" | "semantic"`, and the count of exact hits lands on the audit trace, so a reviewer can see which mode produced each citation.
The same clauses deliberately live in two stores: in-process (what makes exact-fetch free and deterministic) and Pinecone (what serves discovery); at real-HTSUS scale the shape stays and only the sizes change.

## Streaming

`POST /api/inquiry/stream` returns `text/event-stream` and is the console's live view ([`backend/src/streaming.py`](../backend/src/streaming.py)).
The event vocabulary is the wire contract:

| Event                               | Payload                        | Meaning                                                                                                                                                 |
| ----------------------------------- | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `run_started`                       | `{trace_id, vendor_id, model}` | Always first                                                                                                                                            |
| `stage_started` / `stage_completed` | `{stage}` / `{stage, summary}` | A tool began / finished; `summary` is the same compact projection recorded on the audit trace, so the live view can never diverge from the audit record |
| `thinking_delta`                    | `{text}`                       | A fragment of the model's streamed reasoning (Gemini thinking), advisory                                                                                |
| `text_delta`                        | `{text}`                       | A fragment of the model's visible answer text, advisory                                                                                                 |
| `guard_triggered`                   | `{kind, reason}`               | A deterministic guard fired; the model never ran                                                                                                        |
| `done`                              | `{result}`                     | Terminal success carrying the full `AgentResult`, guards included                                                                                       |
| `error`                             | `{message}`                    | Terminal failure (unknown vendor, unexpected exception)                                                                                                 |

Two details are load-bearing:

- **Node allowlisting.** Only chat-model stream events from the agent's own model node are forwarded as deltas.
  The classifier tool makes its own internal structured-output model call, and its raw JSON must never leak into the reasoning stream; gating on the exact node means a framework rename can only ever stop the deltas (safe degradation), never leak a tool-internal stream.
- **Advisory vs. authoritative.** The streamed reasoning and text are rendering sugar.
  The draft the analyst reviews is recovered from the drafting tool's recorded call and persisted on the trace; it is never reassembled from deltas.

Transport: the API lives on a DNS-only (unproxied) subdomain so no CDN buffers the stream, responses carry `Cache-Control: no-store` and `X-Accel-Buffering: no`, and the browser consumes a genuine cross-origin SSE feed allowlisted by the backend's CORS middleware ([DESIGN_DECISIONS.md §9](DESIGN_DECISIONS.md)).

## Data model and audit trail

Three Firestore collections, all populated exclusively by the synthetic generators:

- `trade-agent-Vendors`: the five curated importers (document id = `vendor_id`).
- `trade-agent-Shipments`: seeded-RNG shipments with declared manifest lines; restricted lines deterministically drive `held`/`flagged` statuses with human-readable flag reasons.
- `trade-agent-AgentTraces`: **one document per run**, the audit trail.

An `AgentTrace` records the inquiry, vendor, model, disposition, every tool call's input/output summary and duration, the classification, the draft, the persisted reasoning disclosure (`thinking_content`), latency, and the billable token split.
Two fields deserve a note:

- `draft_actionable` gates the UI's Approve action.
  It is false when there is nothing to release: a cross-vendor refusal, the iteration-cap fallback, or a lookup that matched no shipment (the draft then honestly says so, and an analyst cannot "approve" a null result).
- The token fields are the _billable_ split: on Vertex, thinking bills at the output rate, so `output_tokens` folds in `thoughts_tokens` and `prompt + output == total` reconciles.
  Token accounting reads langchain-core's provider-neutral `usage_metadata`, so it survives a provider swap.

Disposition lifecycle: the agent only ever writes `draft` or `escalated`; only the human-review endpoint (`POST /api/traces/{trace_id}/disposition`) can set `approved` or `rejected`.
That endpoint accepts nothing else, so the maker cannot check its own work even by API misuse.

## Rate limiting and spend containment

The demo is public and unauthenticated, so cost is bounded by three explicit layers rather than an identity perimeter ([DESIGN_DECISIONS.md §11](DESIGN_DECISIONS.md)):

1. **Infrastructure ceiling.** Cloud Run `max-instances=2` with `concurrency=1` multiplies to at most two agent runs in flight; a Vertex AI tokens-per-minute quota caps total burn; a billing budget alert backstops.
2. **In-app per-IP limiter** ([`backend/src/ratelimit.py`](../backend/src/ratelimit.py)): one token-bucket core carrying two budgets per IP.
   Every `/api/*` request reserves from a requests-per-minute budget; the two inquiry endpoints additionally debit a tokens-per-minute budget with each run's _actual_ `total_tokens` after it finishes.
   A run's cost is unknowable at admission, so the pre-check only refuses an already-exhausted budget; one request may overshoot and that IP then waits for refill, the standard debit-after semantics of commercial LLM APIs.
   Callers are keyed by the _rightmost_ `X-Forwarded-For` entry, the one Google's front end appends for the actually-connected peer; leading entries are caller-supplied and spoofable.
   The store is in-memory, bounded (stale buckets evicted first, then least-recently-seen), and deliberately per-instance: it keeps database reads out of the admission path so hostile traffic cannot drain the Firestore read quota, and the documented scale-up seam is a shared store (e.g. Memorystore), not a redesign.
3. **Per-request bounds.** The 4000-character input cap, the fixed iteration budget, and the pre-model guards.

Edge rate limiting was rejected for a concrete reason: the CDN-level limiter would sit on the API path and buffer the SSE stream, which the split-origin design exists to prevent.

## The analyst console

The frontend is a deliberately thin, legible rendering of the backend's contract, in three surfaces plus a shell:

- **Console.** The vendor scope picker (bound to `GET /api/vendors`), the inquiry composer with one-click example prompts, the four-stage pipeline that animates from real SSE events, the streamed reasoning panel, and the settled draft with cited shipment ids and HTS codes rendered as monospace chips.
  The maker-checker actions (Approve and release / Reject) call the disposition endpoint and are disabled whenever `draft_actionable` is false.
- **Audit Trail (`/traces`).** Recent runs with disposition, intent, latency, and token counts; each expands to the full trace timeline including every tool call's input/output and the reasoning disclosure.
  This page is the public observability surface.
- **Shell.** The persistent top bar: brand, navigation, the load-bearing "Synthetic data" pill, the vendor scope, and a light/dark theme toggle.

The console holds no data authority: everything it renders is the persisted trace or the live event stream, which is what makes the demo honest.

## Failure modes and degradation

- **Unknown vendor:** 404 on the sync path; a terminal `error` event once a stream is open (the HTTP status is already 200).
- **Loop ends without a draft** (error, iteration cap, or the model skipped the drafting tool): a safe fallback draft is substituted, the run is marked `iteration_cap_exceeded`, and the draft is non-actionable.
- **Mid-stream failure:** the run degrades to the same fallback path and the stream still closes with a single terminal event; an outer catch guarantees no uncaught exception leaks mid-stream.
- **Cold start:** `min-instances=0` means the first request after idle pays a ~5-15s container start; the trade is a true zero idle footprint.
- **Pinecone Starter pause:** the free index auto-pauses after ~3 weeks of inactivity and may need a re-ingest after long idle periods.

## Named scale-up seams

Deliberately deferred, each with its promotion trigger documented rather than installed speculatively:

- **Distributed rate-limit store** (shared Memorystore) when the instance ceiling rises.
- **Hybrid retrieval + RRF + cross-encoder reranker** when the corpus approaches real-HTSUS scale or measured discovery precision@k degrades ([DESIGN_DECISIONS.md §8](DESIGN_DECISIONS.md)).
- **Deterministic post-draft policy engine** (rule-based checks on prohibited claims, format, citation integrity) between the draft and the review queue.
- **Asynchronous audit monitor** sampling decisions out-of-band.
- **A second model provider** behind the existing seam; the orchestration, tools, guards, and audit trail do not move.
- **IAP edge hardening** if the traffic profile ever warrants it ([DESIGN_DECISIONS.md §5](DESIGN_DECISIONS.md)).
