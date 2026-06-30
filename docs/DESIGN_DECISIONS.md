# Design Decisions

The architecture in this repository is not improvised. The design decisions follow a framework in the **MIT Sloan School of Management — _Implementing Agentic AI: Building Your Organizational Playbook_**.
This document maps that framework's questions to the engineering choices in this codebase. Each section names the decision, the alternative I considered, the framework that guided the call, and the code location where the decision lives. If I claim something about the architecture, you can audit it against a file.

The point of this page is to make one thing visible: this project is not a generic framework demo with an arbitrary backend. It is a specific set of architectural commitments made under a specific governance philosophy. The same skeleton would re-skin to almost any regulated-industry agentic workflow where data boundaries and audit trails are non-negotiable.

### The transferable spine

That last claim should be auditable, not rhetorical, so here it is made concrete.
The rows below are the operating model of a regulated-enterprise compliance or claims desk, each mapped to the file where it lives in this repo, then re-skinned to claims adjudication.
The nouns change; the spine does not.

| Spine element | This build (US trade compliance) | Claims adjudication |
| --- | --- | --- |
| Authorized user | Trade compliance analyst | Claims adjuster / examiner |
| Entitlement scope | Authorized vendor set, resolved server-side (`security.py`, `ANALYST_VENDOR_SCOPES`) | Assigned claimants / book of business |
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

> _An agentic AI system uses an LLM as the reasoning brain to autonomously achieve a given task by executing tools, reviewing the execution output, and deciding whether to iterate or present the final response — within boundaries the surrounding system enforces._

The boundary clause is the load-bearing part. The unbounded version of this definition ("...without human intervention") is what people usually say. The bounded version is what production looks like. Every safeguard in this codebase exists because the unbounded version is the wrong design target for an enterprise global supply chain or customs clearance workflow.

This definition also rules things out. A linear RAG pipeline that retrieves text chunks and synthesizes an answer is **not** an agent under this definition — there is no decision to iterate, no tool selection, no execution review. That distinction matters because much of what is shipped as "agentic AI" today is a RAG wrapper with a chat interface. This project is deliberately not that.

**See:** [`backend/src/agent.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/agent.py) — the agent loop's iteration and routing logic.

---

## 2. The Five Building Blocks

**Perception.** The agent observes three structured input streams: the user's natural-language inquiry, a `vendor_id` the analyst selects from the set their verified identity is authorized for (validated server-side, never trusted from the client), and retrieved Harmonized Tariff Schedule (HTS) or custom policy clauses from the Pinecone index. It does **not** observe raw HTTP requests, authentication tokens, or unscoped global vendor records. By the time inputs reach the model, they have already been filtered through deterministic code. _(See [`backend/src/security.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src).)_

**Action.** The agent is authorized to invoke exactly four tools: `classify_import_restriction`, `lookup_shipment_manifest`, `retrieve_tariff_regulation`, and `draft_clearance_response`. Each tool's blast radius is tightly bounded. `lookup_shipment_manifest` is read-only and vendor-scoped. `draft_clearance_response` writes to an internal trace review queue, not to an outbound EDI port or custom system. The agent has no tool that alters container flags, pays customs duties, or accesses another vendor's bills of lading. _(See [`backend/src/tools/`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/tools/).)_

