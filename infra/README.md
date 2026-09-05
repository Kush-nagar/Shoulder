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
