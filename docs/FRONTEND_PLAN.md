# Frontend Plan: the Analyst Console and Audit Trail

This is the concrete, locked build plan for the React/Vite frontend (Phase 4, second half).
It is written to be executed cold from a fresh session.
For who and what, see [PRODUCT.md](PRODUCT.md).
For why the architecture is shaped this way, see [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).
For environment and deployment, see [GCP_SETUP.md](GCP_SETUP.md).
The source of truth for values and config is `backend/src/config.py`.

## Status at the start of this phase

The backend is complete and live-verified end-to-end.
The agent loop, the four tools, the deterministic guards, the trace store, the eval suite, and the billable token split (committed `7ec8a3b`) are all in place and green.
The React/Vite frontend is not started.
Deployment is documented in `GCP_SETUP.md` §9 but not built; `Dockerfile` and `deploy.sh` do not exist yet.
The definition of done for this phase is a live, deployed URL that runs the whole pipeline.

## Locked decisions (do not re-litigate)

- Visual brand is a dark "AgentOps console".
  The tokens are below.
- The live-run experience is Layer 1 only.
  The four-stage pipeline animates from real Server-Sent Events as each tool executes.
  Token-by-token streaming of the draft text is parked as Future work.
- The draft stays a tool.
  `draft_clearance_response` and the "exactly four tools" contract are unchanged.
  We do not restructure the draft into streamed assistant text in this phase.
- Frontend and backend wiring is same-origin.
  Locally that is the Vite dev-server proxy; in production it is a Firebase Hosting `/api/**` rewrite.
  There is no CORS on the production path, and authenticated responses carry `Cache-Control: private, no-store`.
- Auth is one-click Google sign-in in production.
  Firebase authenticates; the in-memory allowlist authorizes server-side, so a non-allowlisted Google user gets a 403.
  The Email/Password scaffold is disabled once the frontend works.
- Production is in scope.
  The phase is not done until the system runs end-to-end at a deployed URL.

## Why Layer 1 only (the streaming decision)

There are two distinct kinds of "streaming", and only the first is in scope now.

1. Progress streaming: the pipeline stages light up as each tool runs.
   This needs no special model configuration and is the source of the "alive" feeling and the architecture legibility that sell the demo.
2. Text streaming: the draft prose renders token-by-token as it is generated.
   On `gemini-2.5-flash` this is fragile, because our draft is a tool-call argument, and Gemini's incremental function-call-argument streaming (`streamFunctionCallArguments` with `partialArgs` and `willContinue`) is Vertex-only and currently associated with Gemini 3 Pro Preview.

The "wow" is the legible agentic pipeline, the maker-checker gate, and the audit trail, not the typewriter effect.
Layer 1 delivers all of that, so text streaming is deferred without losing the impact.

## Information architecture (four surfaces)

1. Sign-in: one-click Google, the synthetic-data disclaimer, the brand moment.
2. Console: the vendor scope picker, the inquiry, the live pipeline, the grounded draft, and the maker-checker actions.
   This is where the demo lives.
3. Audit Trail (`/traces`): the recent-runs list with disposition, intent, latency, and tokens, plus a trace-detail timeline that expands every tool call's input and output.
   This is the defensible record, and it is half of what makes the project read as senior.
4. Shell: the persistent top bar (brand, vendor scope, identity, sign-out), the load-bearing "Synthetic data" pill, and the nav between Console and Audit Trail.

## The dark AgentOps theme

These are the starting tokens; refine in F4.

- Ink scale: page `#0B0E15`, surface `#121722`, elevated `#1A2130`, hairline border `#232C3D`.
- Text: primary `#E6EDF6`, secondary `#9AA7BD`, muted `#6B7689`.
- One accent: electric blue `#4C8DFF`, used sparingly for primary actions, the active pipeline node, and links.
- Semantic states: held and draft amber `#E0A23B`, escalated red `#E5534B`, approved and cleared teal `#2EA88A`.
- Type: a grotesk or Inter sans for prose, a monospace such as JetBrains Mono or Geist Mono for every code, id, and token count.
- Motion: 150 to 250ms ease-out, a soft pulse on the active pipeline node as each event lands, and a clean settle rather than a hard pop when the draft arrives.

## Screen specs

### Console

- A vendor scope picker bound to `GET /api/vendors`, which returns only the analyst's authorized vendors.
- The selected vendor's context shown inline: legal name, country, customs broker, categories.
- A natural-language inquiry input, 1 to 4000 characters, matching `InquiryRequest`.
- On submit, the run streams from the Layer 1 SSE endpoint and the four-stage pipeline animates: classify, look up, retrieve, draft.
- Each stage shows its real result as it completes: intent and confidence; shipment count and ids; HTS codes and the exact-match flag; draft ready.
- The grounded draft settles into a document card with cited shipment ids and HTS codes highlighted as monospace chips.
- The maker-checker actions are Approve and release, Edit, and Reject.
  Approve and Reject call `POST /api/traces/{trace_id}/disposition`.
- A metadata strip shows model, latency, and the billable token split (prompt, output, thinking, total) from the `done` event.
- A guard path: if an escalation or cross-vendor guard fires, the run ends before the model with a clear "routed to a human" state and no token spend.

### Audit Trail

