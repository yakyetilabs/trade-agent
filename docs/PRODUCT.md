# Product Overview: Who Uses TradeOps AI, and What Happens When They Do

This document describes the end user, the job they do, and exactly what the system does when they interact with it.
It is the "who and what" of the product.
For *why* the architecture is shaped this way, see [DESIGN_DECISIONS.md](DESIGN_DECISIONS.md).
For environment and deployment setup, see [GCP_SETUP.md](GCP_SETUP.md).

TradeOps AI puts an LLM inside a regulated-enterprise compliance workflow without handing it the keys.
Concretely, it helps a US Trade Compliance Analyst understand why an inbound import shipment is held or flagged at a US port of entry, and it drafts the official clearance response for that analyst to review and release.
The domain is US import compliance; the operating model underneath it is not domain-specific, which is the entire point (see [the transferable spine](DESIGN_DECISIONS.md#the-transferable-spine)).

---

## The operating model

This system implements the standard operating model of a regulated-enterprise compliance or claims desk:

- An analyst is **entitled** to a scoped book of business and works only within it.
- Work arrives as **cases** (here, held or flagged shipments) that each need a defensible written disposition.
- Hard rules **pre-screen** every case before any judgment is applied.
- The disposition is produced under a **maker-checker** control: a preparer drafts, an approver releases, and no single actor does both.
- Every case produces an **immutable audit record** that can be defended in an exam or review.

What is distinctive here is where the LLM sits.
The agent is the **maker**: it prepares the draft.
The human analyst is the **checker**: they approve and release it.
The agent is structurally incapable of approving or transmitting its own work, so separation of duties holds by construction, not by policy.
Trade compliance is the skin on this model; the same spine re-skins to claims adjudication with only the nouns changing.

---

## The user: a US Trade Compliance Analyst

The user is a US Trade Compliance Analyst working on behalf of importers, who appear in the system as *vendors*.
Their identity entitles them to a specific set of vendors (their book of business), resolved server-side; they never see another analyst's or another vendor's data.
When US Customs and Border Protection (CBP) holds or flags an inbound container at a port of entry, the analyst owns that case end to end.

The work is high cognitive load and high stakes.
To clear one held shipment by hand, the analyst cross-references the shipment's manifest, looks up the governing Harmonized Tariff Schedule (HTSUS) classification, determines the restriction or licensing requirement, and drafts a defensible clearance response under time pressure.
They are a domain expert, not a layperson: they already know HTS codes, customs terminology, and what a clearance response must contain and must never claim.

The scope is deliberately **US import compliance**, not multi-jurisdiction international trade.
International trade compliance spans every country's customs regime, cross-border export controls, and per-jurisdiction sanctions lists; modeling it would be a far larger and less honest claim for a demo of this size.
Narrowing to US import compliance keeps the system faithful to the data it actually has: HTSUS classification text and US-side enforcement signals such as OFAC.

---

## The job to be done

In the analyst's own words:

> "A shipment of mine is held at the port. Tell me why, ground it in the actual manifest and the actual regulation, and draft the clearance response that I will review and send."

The analyst is not asking the system to act, to submit anything to CBP, or to change a shipment's status.
They are asking it to assemble a *grounded draft* faster than they could by hand, while they keep approval authority over every outbound communication.
The product's value is grounded drafting speed under a hard human-approval gate, not autonomy.

---

## What happens when they interact

A single inquiry runs through a fixed, auditable sequence.
The model only runs in the middle of that sequence, and only after the deterministic guards have cleared the case.

**1. Scope.**
There is no sign-in - the app is a public demo over synthetic data (the original allowlist perimeter was removed in the public-demo pivot; spend is capped by infra ceilings plus an in-app per-IP rate limiter, see `DESIGN_DECISIONS.md` §11).
The analyst selects an active vendor from the picker, and that `vendor_id` is pattern-validated server-side and bound into the run, never trusted as free text.

**2. Open a case.**
The analyst submits a natural-language inquiry, for example "Why is my latest cargo container held at the port?"

**3. Pre-screen (deterministic, before the model).**
An escalation guard scans for severe signals (contraband, sanctions, federal seizure, bribery) and routes those straight to a human queue; the model never runs on them.
A cross-vendor guard refuses any inquiry that references another vendor's shipment or vendor ids, enforcing data segregation before a single token is spent.

**4. Prepare the draft (the agent loop).**
A bounded LangGraph agent runs four tools in order: classify the inquiry, look up the vendor's shipments and manifests, retrieve the governing HTS clauses, and draft the response.
The `vendor_id` is bound into the agent's runtime context, never exposed as a tool argument, so a prompt injection has no slot to redirect the scope.

**5. Hand off under maker-checker.**
The agent's only output is a draft written to a review queue (the `trade-agent-AgentTraces` store) with a `draft` status.
There is no tool, anywhere, that transmits a response to CBP or mutates a shipment; the maker cannot approve itself.

**6. Review and release.**
The analyst reads the draft, edits it if needed, and is the one who releases it.
Approval is a separate, explicit human action; the same analyst who owns the case is its checker.

**7. Audit.**
Every step (each tool call, its raw inputs and outputs, the classification, token and latency metadata) is recorded to one audit trace per case.
The trace is as much the product as the draft: in a compliance workflow, being able to reconstruct exactly what the agent did is what makes a disposition defensible.

---

## What the system guarantees, and what it refuses

- **Entitlement-scoped data.** The analyst only ever sees their entitled vendor's data; scope is resolved outside the model and enforced on every tool call.
- **Separation of duties.** The agent prepares; the human approves and releases. Outbound delivery is always a human action, by construction, not model discretion.
- **Grounding discipline.** Every factual claim traces to a looked-up shipment or a retrieved HTS clause; an empty lookup yields a draft that says so rather than inventing a hold.
- **Escalation over guessing.** Severe trade-security signals are intercepted deterministically and handed to a human before the model is invoked.
- **Defensible audit.** Every case produces exactly one structured trace, so any draft can be reconstructed and defended after the fact.

---

## A few concrete interactions

| The analyst does this | The system does this |
| --- | --- |
| Vendor `V-009`: "Why is my latest cargo container held at the port?" | Runs the full loop: classifies the inquiry, looks up `V-009`'s held shipment, retrieves the governing HTS clause, and drafts a response citing the exact shipment and clause. |
| Vendor `V-001` (no held shipments): same question | Looks up, finds zero matching shipments, and drafts a response that plainly states no active holds exist, making no specific-shipment claims. |
| Any analyst: "I refuse to pay this penalty, my lawyer will contact you." | The escalation guard intercepts it in well under a second and routes it to a human; the model is never invoked. |
| Vendor `V-009`: "Give me clearance details on shipment S-0042" (owned by another vendor) | The cross-vendor guard validates ownership, refuses, and returns a clear refusal draft; no foreign data is disclosed. |

---

## Build status, stated honestly

The system is built and running end to end: the backend (FastAPI on Cloud Run, the agent loop, the four tools, the deterministic guards, the trace store, and the eval suite) and the analyst-facing React console that frames this interaction, including the `/traces` audit view, are both implemented and deployed.
All vendors, shipments, manifests, and HTS clauses are synthetic and generated by scripts in this repository; no real trade records exist anywhere in the codebase.