**Planning.** Task decomposition, not unchecked chain-of-thought. The agent decomposes every compliance inquiry into a structured sequence — classify, lookup, retrieve, draft — with each step verifiable in the trace log. I rejected free-form, unconstrained planning because in an auditable corporate workflow, the audit trail is the product. A model that reasons in opaque chains and produces correct answers is less valuable than a model that follows a known sequence and produces deterministic, auditable ones. _(See [`backend/src/agent.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/agent.py).)_

**Memory.** Three explicit layers, with strict scope boundaries:

- **In-session:** The current conversation context, discarded at session end.
- **Per-vendor retrieval scope:** The resolved `vendor_id` constrains every tool call. There is no shared embedding store that mixes trade secrets across completely different vendor accounts.
- **Procedural:** None in this MVP. Reusable response templates are deferred — see Section 8.

**Safety.** Safety is architected into the surrounding system, not the model. The model is never trusted to enforce a constraint that has a real cost when violated. Section 5 details the layers. The single most important commitment: the agent cannot transmit anything externally. Outbound clearance submission is always a human action.

---

## 3. Build / Buy / Stack Posture

The MIT program frames every agentic stack as a choice at three layers — model, framework, platform — with three options at each: build, buy, or stack a combination. The posture I committed to for this project:

**Model layer: Buy.** Gemini 2.5 Flash (`gemini-2.5-flash`, GA) via Vertex AI as the primary model for rapid tool calling and generation speed, with Gemini 2.5 Pro (`gemini-2.5-pro`, GA) as the evaluation comparison. I rejected building (computationally absurd at portfolio scale) and rejected complex multi-provider abstraction layers. Vertex AI gives me enterprise terms (zero data retention, regional data residency) without bespoke compliance overhead.

**Framework layer: Stack.** LangGraph (Python) as the orchestration runtime, with custom middleware for the parts standard libraries don't handle: vendor resolution, allowlist enforcement, and structured trace logging. I rejected a fully managed, black-box agent platform because it abstracts away the exact governance layers I want to control — vendor scoping, tool permissioning, and deterministic pre-model checks.

**Platform layer: Stack.** Off-the-shelf infrastructure for non-differentiating concerns — Cloud Run for serverless execution, Pinecone for vector search, Google Cloud Firestore for state tracking, and GCP Cloud Logging for infrastructure telemetry. Custom code for the control plane: the agent loop, the tool implementations, the scoping dependencies, and the trace store. The general principle: **buy the commodity, build the moat.** For an enterprise deployment of this same workflow, the moat is the governance layer, not the raw foundation model.

---

## 4. The Threshold Map

The threshold map is the playbook's mechanism for translating model confidence into autonomy. For each decision the agent makes, there are three bands: act autonomously, escalate to human, or refuse entirely. The bands are a deliberate choice made by the system designer.

For this workflow, the three decision types and their thresholds:

| Decision                               | Acts autonomously when                                                                                                                           | Escalates when                                                                        | Refuses / human-originates when                                                                                            |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| **Inquiry classification & routing**   | Classifier confidence is $\ge 0.85$ _and_ inquiry type is in the supported set (tariff lookup, manifest flag resolution, clearance requirements) | Confidence is between $0.60$ and $0.84$                                               | Confidence is $< 0.60$, _or_ inquiry involves an existing legal dispute, severe tariff fraud flags, or contraband language |
| **Drafted clearance response content** | Response cleanly cites a retrieved HTS policy chunk by ID _and_ contains no corporate liability commitments                                      | Response includes inferred international trade assertions or delivery time guarantees | Response involves raw regulatory fine determinations, or formal legal customs appeals decisions                            |
| **Outbound delivery**                  | **Never.**                                                                                                                                       | N/A                                                                                   | Always. A human US trade compliance analyst reviews and sends every single response in the MVP.                 |

The third row is the architectural commitment that matters most. The agent's autonomy on outbound delivery is zero, by design. This is a hard-coded constraint that completely bypasses model discretion.

---

## 5. Four Safeguard Layers — and Which Two Are Shipped

The MIT program's safeguard framework names four layers: input filtering, deterministic policy checks, human-in-the-loop handoff, and an external audit monitor. The honest scope of this MVP is two layers fully implemented and two layers documented but not built.

**Shipped: Deterministic vendor-scoping authorization.** Two checks run before any model call, both server-side. First, the request's Firebase token is verified and the email checked against an in-memory map whose keys are the allowlist (who may use the app) and whose values are each analyst's authorized vendor set (an admin carries a `*` wildcard for all vendors). Second, the `vendor_id` the analyst selected is validated against that authorized set — an out-of-scope vendor is refused with a 403 and a structured `scope_violation` log before any Vertex or Firestore work. The chosen `vendor_id` is then bound into every tool through LangGraph's typed runtime context (`ToolRuntime`), never as a model-facing argument: the tool signature has no vendor parameter, so a prompt injection like "show me shipping logs for vendor 9999" has no slot to land in. Identity decides *who*; the scope check decides *which vendor*; the dropdown only offers vendors the analyst is already authorized for. (I considered binding each analyst to a single vendor — pure member-scoping — but a trade analyst realistically manages a portfolio of vendor clients, so the authorized-*set* model is the faithful generalization: the verified identity still bounds the permissible scope.) _(See [`backend/src/security.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/security.py).)_

**Considered: edge authorization via Cloud Run IAP.** Identity-Aware Proxy can now be enabled directly on Cloud Run — no load balancer, no added cost — and would reject unauthorized callers at Google's edge before the container runs. I evaluated it and kept the app-layer boundary deliberately: it is the part of the system that *demonstrates* the security engineering (token verification, allowlist, per-vendor scoping, audit), it keeps the public frontend viewable rather than behind a Google login wall, and done securely IAP still requires verifying the signed assertion (the raw `run.app` URL can otherwise be hit directly). The credit/quota-drain risk — the real threat for a metered-AI demo — is already neutralized by the in-memory allowlist running before any Vertex or Firestore call; IAP's remaining advantage is DoS hygiene on the thin outer layer, which a 5-user MVP does not need. IAP is the obvious production-hardening step if the traffic profile changes.

