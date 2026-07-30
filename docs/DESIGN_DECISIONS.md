# Design Decisions

The architecture in this repository is not improvised. Each design decision answers a specific governance question for putting an LLM inside a regulated workflow: how the agent is defined and bounded, where to build versus buy versus stack at each layer, how model confidence maps to autonomy, which safeguards ship versus stay documented, and how every decision stays auditable against the code.
Each section below names the decision, the alternative I considered, the principle that guided the call, and the code location where the decision lives. If I claim something about the architecture, you can audit it against a file.

The point of this page is to make one thing visible: this project is not a generic framework demo with an arbitrary backend. It is a specific set of architectural commitments made under a specific governance philosophy. The same skeleton would re-skin to almost any regulated-industry agentic workflow where data boundaries and audit trails are non-negotiable.

### The transferable spine

That last claim should be auditable, not rhetorical, so here it is made concrete.
The rows below are the operating model of a regulated-enterprise compliance or claims desk, each mapped to the file where it lives in this repo, then re-skinned to claims adjudication.
The nouns change; the spine does not.

| Spine element | This build (US trade compliance) | Claims adjudication |
| --- | --- | --- |
| Authorized user | Trade compliance analyst | Claims adjuster / examiner |
| Entitlement scope | Vendor scope validated at the edge and bound server-side into the run (`VendorContext`, cross-vendor guard; see §11) | Assigned claimants / book of business |
| Work item (a case) | Held or flagged shipment | Pended or flagged claim |
| Scoped evidence | The vendor's shipment manifests (`lookup_shipment_manifest`) | Claim line items and coverage |
| Governing rule | HTSUS clause from the KB (`retrieve_tariff_regulation`) | Policy provision / coverage clause |
| Deterministic pre-screen | Escalation + cross-vendor guards (`safeguards/`) | Fraud / SIU referral + claimant segregation |
| Maker (prepares) | Agent drafts the clearance response (`draft_clearance_response`) | Agent drafts the determination |
| Checker (approves; same human) | Analyst reviews and releases | Examiner reviews and issues |
| Immutable audit | One `AgentTrace` per case | Claim decision log / file |
| Autonomy posture | Supervised, gated path to delegated (§7) | Supervised |

The code is deliberately specific to trade compliance.
The transferable asset is the design philosophy the rows share: deterministic boundaries resolved outside the model, maker-checker with the agent as the maker, evidence-grounded output, an immutable per-case audit record, and a supervised autonomy posture with an evidence-gated path to more.
The trade skin is proof the philosophy was built, not merely described.

---

## 1. The Agent Definition I'm Working From

A working definition disciplines everything downstream. The one I'm using:

> _An agentic AI system uses an LLM as the reasoning brain to autonomously achieve a given task by executing tools, reviewing the execution output, and deciding whether to iterate or present the final response - within boundaries the surrounding system enforces._

The boundary clause is the load-bearing part. The unbounded version of this definition ("...without human intervention") is what people usually say. The bounded version is what production looks like. Every safeguard in this codebase exists because the unbounded version is the wrong design target for an enterprise global supply chain or customs clearance workflow.

This definition also rules things out. A linear RAG pipeline that retrieves text chunks and synthesizes an answer is **not** an agent under this definition - there is no decision to iterate, no tool selection, no execution review. That distinction matters because much of what is shipped as "agentic AI" today is a RAG wrapper with a chat interface. This project is deliberately not that.

**See:** [`backend/src/agent.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/agent.py) - the agent loop's iteration and routing logic.

---

## 2. The Five Building Blocks

**Perception.** The agent observes three structured input streams: the user's natural-language inquiry, a `vendor_id` the analyst selects from the vendor picker (pattern-validated server-side and bound into the run context, never trusted as free text), and retrieved Harmonized Tariff Schedule (HTS) or custom policy clauses from the Pinecone index. It does **not** observe raw HTTP requests or unscoped global vendor records. By the time inputs reach the model, they have already been filtered through deterministic code. _(See [`backend/src/app.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/app.py) and [`backend/src/safeguards/`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/safeguards).)_

**Action.** The agent is authorized to invoke exactly four tools: `classify_import_restriction`, `lookup_shipment_manifest`, `retrieve_tariff_regulation`, and `draft_clearance_response`. Each tool's blast radius is tightly bounded. `lookup_shipment_manifest` is read-only and vendor-scoped. `draft_clearance_response` writes to an internal trace review queue, not to an outbound EDI port or custom system. The agent has no tool that alters container flags, pays customs duties, or accesses another vendor's bills of lading. _(See [`backend/src/tools/`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/tools/).)_

