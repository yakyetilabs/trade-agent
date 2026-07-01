# GCP & Cloud Deployment: Lessons Learned

A running record of non-obvious, hard-won lessons from deploying this project to GCP.
Written to be portable: useful in a future enterprise GCP engagement or an interview, not just this repo.
Each entry states the general principle first, with a concrete aside from this project where useful.
This is a living document; keep appending as the deploy phase continues.

## Contents

- [A Firebase project is a GCP project](#a-firebase-project-is-a-gcp-project)
- [Dockerfile vs. buildpacks: the real trade-off is not cost](#dockerfile-vs-buildpacks-the-real-trade-off-is-not-cost)
- [Same-origin beats CORS, and beats a load balancer](#same-origin-beats-cors-and-beats-a-load-balancer)
- [Authentication and authorization are different layers](#authentication-and-authorization-are-different-layers)
- [Service accounts must be created and granted explicitly](#service-accounts-must-be-created-and-granted-explicitly)
- [Secrets belong in Secret Manager](#secrets-belong-in-secret-manager)
- [Two ignore files, two different jobs](#two-ignore-files-two-different-jobs)
- [gcloud's list-flag delimiter can silently corrupt values](#gclouds-list-flag-delimiter-can-silently-corrupt-values)
- [Scripted gcloud calls must never be able to prompt](#scripted-gcloud-calls-must-never-be-able-to-prompt)
- [Pin exact versions for reproducibility](#pin-exact-versions-for-reproducibility)
- [In a polyglot monorepo, each ecosystem owns its own tooling root](#in-a-polyglot-monorepo-each-ecosystem-owns-its-own-tooling-root)
- [Verify CLI and console behavior against current docs](#verify-cli-and-console-behavior-against-current-docs)
- [The actual dials for cost vs. availability on a scale-to-zero service](#the-actual-dials-for-cost-vs-availability-on-a-scale-to-zero-service)
- [Open questions / to verify next](#open-questions--to-verify-next)

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
  Write down the list (this project: Vertex AI user, Firestore user, log writer, log viewer, Firebase Auth admin, Secret Manager secret accessor on one specific secret) so the grant set is reviewable.

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
  Assuming buildpacks were the "cheaper" choice here would have been wrong: both build on the same free-tier build service, so the assumption would have driven a worse decision without ever surfacing as a bug.
- Practice: before writing infrastructure code or handing over a command, pull the current official doc page rather than relying on trained memory, especially for anything involving pricing, defaults, or precedence between two mechanisms.
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

## Open questions / to verify next

- Whether a Server-Sent Events stream survives a CDN-fronted Hosting layer fully unbuffered, end to end.
  The response headers are set correctly (`Cache-Control: no-store`, an unbuffering header for the origin), but this needs a live confirmation, not just a header check.
- Whether a third-party DNS proxy (Cloudflare's orange-cloud proxying) interferes with a managed TLS certificate provisioning flow (Firebase's custom-domain cert issuance), and whether that requires temporarily disabling the proxy during provisioning.