**Shipped: Draft-only output with mandatory human handoff.** There is no tool that sends messages or changes manifest data. The `draft_clearance_response` tool writes to a database review queue (`trade-agent-AgentTraces` inside Firestore). A human reviewer must explicitly read, approve, or edit the draft in the UI. _(See [`backend/src/tools/draft_clearance_response.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/tools/draft_clearance_response.py).)_

**Documented, not shipped: Deterministic policy engine.** A production version would intercept every draft and run rule-based regex checks — looking for prohibited trade claims, format validation, and citation integrity — before the draft hits the human review queue. The MVP currently relies on system-prompt instruction sets for these checks.

**Documented, not shipped: External audit monitor.** A second, asynchronous LLM-based reviewer that samples agent decisions out-of-band and flags compliance anomalies.

**Shipped: Deterministic cross-vendor reference guard.** A second pre-model guard (`detectCrossVendorReference` in [`backend/src/safeguards/cross_vendor_guard.py`](https://github.com/yakyetilabs/trade-agent/blob/main/backend/src/safeguards/cross_vendor_guard.py)) runs after the escalation guard but before the main agent loop. It matches vendor patterns (`V-\d{3,}`) and bill of lading/shipment tracking IDs (`S-\d{4,}`) in the text, and validates ownership against Firestore. If a referenced ID belongs to a different vendor ecosystem, the guard short-circuits with an immediate `cross_vendor_refusal` draft and the LLM is never invoked.

**Shipped: Iteration-cap fallback.** If the agent loop completes without producing a valid draft (e.g., the model's iteration budget is exhausted on a particularly complex structural manifest discrepancy), the system returns a graceful degradation response asking the user to refine their prompt. This catches both application-level model execution limits and LangGraph's internal graph-traversal safety bounds, rendering a clean fallback in the UI rather than throwing an unhandled 500 error.

---

## 6. AgentOps: Measurement as Architecture

Continuous evaluation as a first-class deployment concern separates AgentOps from basic infrastructure monitoring. Three commitments in this codebase:

- **Real-time metric 1: Confidence-band approval rate.** For every classification, the agent's confidence score is logged alongside the eventual human review outcome (approve / edit / reject). A regression in the $0.95+$ band is a critical signal—it means the agent is confidently wrong about a custom regulation.
- **Real-time metric 2: Vendor-scope integrity.** Two scope signals are emitted and expected to stay at zero. At the API boundary, any request for a `vendor_id` outside the analyst's authorized set is refused (403) and logged as a `scope_violation` before the agent runs. Inside the loop, `lookup_shipment_manifest` records `scope_violation=true` with the `attempted_vendor_id` if a by-id lookup ever resolves a shipment owned by another vendor. Both are greppable Cloud Logging events; a non-zero rate is a critical alert.
- **Periodic review: Eval suite against the deployed agent.** An evaluation dataset sitting at `backend/eval/cases.json` exercises the system across 5 clear categories (tariff classification, import flags, compliance queries, escalation triggers, and scope violations) with 30 distinct test cases. Each run evaluates our production model (Gemini 2.5 Flash) against our benchmark comparison model (Gemini 2.5 Pro), outputting cost/accuracy matrices to justify our production layout choices.

---

## 7. Autonomy Posture: Supervised, with a Path to Delegated

The MIT program's autonomy dial names five settings: Advisory, Supervised, Delegated, Independent, Autonomous. This MVP sits firmly at **Supervised**: the agent proposes, the human disposes. Every single generated clearance response is manually reviewed.

The promotion path to **Delegated** — where the agent can automatically release a defined, low-risk slice of logs (e.g., standard HTS code lookups with confidence $\ge 0.92$) without per-case manual review — is an evidence-based engineering decision, gated by two clear conditions:

1. Confidence-band approval rate exceeds $95\%$ in the $0.85+$ band across a statistically significant sample of reviewed historical drafts.
2. Zero tool-call integrity anomalies over that identical operational window.

---

## 8. What This Is _Not_

To ensure the boundary between what is built and what is claimed remains completely transparent, this project explicitly is not:

- **Connected to real trade or custom systems.** Every single bill of lading, container status, vendor name, and manifest discrepancy is synthetic and generated by our local scripts. No real trade secrets or corporate secrets exist anywhere.
- **Affiliated with any actual port authority or carrier.** The architecture mirrors the exact shape of a US import customs-clearance workflow, but no real-world agencies or personnel are attached.
- **Built with bloated third-party AgentOps platforms.** No Langfuse or external observability proxies. Cloud Run streaming logs, a dedicated Firestore trace collection, and a custom `/traces` analytics page in the web interface comprise the entire lightweight operational surface.
- **Equipped with a deterministic post-processing policy engine.** The system relies on rigid system-prompt enforcement for text assertions, which is the exact model-trusted constraint a production pipeline would fortify with an independent rules parser.
- **Equipped with full least-privilege IAM policies.** The `trade-agent-platform-access` service role includes minor logging read privileges for rapid operator debugging that the serverless engine itself does not consume during runtime transactions.