**Planning.** Task decomposition, not unchecked chain-of-thought. The agent decomposes every compliance inquiry into a structured sequence - classify, lookup, retrieve, draft - with each step verifiable in the trace log. I rejected free-form, unconstrained planning because in an auditable corporate workflow, the audit trail is the product. A model that reasons in opaque chains and produces correct answers is less valuable than a model that follows a known sequence and produces deterministic, auditable ones. _(See [`backend/src/agent.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/agent.py).)_

**Memory.** Three explicit layers, with strict scope boundaries:

- **In-session:** The current conversation context, discarded at session end.
- **Per-vendor retrieval scope:** The resolved `vendor_id` constrains every tool call. There is no shared embedding store that mixes trade secrets across completely different vendor accounts.
- **Procedural:** None in this MVP. Reusable response templates are deferred - see Section 10.

**Safety.** Safety is architected into the surrounding system, not the model. The model is never trusted to enforce a constraint that has a real cost when violated. Section 5 details the layers. The single most important commitment: the agent cannot transmit anything externally. Outbound clearance submission is always a human action.

---

## 3. Build / Buy / Stack Posture

Every agentic stack is a choice at three layers - model, framework, platform - with three options at each: build, buy, or stack a combination. The posture I committed to for this project:

**Model layer: Buy.** Gemini 2.5 Flash (`gemini-2.5-flash`, GA) via Vertex AI as the primary model for rapid tool calling and generation speed, with Gemini 2.5 Pro (`gemini-2.5-pro`, GA) as the evaluation comparison. I rejected building (computationally absurd at portfolio scale) and rejected complex multi-provider abstraction layers. Vertex AI gives me enterprise terms (zero data retention, regional data residency) without bespoke compliance overhead.

**Framework layer: Stack.** LangGraph (Python) as the orchestration runtime, with custom middleware for the parts standard libraries don't handle: vendor resolution, deterministic pre-model guards, and structured trace logging. I rejected a fully managed, black-box agent platform because it abstracts away the exact governance layers I want to control - vendor scoping, tool permissioning, and deterministic pre-model checks.

**Platform layer: Stack.** Off-the-shelf infrastructure for non-differentiating concerns - Cloud Run for serverless execution, Pinecone for vector search, Google Cloud Firestore for state tracking, and GCP Cloud Logging for infrastructure telemetry. Custom code for the control plane: the agent loop, the tool implementations, the scoping dependencies, and the trace store. The general principle: **buy the commodity, build the moat.** For an enterprise deployment of this same workflow, the moat is the governance layer, not the raw foundation model.

---

## 4. The Threshold Map

The threshold map is the mechanism for translating model confidence into autonomy. For each decision the agent makes, there are three bands: act autonomously, escalate to human, or refuse entirely. The bands are a deliberate choice made by the system designer.

For this workflow, the three decision types and their thresholds:

| Decision                               | Acts autonomously when                                                                                                                           | Escalates when                                                                        | Refuses / human-originates when                                                                                            |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **Inquiry classification & routing**   | Classifier confidence is $\ge 0.85$ _and_ inquiry type is in the supported set (tariff lookup, manifest flag resolution, clearance requirements) | Confidence is between $0.60$ and $0.84$                                               | Confidence is $< 0.60$, _or_ inquiry involves an existing legal dispute, severe tariff fraud flags, or contraband language |
| **Drafted clearance response content** | Response cleanly cites a retrieved HTS policy chunk by ID _and_ contains no corporate liability commitments                                      | Response includes inferred international trade assertions or delivery time guarantees | Response involves raw regulatory fine determinations, or formal legal customs appeals decisions                            |
| **Outbound delivery**                  | **Never.**                                                                                                                                       | N/A                                                                                   | Always. A human US trade compliance analyst reviews and sends every single response in the MVP.                 |

The third row is the architectural commitment that matters most. The agent's autonomy on outbound delivery is zero, by design. This is a hard-coded constraint that completely bypasses model discretion.

---

## 5. Four Safeguard Layers - and Which Two Are Shipped

The safeguard model has four layers: input filtering, deterministic policy checks, human-in-the-loop handoff, and an external audit monitor. The honest scope of this MVP is two layers fully implemented and two layers documented but not built.

**Shipped: Deterministic vendor scoping.** The `vendor_id` the analyst selects is pattern-validated at the API edge (a malformed id is a 422 before any orchestration), then bound into every tool through LangGraph's typed runtime context (`ToolRuntime`), never as a model-facing argument: the tool signature has no vendor parameter, so a prompt injection like "show me shipping logs for vendor 9999" has no slot to land in. A companion pre-model guard (below) refuses inquiries that reference another vendor's entities by ID. _(See [`backend/src/app.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/app.py) and [`backend/src/tools/lookup_shipment_manifest.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/tools/lookup_shipment_manifest.py).)_
_Amended by the public-demo pivot (§11): an identity layer previously fronted this scoping - a Firebase-verified email checked against an in-memory allowlist that also carried each analyst's authorized vendor set (`security.py`). That layer was removed when the demo went public; the vendor binding and the guards below are auth-independent and unchanged._

**Considered: edge authorization via Cloud Run IAP.** Identity-Aware Proxy can now be enabled directly on Cloud Run - no load balancer, no added cost - and would reject unauthorized callers at Google's edge before the container runs. I evaluated it and kept the app-layer boundary deliberately: it kept the public frontend viewable rather than behind a Google login wall, and done securely IAP still requires verifying the signed assertion (the raw `run.app` URL can otherwise be hit directly). The credit/quota-drain risk - the real threat for a metered-AI demo - is handled in-app before any Vertex or Firestore call (originally the in-memory allowlist; since the §11 pivot, the in-memory per-IP rate limiter plus the infra spend ceilings); IAP's remaining advantage is DoS hygiene on the thin outer layer, which this demo's traffic profile does not need. IAP remains the obvious production-hardening step if that changes.

**Shipped: Draft-only output with mandatory human handoff.** There is no tool that sends messages or changes manifest data. The `draft_clearance_response` tool writes to a database review queue (`trade-agent-AgentTraces` inside Firestore). A human reviewer must explicitly read, approve, or edit the draft in the UI. _(See [`backend/src/tools/draft_clearance_response.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/tools/draft_clearance_response.py).)_

