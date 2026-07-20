# GCP & Cloud Deployment: Lessons Learned

A record of non-obvious, hard-won lessons from deploying this project to GCP.
Written to be portable: useful in a future enterprise GCP engagement, not just this repo.
Each entry states the general principle first, with a concrete aside from this project where useful.

## Contents

- [A Firebase project is a GCP project](#a-firebase-project-is-a-gcp-project)
- [Dockerfile vs. buildpacks: the real trade-off is not cost](#dockerfile-vs-buildpacks-the-real-trade-off-is-not-cost)
- [Same-origin beats CORS, and beats a load balancer](#same-origin-beats-cors-and-beats-a-load-balancer)
- [Authentication and authorization are different layers](#authentication-and-authorization-are-different-layers)
- [Service accounts must be created and granted explicitly](#service-accounts-must-be-created-and-granted-explicitly)
- [Your build runs as an identity you never chose, and it ships with Editor](#your-build-runs-as-an-identity-you-never-chose-and-it-ships-with-editor)
- [Secrets belong in Secret Manager](#secrets-belong-in-secret-manager)
- [Two ignore files, two different jobs](#two-ignore-files-two-different-jobs)
- [gcloud's list-flag delimiter can silently corrupt values](#gclouds-list-flag-delimiter-can-silently-corrupt-values)
- [Scripted gcloud calls must never be able to prompt](#scripted-gcloud-calls-must-never-be-able-to-prompt)
- [Pin exact versions for reproducibility](#pin-exact-versions-for-reproducibility)
- [In a polyglot monorepo, each ecosystem owns its own tooling root](#in-a-polyglot-monorepo-each-ecosystem-owns-its-own-tooling-root)
- [Verify CLI and console behavior against current docs](#verify-cli-and-console-behavior-against-current-docs)
- [Verify what is deployed, not just what is committed](#verify-what-is-deployed-not-just-what-is-committed)
- [The actual dials for cost vs. availability on a scale-to-zero service](#the-actual-dials-for-cost-vs-availability-on-a-scale-to-zero-service)
- [Model-API feature constraints compose; verify the combination, not each feature alone](#model-api-feature-constraints-compose-verify-the-combination-not-each-feature-alone)
- [A custom domain is not authorized for federated sign-in until you allowlist it](#a-custom-domain-is-not-authorized-for-federated-sign-in-until-you-allowlist-it)
- [Referencing a bundler's whole env object embeds every env var in the shipped bundle](#referencing-a-bundlers-whole-env-object-embeds-every-env-var-in-the-shipped-bundle)
- [A model quota grant is several quotas; probe the endpoint, don't trust the console](#a-model-quota-grant-is-several-quotas-probe-the-endpoint-dont-trust-the-console)
- [Agent loops burst through per-minute token quotas, and graceful fallbacks hide it](#agent-loops-burst-through-per-minute-token-quotas-and-graceful-fallbacks-hide-it)
- [A system prompt tuned on one model family overfits its tool-calling habits](#a-system-prompt-tuned-on-one-model-family-overfits-its-tool-calling-habits)
- [An eval arm must bind every internal model call, not just the main loop](#an-eval-arm-must-bind-every-internal-model-call-not-just-the-main-loop)

## A Firebase project is a GCP project

- Firebase is a product layer on top of a GCP project, not a separate cloud.
- Same project ID, same IAM, same billing account, same quota.
- Before assuming you need to bridge "two clouds," check whether you already have one project with two consoles into it.

## Dockerfile vs. buildpacks: the real trade-off is not cost

- `gcloud run deploy --source` auto-detects the build strategy: it prefers a Dockerfile if one is present in the source directory, and falls back to Cloud Native Buildpacks only if there isn't one.
- Both paths build on Cloud Build and both push to the same auto-created Artifact Registry repo (`cloud-run-source-deploy`).
  There is no cost delta between them.
- The real trade-off is control and reproducibility versus zero-config convenience.
  Buildpacks are fine when the default tooling for your language matches what you actually use (pip for Python, npm for Node) and you don't care about the exact base image patch.
- Reach for a Dockerfile when your dependency manager isn't the buildpack's default (this project uses `uv`, which the Python buildpack doesn't install), or when you need an exact runtime patch version pinned for reproducibility.
- Concretely: since gcloud prefers a Dockerfile automatically, adding one does not change your deploy command, it only changes what gets built.

## Same-origin beats CORS, and beats a load balancer

- A Hosting (or CDN/gateway) rewrite that proxies `/api/**` to a backend service puts the frontend and the API behind one origin, so the browser never issues a CORS preflight at all.
- This also removes any reason to stand up a Load Balancer or an Identity-Aware Proxy just to get a shared domain in front of two services.
  Both carry fixed hourly costs and are overkill when a path-based rewrite does the same job for free.
- Ordering matters in the rewrite config: specific-path rules (`/api/**`) must be listed before a catch-all SPA fallback (`** -> /index.html`), or the catch-all swallows the API traffic.
- Consequence: once there is a CDN in front of your API, authenticated responses must carry `Cache-Control: private, no-store`, or the CDN can cache one user's response and serve it to another.
- The caveat that reverses this: a same-origin rewrite routes the API *through* the CDN, and a CDN buffers responses - which silently breaks Server-Sent Events and any streaming response, where the whole point is that bytes reach the browser frame by frame.
- So the rule is scoped to request/response APIs.
  The moment you add a streaming path, give *that* path a route that bypasses the CDN: a DNS-only (unproxied) subdomain straight to the origin.
  In this project the frontend stayed same-origin, but the streaming API moved to an `api.` subdomain wired as a Cloudflare grey-cloud (DNS-only) record to Cloud Run.
- That reintroduces CORS on the streaming path, which is a fine trade: CORS is a one-line middleware allowlist, still cheaper than the load balancer or IAP you were avoiding.
  You are trading "zero CORS" for "unbuffered stream," not for fixed infrastructure cost.

## Authentication and authorization are different layers

- Authentication (an identity provider like Firebase Auth, Google, Okta) proves who someone is.
  It should never be trusted to also decide what they're allowed to do.
- Authorization (an allowlist, a role table, a scope map) is a separate, app-level decision, checked after identity is verified.
  Keep it cheap (in-memory, no DB round-trip) if it sits in the path of unauthenticated or public traffic, so a flood of junk requests can't drain a paid resource (a database read, an LLM call) before your own code ever rejects them.
- This is why `--allow-unauthenticated` on a backend service is correct, not a shortcut, once the app enforces its own authorization.
  Adding IAM-level auth (IAP) on top would be redundant, and would reintroduce the load-balancer cost and CORS problems above.

## Service accounts must be created and granted explicitly

- A runtime service account is a resource like any other.
  Deploying with `--service-account=X` before `X` exists fails with a plain "does not exist" error, it is not auto-created for you.
- Local-dev identity and the production runtime identity are two different credential paths.
  Application Default Credentials from `gcloud auth application-default login` authorize your own machine; they say nothing about whether the service account a deployed service will run as has even been created yet.
- Grant roles at the narrowest scope that works, enumerated one at a time, rather than reaching for Editor or Owner.
  Write down the list (this project: Vertex AI user, Firestore user, log writer, log viewer, Secret Manager secret accessor on one specific secret) so the grant set is reviewable.
- Revisit the written list when a feature is removed, or it quietly becomes fiction.
  This project carried a Firebase Auth admin grant for months after the auth layer it existed for was deleted.

## Your build runs as an identity you never chose, and it ships with Editor

- Auditing the identities you created is the easy half; the dangerous grants sit on the accounts the platform created for you, because nobody ever decided to make them.
  On GCP, `gcloud run deploy --source` runs the build as the Compute Engine default service account, which is auto-created with `roles/editor` - so on an untouched project, "build my container" can read every database document and reconfigure most resources.
- A build identity is a supply-chain surface, not a deployment detail.
  Anything that can influence a build (a compromised base image, a dependency's install hook, an injected step) executes with whatever that account holds, no matter how small the project.
- Prefer the vendor's purpose-built role over a permission set you hand-derive.
  Google publishes `roles/run.builder` for exactly this path: six permissions (read the source object, upload/download/delete Artifact Registry artifacts, write log entries), and a curated role tracks the platform's own changes better than a list you maintain.
- Derive the requirement from the build itself, not from memory.
  `gcloud builds describe <ID>` shows the source bucket, steps, push target, and logging mode; those four facts are the permission list.
  Pass `--region` - `gcloud builds list` queries global by default and returns nothing for Cloud Run source deploys, which build in the service's region, so an empty list is not evidence that nothing is building.
- The build needs no deploy permission at all, which is easy to over-grant.
  In deploy-from-source the build only builds; the CLI performs the deploy under your own credentials, so neither `run.admin` nor `serviceAccountUser` belongs on the build identity.
- Tighten it safely: grant the narrow role first (respecting the propagation delay Google documents), then revoke the broad one, then prove it with a real deploy.
  Build-time and runtime identities are separate accounts, so this cannot disturb the running revision, and it reverses in one line - but an IAM change that has not survived a deploy is untested, not finished.
  Confirm first that the default SA is not also a runtime identity for Compute Engine, Cloud Functions, or a Cloud Run service deployed without an explicit `--service-account`.

## Secrets belong in Secret Manager

- Mount secrets into the runtime as `ENV_VAR=secret-name:version`, so the value never touches the container image, the Dockerfile, or a plaintext `--set-env-vars` flag.
- The runtime service account needs the secret-accessor role granted explicitly on that secret (or at the project level).
  It is not implied by other roles, including broad ones.
- A secret manager entry also gives you version history and rotation for free, which a baked-in or `.env`-shipped value does not.

## Two ignore files, two different jobs

- `.dockerignore` controls what enters the image build context.
  Miss it, and a secret or credential file can get baked into an image layer, which persists in the registry even if a later layer "deletes" it.
- A separate ignore file (Cloud Build's `.gcloudignore`, or your platform's equivalent) controls what gets uploaded to the build service in the first place, when deploying straight from source rather than a pre-built image.
  Miss this one, and a secret leaves your machine and lands in build service storage even though the image itself would never have contained it.
- Whenever a "deploy from source" flow exists (as opposed to "build locally, push, deploy"), check for both scopes of ignore file. They are easy to conflate and only one of them protects the upload step.

## gcloud's list-flag delimiter can silently corrupt values

- Flags like `--set-env-vars` split their argument on commas by default.
  A value that legitimately contains a comma (a serialized map, a CSV, a list-shaped config string) gets silently torn into the wrong number of pairs, with no error.
- Two fixes: the CLI's alternate-delimiter escape syntax for a one-off value, or, more robust when multiple variables or complex values are involved, a `--env-vars-file` (YAML) with no delimiter ambiguity at all.
- Separately: know whether your flag replaces the entire set or merges.
  `--set-env-vars` replaces all existing environment variables; a merge flag (`--update-env-vars`) exists for a reason. Picking the wrong one during an iterative deploy can silently delete unrelated config that a previous deploy had set.

## Scripted gcloud calls must never be able to prompt

- The CLI will interactively ask to enable a missing API ("...retry? (y/N)") by default.
  Fine in a terminal, fatal in a script.
- It gets worse if a "quiet" check redirects stdout/stderr to `/dev/null`: the prompt becomes invisible and the script just hangs forever, with no output pointing at the cause.
  This was a live incident, not a hypothetical: a preflight check in this project's deploy script hit exactly this and looked indistinguishable from a frozen process.
- Fix: pass the CLI's non-interactive flag (`--quiet`) on every call inside a script, and write explicit preflight checks (is the API enabled, does the service account exist, does the secret exist) that fail fast with a printed remediation command, instead of relying on the tool's own auto-enable-and-retry flow.

## Pin exact versions for reproducibility

- Pin your build tool's version in the Dockerfile to whatever produced your lockfile, not a floating `:latest` tag.
- Pin the base image to an exact patch version (`python:3.12.13-slim`, not `python:3.12-slim`) when the language runtime itself matters to reproducibility, and bump it as a deliberate act (a CVE fix), not automatically on every rebuild.
- This is the same supply-chain-determinism argument as a dependency lockfile: a floating tag means today's build is not guaranteed to be tomorrow's build, even with zero code changes.

## In a polyglot monorepo, each ecosystem owns its own tooling root

- A Python/uv backend and a TypeScript/pnpm frontend should each keep their own manifest and lockfile at their own root, not share one at the repo root.
- A root-level workspace file only earns its place if multiple packages actually live in that ecosystem.
  One JS package does not need a JS "workspace"; adding one anyway just misrepresents a half-Python repo as a JS monorepo for no benefit.
- Deploy config that genuinely spans multiple services (a Hosting config naming both the frontend build output and a backend rewrite target) belongs at the repo root regardless of the rule above, because its job is to describe the whole system, not one ecosystem's build.
  Scope, not location convention, decides where a config file lives.

## Verify CLI and console behavior against current docs

- Cloud CLI defaults, precedence rules, and console navigation drift continuously.
  Two concrete hits from this project alone: confirming that `gcloud run deploy --source` actually prefers a Dockerfile over buildpacks (verified against current docs rather than assumed), and a cloud console having moved a settings page (Authentication) under a different top-level menu (Security) than where older documentation and habit expected it.
- The cost of skipping verification is usually a silently wrong assumption, not a loud error.
  Assuming buildpacks were the "cheaper" choice here would have been wrong: both build on the same Cloud Build service with no cost delta, so the assumption would have driven a worse decision without ever surfacing as a bug.
- Practice: before writing infrastructure code or handing over a command, pull the current official doc page rather than relying on trained memory, especially for anything involving pricing, defaults, or precedence between two mechanisms.

## Verify what is deployed, not just what is committed

- A merged commit is not a running change.
  The live service keeps serving its last-deployed revision until you redeploy, so the repo and production can silently disagree - especially on a scale-to-zero service you are not actively watching.
- Probe the running system for the behavior you care about, rather than reasoning from `git log`.
  A cheap black-box probe usually exists: here, a CORS preflight (`curl -X OPTIONS` with an `Origin` header) returned `400 Disallowed CORS origin`, which proved the deployed revision predated the commit that widened the allowlist - long before any redeploy touched it.
- Confirm the gap precisely with `git merge-base --is-ancestor <commit> <deployed-sha>`: if that is false, the fix you assume is live simply is not.
- The practical rule for a cutover: when the frontend and backend must change together (a new cross-origin contract, a new CORS allowlist), redeploy both.
  Shipping only the frontend against a backend that predates the matching change is how you deploy a broken path with a green local test suite.
- Corollary: one doc page not answering a question is not the same as the answer not existing.
  A serverless compute service can hand back two different permanent URLs for the same deployed service: a deterministic one built from a project number and region (predictable before the service is even created, useful for wiring other config to it ahead of time), and a non-deterministic one built from an opaque per-service identifier.
  Both are valid and permanent for the life of the service; neither is "the real one."
  The first doc page fetched did not cover this, a second, more targeted search did, confirming it is documented behavior and not an inconsistency to worry about.

## The actual dials for cost vs. availability on a scale-to-zero service

- A minimum-instance count of zero is what makes idle cost zero, at the cost of a cold start (roughly 5 to 15 seconds is typical) on the first request after an idle period.
- A per-instance concurrency limit controls how many in-flight requests one instance absorbs before the platform spins up another.
  Too high risks one instance running out of memory under a heavy workload (an LLM call, a large payload); too low wastes instances on light ones.
- A maximum-instance cap bounds the blast radius of a traffic spike or a runaway client, on both your own cost and any downstream rate-limited dependency.
- Request timeout needs to be raised above the platform default for long-lived responses, such as Server-Sent Events or a slow model generation.

## Model-API feature constraints compose; verify the combination, not each feature alone

- LLM APIs constrain feature combinations, not just individual parameters: on Anthropic models, extended thinking rejects forced tool choice (`tool_choice: any/tool` errors when thinking is enabled) and pins sampling (temperature must stay at its default).
  Each feature works alone; the 400 only appears when they meet - and only at runtime, because mocked unit tests never hit the real endpoint.
- Framework abstractions hide which combination you are actually sending.
  LangChain's `with_structured_output` compiles to a forced tool choice under the hood, so "enable thinking" plus "use structured output" silently becomes an invalid request pair even though neither line of code mentions `tool_choice`.
  One grep through the installed adapter's source revealed this in seconds; the docs alone did not connect the two.
- A migration snippet drafted from one doc page can carry an invalid combination that no static check catches.
  Concrete hit here: the planned Claude-on-Vertex constructor paired `temperature=0.0` with thinking enabled; verifying the extended-thinking doc plus the adapter source forced a split - the thinking-on agent loop keeps default sampling, and the structured-output classifier keeps `temperature=0` but drops thinking.
- Practice: before swapping model providers, list the features each call site uses (thinking, structured output, forced tools, sampling pins), check the provider's compatibility rules for the pairs, and confirm with one live smoke call - the only layer where combination errors actually surface.

## A custom domain is not authorized for federated sign-in until you allowlist it

- A managed-auth provider's OAuth/popup sign-in checks the serving origin against a per-project authorized-domains allowlist before it will start the flow.
  The platform's own default hosting domains are on that list out of the box, so sign-in works there from day one and hides the gap.
  A custom domain you point at the same app is not added automatically - and the failure only shows up once you serve the app from that new origin.
- This produces a sign-in that works on one URL and fails on another for the same build, which reads like an app bug but is pure configuration.
  Here: sign-in worked on the default `*.web.app` origin and failed on the custom domain because only the former was in Firebase Auth's authorized domains; the fix is a one-line console addition (Authentication -> Settings -> Authorized domains), not a code change.
- The client SDK rejects an unlisted origin before opening the popup, so the tell is a specific, greppable error code (`auth/unauthorized-domain`), not a network or popup failure.
  Map that code to an actionable message that names the fix, rather than a generic "sign-in failed" - the next new domain you add will hit the same wall, and a message that says where to add it turns a debugging session into a thirty-second console edit.
- General rule for any hosting-plus-federated-auth cutover: the domain allowlist is a separate surface from DNS, TLS, and the app build.
  A custom domain resolving and serving over HTTPS does not mean auth will accept it; add the new origin to the auth provider's allowlist as an explicit step in the same cutover checklist.

## Referencing a bundler's whole env object embeds every env var in the shipped bundle

- Vite statically replaces `import.meta.env` at build time.
  Read it property-by-property (`import.meta.env.VITE_X`) and only the values you use are inlined; capture the whole object once (`const env = import.meta.env`) and the bundler embeds every `VITE_*` variable visible at build time - including values from a machine-local `.env.local` that the code no longer reads.
- The failure is silent because the app works either way; the leak only shows up if you grep the built artifact.
  Concrete hit here: after removing the Firebase auth layer, the prod bundle still contained the Firebase config strings because `config.ts` captured the whole env object; switching to per-key reads dropped them.
- Practice for any Vite (or similar static-replacement) frontend: read env vars per-key in the one config module, and add a post-build grep of `dist/` for values that should be gone as part of removal work.
  These are usually public identifiers, not secrets, but a removal is not done until the artifact is clean.

## A model quota grant is several quotas; probe the endpoint, don't trust the console

- Serving a partner-published model on a managed ML platform (here: Anthropic models on Vertex AI) is gated by multiple independent per-base-model quota metrics - requests per minute AND input tokens per minute - each scoped per region, plus a separate global-endpoint quota namespace.
  A grant that raises one metric in one scope still returns 429 if any other metric on the request path is zero.
- A console quota page can read as "unblocked" while the approval covers only a subset of metrics or regions, or has not yet propagated.
  Concrete hit here: the console showed the Anthropic-on-Vertex block lifted, but every live call failed - the global endpoint on `global_online_prediction_requests_per_base_model = 0`, the regional endpoints on `online_prediction_input_tokens_per_minute_per_base_model = 0`.
- The two cheapest diagnostics: read the metric name in the 429 body (it names the exact quota and base model to ask for), and probe one prompt per region x model - the error class distinguishes the cases (429 = served but no quota; 404/400 = model not offered in that region at all).
- Practice: after any quota-increase approval, run a single live smoke call on the exact model id and endpoint the workload uses before declaring the block cleared, and record the metric names from any remaining 429 - they are precisely what the follow-up quota request must name.

## Agent loops burst through per-minute token quotas, and graceful fallbacks hide it

- An agent loop multiplies one task into several model calls in quick succession: a classifier call plus one call per tool iteration, each resending the system prompt, every tool schema, and the growing conversation.
  A per-minute input-token quota that comfortably admits an ordinary chat request can be exhausted by a single task's burst, so pacing tasks apart cannot prevent 429s that occur inside one task.
- A retry policy is only as good as its cumulative horizon.
  The client library's default exponential backoff here summed to roughly 31 seconds, which can expire entirely inside one depleted minute-window; stretching the envelope past a full refill window (~123 seconds, via one client parameter) is the minimum that can work - and is still insufficient when the quota value itself sits below one request's size.
- The damaging failure mode was not the 429 but the masking: the serving path degrades a failed model call into a graceful fallback response, which is right for end users and wrong for measurement.
  Three evaluation passes here read as "completed" while their rows were fallback text; the tell was provenance, not status - a row with zero recorded tokens and no cost never touched the model.
- The 429 body names the exact metric and base model (here `global_generate_content_input_tokens_per_minute_per_base_model`), but neither the configured value nor the depletion state; bracket those empirically.
  Two probes bound the admission budget in minutes: a 7-token call succeeded instantly while a single ~2.5k-token call failed through a full 129-second retry ladder against an otherwise idle project - proof the effective admission budget sat below one ordinary request, which no client-side behavior can fix.
- Correction after root-causing: the starving quota was not a platform-set per-minute value at all but a **self-set per-day override** (60k tokens/day, left over from an early cost-guard experiment), which the 429's per-minute metric name gave no hint of.
  Newer Gemini models on Vertex admit via Dynamic Shared Quota with no per-minute token knob to raise, so the only project-side dial on that path is whatever override you set yourself - and a per-day cap does not refill by waiting a minute, which is why every pacing and backoff tactic failed.
- Practice: before a batch run, compute one task's burst profile (calls x input tokens per call) against the quota value; validate one task live before committing to the batch; treat zero-token "successes" as corrupt rows and discard that run's results; and when 429s persist against an idle project, stop tuning the client and audit the configured quota values - **including overrides your own project set**, which sit in the same console table as platform defaults and are the first thing to rule out.

## A system prompt tuned on one model family overfits its tool-calling habits

- A prompt that reliably drives tool use on the model family it was developed against can carry unstated assumptions that another family does not share: when to answer in prose versus calling a tool, whether to parallelize tool calls, and whether a final tool call may be replaced by a summary of what the tool would have said.
  Concrete hit here: an agent whose only sanctioned answer channel is a drafting tool worked flawlessly on Gemini, while Claude Haiku ended runs with well-written prose instead of the required tool call - 0/3 on the affected category, with nothing else different.
- The fix is to promote the implicit contract to an explicit protocol block in the system prompt: name the tool that is the only valid answer channel, state that ending in prose is a failed run, and pin the one-tool-per-turn expectation.
  That block cost nothing on the original family and took the second family to 3/3; a unit test now pins the protocol sentences so a prompt edit cannot silently drop them.
- Practice: treat cross-model portability of an agent prompt as a tested property, not an assumption; before comparing models through a shared harness, smoke each new family and read its transcripts for protocol drift rather than only scoring outcomes.

## An eval arm must bind every internal model call, not just the main loop

- Agent systems often make model calls the orchestration does not surface: classifier or router calls, structured-output extractions, summarizers inside tools.
  If a model-comparison harness swaps only the main loop's binding, those interior calls silently keep using the default model, and every arm's numbers become a blend.
- The failure compounds quietly: here, an interior classifier call kept running the production model inside the "compare a different model" arms, so token counts, latencies, and costs attributed to the candidate model partly measured the default one - and when the default model's quota died, healthy-looking candidate rows carried degraded classifications.
- The fix is structural, not procedural: thread the run's model binding through the same typed runtime context that carries tenancy, so any tool making an interior model call must read the bound model and cannot fall back to a global default.
  Then record per-row health for the interior call (intent, confidence, an errored flag) and make the report generator refuse rows whose interior call degraded.
- Practice: enumerate every model call a single task makes before trusting any per-model measurement, and prefer one seam that all of them resolve through; a comparison harness is only as honest as its least-visible model call.
