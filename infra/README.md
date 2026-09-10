# Deployment preparation

Deployment is pending the owner's explicit follow-up approval. No cloud account,
resource, app, region, domain, or GitHub setting has been created or selected.
CI has no deployment job or cloud credentials.

## Vercel web

After approval, use the intended Vercel project with Root Directory `apps/web`,
Next.js framework, Node 24.x, and access to files outside the Root Directory.
The checked-in `apps/web/vercel.json` pins pnpm and uses the workspace lockfile.
Vercel controls the exact Node patch; local and CI use `.node-version`.
No Task 1 environment variables or secrets are needed.

Verify `/` on a phone and `/health` returns HTTP 200 with `{"status":"ok"}`.
Inspect font requests for same-origin WOFF2 and retrieve
`/licenses/inter-tight-OFL.txt` before accepting the deployment.

## Fly.io API

The Docker build context is the repository root. `infra/api.Dockerfile` installs
only locked production dependencies and runs as a non-root numeric user.
The allowlist `.dockerignore` excludes local secrets, tools, assets, and web code.
`infra/fly.toml` configures HTTPS and `/health`; it intentionally omits the app
name and region until the owner selects the destination and approves resource use.
Its Dockerfile path is relative to the configuration directory (`infra/`);
the Docker build context remains the repository root.

Only after that approval and CLI/account setup, from the repository root:

```powershell
fly deploy --config infra/fly.toml --app <approved-app-name> --primary-region <approved-region>
```

The expected public response is HTTP 200 with `{"status":"ok"}`. No database,
storage, auth, worker, volume, or secret is required. Docker/Fly/Vercel validation
and public phone health checks remain pending deployment approval and access.

References: [Fly configuration](https://fly.io/docs/reference/configuration/),
[Vercel monorepos](https://vercel.com/docs/monorepos),
[uv Docker integration](https://docs.astral.sh/uv/guides/integration/docker/).

## Private object storage

Project Block 2 adds the storage boundary. Locally it is the Compose MinIO in
`infra/compose.yaml`; in the target architecture it is a private Cloudflare R2
bucket reached through the same S3 API (`docs/02-architecture.md`).

Before any deployment, the bucket must be created with **no** public access and
its CORS list must name only the app origins. `infra/r2-cors.json` is that list
with the production origin left as a placeholder, because the owner has not
selected a domain. Apply it with the R2 dashboard or `wrangler`, then confirm
that an unlisted origin receives no `Access-Control-Allow-Origin` header;
`tests/test_storage.py` asserts the same property against MinIO locally.

The API and worker each read `R2_ENDPOINT_URL`, `R2_BUCKET`, `R2_REGION`,
`R2_ACCESS_KEY_ID`, and `R2_SECRET_ACCESS_KEY` from their own environment
(`services/api/.env.example`, `services/worker/.env.example`). The browser never
receives them: it only ever holds a presigned URL for one object, one verb, and
a short expiry.

## CPU worker

`services/worker/main.py` is a separate long-running process with no HTTP
surface. It connects as `shoulder_worker`, the least-privilege role migration
`0005` creates ([ADR 0018](../docs/decisions/0018-worker-database-role.md)), and
needs `WORKER_DATABASE_URL` plus the same `R2_*` values. It registers no job
handler until Task 11, so deploying it before then would start a process with
nothing to claim; its Fly configuration is deferred to that task with the ffmpeg
image it will need.