**Documented, not shipped: Deterministic policy engine.** A production version would intercept every draft and run rule-based regex checks - looking for prohibited trade claims, format validation, and citation integrity - before the draft hits the human review queue. The MVP currently relies on system-prompt instruction sets for these checks.

**Documented, not shipped: External audit monitor.** A second, asynchronous LLM-based reviewer that samples agent decisions out-of-band and flags compliance anomalies.

**Shipped: Deterministic cross-vendor reference guard.** A second pre-model guard (`detectCrossVendorReference` in [`backend/src/safeguards/cross_vendor_guard.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/safeguards/cross_vendor_guard.py)) runs after the escalation guard but before the main agent loop. It matches vendor patterns (`V-\d{3,}`) and bill of lading/shipment tracking IDs (`S-\d{4,}`) in the text, and validates ownership against Firestore. If a referenced ID belongs to a different vendor ecosystem, the guard short-circuits with an immediate `cross_vendor_refusal` draft and the LLM is never invoked.

**Shipped: Iteration-cap fallback.** If the agent loop completes without producing a valid draft (e.g., the model's iteration budget is exhausted on a particularly complex structural manifest discrepancy), the system returns a graceful degradation response asking the user to refine their prompt. This catches both application-level model execution limits and LangGraph's internal graph-traversal safety bounds, rendering a clean fallback in the UI rather than throwing an unhandled 500 error.

---

## 6. AgentOps: Measurement as Architecture

Continuous evaluation as a first-class deployment concern separates AgentOps from basic infrastructure monitoring. Three commitments in this codebase:

- **Real-time metric 1: Confidence-band approval rate.** For every classification, the agent's confidence score is logged alongside the eventual human review outcome (approve / edit / reject). A regression in the $0.95+$ band is a critical signal-it means the agent is confidently wrong about a custom regulation.
- **Real-time metric 2: Vendor-scope integrity.** Two scope signals are emitted and expected to stay at zero. Before the model runs, the cross-vendor guard refuses any inquiry that references another vendor's entities by ID (`cross_vendor_refusal`). Inside the loop, `lookup_shipment_manifest` records `scope_violation=true` with the `attempted_vendor_id` if a by-id lookup ever resolves a shipment owned by another vendor. Both are greppable Cloud Logging events; a non-zero rate is a critical alert. (The pre-pivot 403 `scope_violation` signal at the API boundary went away with the identity layer; see §11.)
- **Periodic review: Eval suite against the deployed agent.** A curated evaluation dataset sitting at `backend/eval/cases.json` exercises the system across 7 capability categories - happy path (the full grounded pipeline, including grounding traps), exact HTS fetch (the deterministic retrieval mode), semantic discovery retrieval (prose only, no code supplied), unsupported-response detection (a plausible code absent from the knowledge base must be reported as not on record, not approximated), escalation triggers, scope violations (the two pre-model guards), and adversarial prompt injection (scope-escape attempts contained by the guards when they name a foreign entity, and by the scoped tool boundary when they do not) - with 21 hand-picked cases. Each case's rationale documents the property it proves and why it earned its slot; a small suite where every case is load-bearing is a stronger signal than volume. Each run evaluates the production primary model against its eval-ladder counterpart (whatever `backend/src/config.py` currently pins - Gemini 2.5 Flash vs Gemini 2.5 Pro as of this edit), outputting cost/accuracy matrices to justify the production layout choice.

---

## 7. Autonomy Posture: Supervised, with a Path to Delegated

The autonomy dial has five settings: Advisory, Supervised, Delegated, Independent, Autonomous. This MVP sits firmly at **Supervised**: the agent proposes, the human disposes. Every single generated clearance response is manually reviewed.

The promotion path to **Delegated** - where the agent can automatically release a defined, low-risk slice of logs (e.g., standard HTS code lookups with confidence $\ge 0.92$) without per-case manual review - is an evidence-based engineering decision, gated by two clear conditions:

1. Confidence-band approval rate exceeds $95\%$ in the $0.85+$ band across a statistically significant sample of reviewed historical drafts.
2. Zero tool-call integrity anomalies over that identical operational window.

---

## 8. Retrieval: Right-Sized for the Corpus, with a Reranker on the Threshold

Retrieval is where most "agentic AI" demos quietly collapse into a vector-search wrapper.
This one treats retrieval as a sized engineering decision rather than a default, and the thing that sizes it is the **query distribution**.
A compliance analyst's inquiry arrives in one of two modes, and the two modes want opposite things from the index:

- **Known-code lookup (the dominant mode).** The analyst - or the agent one step earlier - already holds the exact HTS code. `lookup_shipment_manifest` enriches every manifest line with its declared code, so by the time the loop calls `retrieve_tariff_regulation` the precise clause id (e.g. `8517.13.0000`) is usually already in hand. What is wanted is _that exact clause_, verbatim.
- **Discovery (the secondary mode).** The inquiry describes goods in prose ("thermal-imaging cameras for a security install") with no code attached. What is wanted is the _semantically nearest_ clauses to read against.

Dense embeddings are good at the second mode and measurably weak at the first.
An alphanumeric identifier like `8542.31.0001` is a low-information token for a semantic model: it will return five plausibly-related integrated-circuit clauses and quietly miss the one exact match.
Leaning on cosine similarity to recall an exact code is the wrong instrument for the dominant query.

**The decision: a single dense search plus a deterministic exact-fetch, merged.**
`retrieve_tariff_regulation` regex-extracts any full HTS code (`\d{4}\.\d{2}\.\d{4}`) from the query, looks those clauses up directly in the in-process catalog with no embedding round-trip, and guarantees they appear in the result - deduped against, then topped up by, the dense hits.
The exact path is deterministic and free; the dense path covers discovery.
Every result is tagged `match: "exact" | "semantic"` and an `exact_hits` count lands on the trace, so a reviewer can see which mode produced each citation.
_(See [`backend/src/tools/retrieve_tariff_regulation.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/tools/retrieve_tariff_regulation.py).)_