- A list of recent traces, newest first, from `GET /api/traces`, filterable by disposition.
- Each row shows a disposition dot and badge, the intent, the vendor, latency, and total tokens.
- A row expands to the trace detail: the inquiry, the vendor, the model, the four-tool timeline (each tool's duration and a one-line input to output), the draft, the token split, and the disposition control.
- A draft trace shows Approve and Reject; a decided trace shows the recorded disposition.

### Sign-in

- One-click Google.
- The synthetic-data disclaimer, stated plainly.

### Shell

- Top bar: brand, the vendor scope picker, the analyst identity and sign-out, the "Synthetic data" pill.
- Nav between Console and Audit Trail.
- An auth guard: unauthenticated users see only Sign-in, and a 403 from the backend surfaces a clear "not authorized" state.

## The SSE event contract (Layer 1)

The streaming endpoint emits `text/event-stream`.
The event types are:

- `run_started`: `{ trace_id, vendor_id, model }`.
- `stage_started`: `{ stage }`, where stage is one of `classify`, `lookup`, `retrieve`, `draft`.
- `stage_completed`: `{ stage, summary }`, where summary carries the real result (classify gives intent and confidence; lookup gives count and shipment_ids; retrieve gives hts_codes and the exact-hit flag; draft gives ready).
- `guard_triggered`: `{ kind, reason }`, where kind is `escalation` or `cross_vendor`.
  This is terminal; the model never runs.
- `done`: `{ result }`, carrying the full `AgentResult` (disposition, draft, classification, tool names, duration, and the token split).
- `error`: `{ message }`.

Transport notes:

- The browser consumes the stream with `fetch` plus a `ReadableStream` reader, not `EventSource`, so the Firebase Bearer token rides in the Authorization header.
- The response carries `Cache-Control: no-store`.
- In production the Hosting rewrite and the CDN must pass the stream through unbuffered; verify this in F5.

## Backend design (F0)

- A new endpoint, `POST /api/inquiry/stream`, returning `text/event-stream`.
- Auth and vendor-scope checks are identical to `POST /api/inquiry`: `verify_authorized_analyst` then `analyst_can_access_vendor`.
- An async streaming runner drives the compiled agent via its streaming API.
  Verify the exact `astream_events` or `stream_mode` shapes against current LangChain 1.0 docs at build time.
  It maps tool start and stop plus the guard outcomes to the SSE event types above, persists the same single `AgentTrace` at the end, and emits the `done` event with the `AgentResult`.
- The synchronous `run_agent` and `POST /api/inquiry` stay as the eval-suite path and a non-streaming fallback.
- Risk to verify first: our tools are synchronous and our trace is a `ContextVar`.
  Confirm the trace context propagates correctly when the graph runs under the async streaming driver, since tools execute in a worker thread.
  If `astream_events` does not give a clean tool-execution signal, derive the events from the existing `record_tool_call` seam instead.
- Tests are hermetic: a fake async event stream asserting the emitted SSE events, and keep the existing synchronous tests.

## Build phases and tasks

### F0 - Backend SSE endpoint (Layer 1)

- Add the streaming runner and the `/api/inquiry/stream` endpoint.
- Reuse the auth and vendor-scope checks.
- Persist exactly one trace and emit `done` with the `AgentResult`.
- Add tests for the event sequence on a normal run, an escalation, and a cross-vendor refusal.
- Verify the streaming API and the `ContextVar` boundary before wiring the UI.

### F1 - Frontend foundation

- Scaffold Vite + React 18 + TypeScript + Tailwind under `frontend/`.
- Add the root `tsconfig.base.json` and have `frontend/tsconfig.json` extend it.
- `frontend/src/config.ts` reads `import.meta.env` once and re-exports typed config.
- Build the dark AgentOps Tailwind theme.
- Build the API client: `fetch` with the Firebase Bearer token, same-origin `/api`.
- Add the Firebase web SDK, Google sign-in, and the auth context and guard.
- Build the app shell and the sign-in screen.

### F2 - Console (the hero)

- The vendor scope picker and the vendor context.
- The inquiry input.
- The SSE client and the run-state machine: idle, then stages, then draft, then done or error.
- The animated pipeline.
- The grounded draft card with citations.
- The maker-checker disposition actions.
- The token and latency strip.

### F3 - Audit Trail

- The recent-traces list with disposition filters.
- The trace-detail timeline.
- The disposition control.

### F4 - Polish

- Empty, loading, and error states everywhere.
- Transitions and the pixel pass.
- The Vite dev-server proxy for same-origin local development.

### F5 - Production

- Backend: a `Dockerfile` and `deploy.sh`; reconcile the buildpack-versus-Dockerfile question from `GCP_SETUP.md` §9; deploy to Cloud Run.
- Frontend: Firebase Hosting with the `/api/**` rewrite; confirm SSE passes through unbuffered.
- Secret Manager for `PINECONE_API_KEY`, replacing the plaintext env var.
- Disable the Email/Password provider and leave Google-only.
- End state: a live URL that runs the whole pipeline.

## Future work (parked)

- Layer 2: token-by-token streaming of the draft text.
  This is gated on either Gemini's incremental function-call-argument streaming maturing (`streamFunctionCallArguments` with `partialArgs` and `willContinue`, currently Vertex-only and associated with Gemini 3 Pro Preview), or a model swap to Claude on Vertex.
  If pursued, the cleanest path is to make the final draft the model's streamed assistant text and to derive the citations by regex from the draft, which would touch the "exactly four tools" contract and so needs a conscious design update.
  Evidence: [function calling intro](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/tools/function-calling) and [vercel/ai #11126](https://github.com/vercel/ai/issues/11126).
- A model swap to Claude (Haiku or Sonnet) on Vertex.
  This is cheap because the model is isolated behind `config.py` and `_build_agent`, and it could be the same change that unlocks Layer 2.

## References

- [PRODUCT.md](PRODUCT.md), [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md), [GCP_SETUP.md](GCP_SETUP.md).
- `backend/src/config.py` for models, dimensions, region, and scopes.
- `backend/src/app.py` for the API surface the frontend consumes.