**The alternative I did not build: hybrid search + RRF + a live reranker.**
The textbook "serious" retrieval stack fuses a lexical/sparse signal (BM25) with the dense one via Reciprocal Rank Fusion, then runs a cross-encoder reranker over the top candidates.
It is the right answer at scale and the wrong answer here.
The corpus is 24 hand-curated synthetic clauses (`build_hts_clauses()`); a cross-encoder reranking 24 documents is theater, and it would bury the actual signal - which is recognizing that the dominant failure mode, exact-code recall, is solved deterministically in-process rather than statistically behind an always-on reranker endpoint.
Over-engineering 24 documents reads junior; right-sizing reads senior.

**The threshold - when the reranker stops being theater.**
This is a deferred _seam_, not a rejected idea, and the promotion conditions are explicit rather than aesthetic.
The MVP corpus is a stand-in for the real HTSUS, which runs to roughly 19,000 lines across thousands of headings; the retrieval stack should graduate to hybrid + RRF + a cross-encoder reranker when:

| Trigger                                          | Why it flips the decision                                                                                        |
| ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| Corpus grows from dozens toward the full HTSUS   | Dense recall@k degrades as near-duplicate headings crowd the embedding space, and lexical signal starts to weigh |
| Measured precision@k on discovery falls below target | The only honest trigger is a _measured_ one; the eval suite (§6) is where that number would live                |
| Queries mix partial codes with prose             | Heading-level or parent codes defeat the full-clause regex and need ranked fusion, not a dictionary lookup       |

The reranker is held as a seam rather than installed speculatively because a live cross-encoder endpoint for 24 documents is exactly the fixed-cost reflex the rest of this architecture refuses (cf. §3's "buy the commodity, build the moat" and the IAP decision in §5).
When the corpus earns it, the insertion point is this tool's merge step; nothing upstream of it changes.

**One honest note on storage.**
The same clauses live in two places at once: in-process (the catalog the exact-fetch and `lookup_shipment_manifest` both read) and in Pinecone (the embedded vectors the dense path reads).
At this scale the duplication is deliberate and cheap - the in-process copy is precisely what makes exact-fetch free and deterministic.
At HTSUS scale the in-process catalog becomes the system of record for exact lookups and Pinecone purely the semantic index; the two-store shape is already right, only the sizes change.
The embedding adapter that feeds the Pinecone side pins its output width and per-call task type explicitly, so the vector width always matches the fixed index.
_(See [`backend/src/embeddings.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/embeddings.py).)_

---

## 9. Frontend and Backend Wiring: One Origin, then a Split-Origin Pivot for Unbuffered SSE

_Amended 2026-07-03: this decision was later revised._
_Production pivoted from the same-origin Hosting rewrite to a split-origin `api.` subdomain, because a CDN on the rewrite path buffered the Server-Sent Events stream._
_The original same-origin reasoning below still holds for a request/response API and for local dev; see **The split-origin pivot** at the end of this section for what changed and why._

The frontend (React on Firebase Hosting) and the backend (FastAPI on Cloud Run) sit inside the same Firebase project, so how the browser reaches the API is itself a design choice rather than a default.
The "buy the commodity, build the moat" posture (§3) extends to the wiring: it should ride the platform's native path, not hand-built glue.

**The decision: serve the API through a Firebase Hosting rewrite, so the browser only ever sees one origin.**
`firebase.json` routes `/api/**` to the Cloud Run service and falls back to the SPA's `index.html` for everything else, so Hosting proxies each API call from its own domain.
That makes the call same-origin, and CORS stops being something the browser ever evaluates.

```json
"hosting": {
  "rewrites": [
    { "source": "/api/**", "run": { "serviceId": "trade-agent-backend", "region": "us-central1" } },
    { "source": "**", "destination": "/index.html" }
  ]
}
```

Order is load-bearing: the `/api/**` rule is matched before the SPA catch-all, and static assets are served before either rewrite applies.
Locally the Vite dev server's proxy mirrors the same `/api` route to the local backend, so the development and production topologies match and neither needs a cross-origin grant.
The frontend therefore calls a relative `/api` path and never embeds a raw `*.run.app` URL.

**The alternative I did not build: two origins joined by an explicit CORS allowlist.**
The default Cloud Run shape hands the frontend the raw service URL and asks the backend to publish a CORS policy enumerating every permitted origin, with a preflight `OPTIONS` round-trip on each non-simple request.
It works, but it stands up a second source of truth for "who may call this API" right beside the real one - the in-memory allowlist of §5 - and it is precisely the non-differentiating glue the platform already solves.
Same-origin makes the question moot rather than merely answered.

This is deliberately not a load balancer or IAP (cf. the IAP decision in §5): a Hosting rewrite carries no fixed hourly fee and does not put the public frontend behind a Google login wall.
It is the native Hosting feature, `us-central1` is a first-class colocation region for it, and Cloud Run still scales to zero, so there is no always-on component to operate.
This pattern is current and supported as of June 2026 - Firebase App Hosting is positioned for server-rendered frameworks (Next.js / Angular), not for a static SPA plus a separate containerized API, so the rewrite is the right tool rather than the legacy one.

**One honest note on caching.**
Routing through Hosting places a CDN in front of the API, which is harmless for the SPA's static assets and a hazard for its authenticated responses.
Every vendor-scoped response must carry `Cache-Control: private, no-store` so the edge never caches one analyst's data and replays it to another; the same-origin win would otherwise smuggle a cross-tenant leak back in at the cache layer.
That header is a response-layer requirement rather than an optional tuning knob, and it is the one new obligation this wiring choice creates.
**The split-origin pivot (2026-07-03).**
The same-origin rewrite was correct for a request/response JSON API, but the agent later grew a Server-Sent Events reasoning stream (`thinking_delta` / `text_delta`), and streaming is where the "one CDN in front of everything" win turns into a liability.
A CDN buffers responses, so on the Hosting rewrite path the browser receives the stream in coarse chunks instead of frame by frame - which defeats the point of streaming.
The fix is to give the streaming API a path that bypasses the CDN: a dedicated `api.trade-agent.samir.codes` subdomain, wired as a Cloudflare grey-cloud (DNS-only) record to the Cloud Run service, so no proxy sits between the browser and the origin and the SSE frames arrive unbuffered.
The frontend stays on `trade-agent.samir.codes` (Cloudflare-proxied, which is the right posture for its static assets).
The cost of the split is that the browser now makes a genuine cross-origin call, so CORS returns to the production path.
That is a deliberate, cheap trade: the backend re-enables it as a middleware allowlist keyed on `PROD_FRONTEND_ORIGINS` (`resolve_cors_origins` -> `CORSMiddleware`), one extra source of truth beside the §5 identity allowlist, and still **not** a load balancer or IAP (the §5 rejection stands).
The `Cache-Control: private, no-store` obligation from the caching note above still holds, because the frontend origin is still CDN-fronted and it is cheap insurance regardless.
The frontend no longer calls a relative `/api`: the production API base URL is baked into the build via `frontend/.env.production` (`VITE_API_BASE_URL`), while local dev keeps the same-origin Vite proxy.
See [`docs/GCP_SETUP.md`](https://github.com/yakyetilabs/trade-agent/blob/main/docs/GCP_SETUP.md) §9 for the operational setup.

---

## 10. What This Is _Not_

To ensure the boundary between what is built and what is claimed remains completely transparent, this project explicitly is not:

- **Connected to real trade or custom systems.** Every single bill of lading, container status, vendor name, and manifest discrepancy is synthetic and generated by local scripts in this repo. No real trade secrets or corporate secrets exist anywhere.
- **Affiliated with any actual port authority or carrier.** The architecture mirrors the exact shape of a US import customs-clearance workflow, but no real-world agencies or personnel are attached.
- **Built with bloated third-party AgentOps platforms.** No Langfuse or external observability proxies. Cloud Run streaming logs, a dedicated Firestore trace collection, and a custom `/traces` analytics page in the web interface comprise the entire lightweight operational surface.
- **Equipped with a deterministic post-processing policy engine.** The system relies on rigid system-prompt enforcement for text assertions, which is the exact model-trusted constraint a production pipeline would fortify with an independent rules parser.
- **Equipped with full least-privilege IAM policies.** The `trade-agent-platform-access` runtime role includes minor logging read privileges for rapid operator debugging that the serverless engine itself does not consume during runtime transactions (§12 documents the full IAM posture).

---

## 11. The Public-Demo Pivot: Dropping the Auth Perimeter, Keeping the Guards (2026-07-10)

**The decision.** The Firebase Authentication sign-in wall and the backend's in-memory email allowlist (the original in-app zero-trust authorization layer, `backend/src/security.py`) were removed entirely.
The app is now a public, no-auth demo over synthetic data.

**Why.** The allowlist was never a security boundary; its only real effect was implicit spend protection, by gating who could run the agent.
That protection is provided more directly at the infra level: reserved concurrency, a billing alarm, a cheap model, per-request caps, and pre-model guards.
A portfolio demo behind a login wall is a demo almost nobody sees; the showcase here is the agentic system and its philosophies (deterministic guards, draft-only disposition, tracing, observability), and none of those depend on knowing who the caller is.
Every internal safeguard from §5 is auth-independent and survives unchanged: edge validation plus `VendorContext` binding, the cross-vendor and escalation pre-model guards, draft-only disposition with the human approve/reject action, and full audit tracing.

**What replaces the allowlist's implicit spend protection.** Three explicit layers:

1. **Hard ceiling (infra):** Cloud Run `max-instances=2` with `concurrency=1`, which on Cloud Run multiplies to the true parallel-run ceiling (2 concurrent agent runs); a Vertex AI tokens-per-minute quota as the hard token cap; and a Cloud Billing budget alert as the backstop tripwire.
2. **In-app per-IP rate limiter:** a token-bucket limiter enforcing a general requests-per-minute cap across all `/api/*` routes plus a tokens-per-minute budget on the two inquiry endpoints (debited with the actual `total_tokens` after each run).
   Admission keys on the rightmost `X-Forwarded-For` entry - the value Google's front end appends for the peer that actually connected (leading entries are caller-supplied and spoofable; with the `api.` origin DNS-only, that peer is the real browser).
   A run's token cost is unknowable at admission, so the pre-check only refuses an already-exhausted budget; one request may overshoot and that IP then waits for refill - standard token-limit semantics.
   It is in-memory and per-instance-approximate by design: state resets on cold start and is not shared across instances.
   With at most two instances that error bound is small, the goal is abuse-smoothing rather than precise global fairness, and an in-memory check keeps the admission path free of database reads (the same principle the allowlist followed).
   The distributed version (a shared store such as Memorystore) is the named scale-up seam if the instance ceiling ever rises.
3. **Per-request controls (pre-existing):** the 4000-character inquiry cap, the agent's model-call cap, and the two deterministic pre-model guards.

**Why in-app rather than edge rate limiting.** Cloudflare's proxy buffers `text/event-stream`, and the split-origin design of §9 exists precisely to keep the SSE reasoning stream unbuffered.
Putting the `api.` subdomain behind Cloudflare's rate limiter would re-break the stream, so `api.trade-agent.samir.codes` stays DNS-only and the limiter lives in the app.

**Scope of the change.** `GET /api/vendors` and `GET /api/traces` return unfiltered synthetic data (the traces page is the public observability showcase), and the disposition endpoint stays public and functional - the human approve/reject action is a differentiator worth demonstrating.
The synthetic-data banner remains load-bearing.
References to the allowlist elsewhere in this document (§5, §9) are retained as dated history with amendment notes.

---

## 12. IAM Posture: Two Identities, Not One

**The decision.** This project runs under two distinct service accounts, each holding only what it uses: `trade-agent-platform-access` at runtime, and the build identity that produces the container image.
Neither holds a broad primitive role, and the project carries no `roles/editor` binding on any identity.

**Why two.** The distinction is easy to miss, because only one of the two is chosen deliberately.
`gcloud run deploy --source` hands the build to Cloud Build, which executes it as the **Compute Engine default service account**, an account GCP creates automatically with `roles/editor` already attached.
Left at that default, "build my container" is authorized to read every Firestore document, alter most resources, and change service configuration, even though the running service uses an entirely different and tightly scoped identity.

**Why it matters.** A build identity is a supply-chain surface, not a deployment detail.
Anything that can influence a build (a compromised base image, a dependency's install hook, an injected build step) executes with whatever that account holds.
A clean runtime role does not offset this, because the build never touches the runtime role.

**What each identity holds.**

- **Runtime (`trade-agent-platform-access`):** Vertex AI user, Firestore user, log writer, log viewer, plus Secret Manager accessor scoped to the single Pinecone secret rather than granted project-wide.
- **Build (Compute Engine default SA):** `roles/run.builder` only, the role Google publishes for deploy-from-source. It is six permissions: read the source object, upload / download / delete Artifact Registry artifacts, and write log entries.

**The non-obvious part.** The build identity needs no Cloud Run permission at all.
In this flow the build only builds; the CLI performs the actual deploy under the operator's own credentials, so neither `run.admin` nor `serviceAccountUser` belongs on the build account.
Deriving that from the build definition rather than assuming it is what keeps the role at six permissions instead of the ~80 in the general-purpose Cloud Build role.

The operational steps, including how to verify which identity your builds actually use, are in [`docs/GCP_SETUP.md`](https://github.com/yakyetilabs/trade-agent/blob/main/docs/GCP_SETUP.md) §5b.
