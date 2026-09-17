# AgentOps Local Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the local execution layer (worktrees, headless Claude workers, verification, recovery, dashboard) around the existing AgentOps coordinator without changing any existing AgentOps module.

**Architecture:** Four new modules plus CLI verbs. `localstate` owns the ignored runtime store; `toolchain` owns pinned-uv resolution and the infra verification lock; `local` owns worktrees, the headless executor, the run loop and recovery; `dashboard` renders read-only HTML/JSON. Routing, classification, leases, briefs, governance and control-center rendering are consumed, never reimplemented.

**Tech Stack:** Python 3.11 stdlib only (no new dependency), `claude` CLI 2.1.268 headless, git worktrees, PowerShell wrappers, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-16-agentops-local-runtime-design.md`

## Global Constraints

- No new production dependency. Standard library only.
- `ops/policy.json`, `.github/workflows/*`, `AGENTS.md`, `CLAUDE.md`, `CODEOWNERS` are not modified.
- `max_parallel_writers` stays 1; the cap is read from policy, never hardcoded.
- All mutable runtime state lives under ignored `.agentops/local/`. Tracked `ops/state/*.json` is read-only baseline.
- `OPENROUTER_API_KEY` is read from `os.environ` at spawn time only: never persisted, printed, logged, or written to state. Absence yields status `AVAILABLE_LATER`.
- uv pin comes from `pyproject.toml` `required-version = "==0.12.10"`; every candidate binary is version-verified before use. No absolute machine path is committed.
- Liveness checks never call `os.kill(pid, 0)` on Windows (it terminates the process).
- `claude` invocation: `-p --output-format stream-json --verbose --permission-mode acceptEdits --permission-prompts none`. Never `--dangerously-skip-permissions`.
  - Superseded: writable roles now use `--dangerously-skip-permissions` and read-only roles use `--permission-mode plan`. See `docs/agentops-local-runtime.md`.
- Fable is unavailable (requires usage credits) and must never be selected.
- Task 15 is never started.
- Python style: `ruff format`, `ruff check`, `mypy` must pass. Tests are `unittest`, discovered by `python -m unittest discover -s tests -p "test_*.py"`.

---

### Task 1: Runtime store (`localstate`)

**Files:**
- Create: `services/agentops/localstate.py`
- Create: `tests/test_agentops_localstate.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `LocalPaths(root: Path)` with properties `dir`, `config`, `runtime`, `workers`, `leases`, `events`, `locks`, `runs`
  - `DEFAULT_CONFIG: dict[str, Any]`
  - `load_config(paths) -> dict`, `save_config(paths, cfg) -> None`
  - `read(path, default) -> dict`, `write(path, data) -> None` (atomic)
  - `append_event(paths, kind: str, **fields) -> dict`
  - `events(paths, limit: int = 50) -> list[dict]`
  - `redact(value: Any) -> Any`
  - `process_alive(pid: int | None, image: str | None = None) -> bool`
  - `SECRET_ENV_NAMES: tuple[str, ...]`

- [ ] **Step 1: Write the failing tests**

```python
class RedactionTests(unittest.TestCase):
    def test_redacts_known_secret_values_from_nested_payloads(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-secret"}):
            out = localstate.redact({"env": ["ANTHROPIC_AUTH_TOKEN=sk-or-secret"]})
        self.assertNotIn("sk-or-secret", json.dumps(out))

    def test_event_never_records_a_secret(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-secret"}):
            localstate.append_event(self.paths, "spawn", argv=["--token", "sk-or-secret"])
        self.assertNotIn("sk-or-secret", self.paths.events.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python -m unittest discover -s tests -p "test_agentops_localstate.py"` → `ModuleNotFoundError: services.agentops.localstate`

- [ ] **Step 3: Implement `localstate.py`**

Atomic write via temp file + `os.replace`. `redact` walks strings/lists/dicts replacing any non-empty value of `SECRET_ENV_NAMES` with `***`. `process_alive` uses `tasklist /FI "PID eq N" /NH` on win32 and `os.kill(pid, 0)` elsewhere.

- [ ] **Step 4: Run the tests and watch them pass**

- [ ] **Step 5: Add `.agentops/` to `.gitignore` and assert it with a test**

```python
def test_local_runtime_directory_is_ignored(self):
    out = subprocess.run(["git", "check-ignore", "-q", ".agentops/local/workers.json"], cwd=REPO)
    self.assertEqual(out.returncode, 0)
```

- [ ] **Step 6: Commit** — `git commit -m "Add the local AgentOps runtime store"`

---

### Task 2: Pinned uv resolver and verification lock (`toolchain`)

**Files:**
- Create: `services/agentops/toolchain.py`
- Create: `tests/test_agentops_toolchain.py`

**Interfaces:**
- Consumes: `localstate.LocalPaths`, `localstate.load_config`, `localstate.save_config`, `localstate.process_alive`.
- Produces:
  - `UvUnavailable(RuntimeError)`
  - `required_version(root: Path) -> str`
  - `candidates(root: Path, config: dict) -> list[tuple[str, Path]]`
  - `resolve_uv(root: Path, paths, *, probe=None) -> Path`
  - `LockBusy(RuntimeError)`
  - `infra_lock(paths, *, owner: str, ttl_seconds: int = 5400)` — context manager
  - `needs_infra_lock(command: list[str]) -> bool`
  - `run_fast_checks(root, uv: Path, *, runner=subprocess.run) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
def test_path_uv_with_wrong_version_is_rejected(self):
    with self.assertRaises(toolchain.UvUnavailable) as raised:
        toolchain.resolve_uv(self.root, self.paths, probe=lambda p: "uv 0.11.28")
    self.assertIn("0.12.10", str(raised.exception))

def test_configured_binary_with_matching_version_is_accepted_and_cached(self):
    found = toolchain.resolve_uv(self.root, self.paths, probe=lambda p: "uv 0.12.10")
    self.assertEqual(found, self.configured)
    self.assertEqual(localstate.load_config(self.paths)["uv_path"], str(self.configured))

def test_second_holder_is_refused_while_the_first_is_alive(self):
    with toolchain.infra_lock(self.paths, owner="a"):
        with self.assertRaises(toolchain.LockBusy):
            with toolchain.infra_lock(self.paths, owner="b"):
                pass

def test_lock_is_recovered_when_the_owner_process_is_gone(self):
    self.paths.locks.mkdir(parents=True, exist_ok=True)
    (self.paths.locks / "infra.lock").write_text(json.dumps({"pid": 999999, "owner": "dead"}))
    with toolchain.infra_lock(self.paths, owner="b") as taken:
        self.assertTrue(taken["recovered"])

def test_only_port_contending_commands_need_the_lock(self):
    self.assertTrue(toolchain.needs_infra_lock(["scripts/check.ps1"]))
    self.assertTrue(toolchain.needs_infra_lock(["scripts/check-db.ps1"]))
    self.assertFalse(toolchain.needs_infra_lock(["ruff", "check", "."]))
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement `toolchain.py`**

Resolution order: `SHOULDER_UV_PATH`, `config["uv_path"]`, repo `.tools/uv{,.exe}`, every `git worktree list --porcelain` path plus the common-dir parent, then PATH. Each candidate probed with `--version` and matched against the pin. Success is cached in config. Failure raises `UvUnavailable` naming the pin, the candidates tried, and the fix (`set SHOULDER_UV_PATH`).

Lock file created with `os.open(..., O_CREAT | O_EXCL)`; on `FileExistsError` the holder is read and taken only when its pid is gone or its `started_at` is older than the TTL; the takeover is recorded in the new lock payload as `recovered`.

- [ ] **Step 4: Run and watch them pass**

- [ ] **Step 5: Commit** — `git commit -m "Resolve the pinned uv and guard shared-port checks"`

---

### Task 3: Worktree lifecycle and headless Claude executor (`local`, part 1)

**Files:**
- Create: `services/agentops/local.py`
- Create: `tests/test_agentops_local.py`

**Interfaces:**
- Consumes: `localstate`, `toolchain`, `coordinator`, `routing`, `brief`, `governance`.
- Produces:
  - `ROLE_BUDGETS: dict[str, dict[str, int]]` (keys `implement`, `review`, `scout`, `summarize`; values `max_turns`, `timeout_seconds`)
  - `worktree_path(config, branch) -> Path`
  - `create_worktree(root, branch, path, *, base="HEAD", runner=subprocess.run) -> dict`
  - `remove_worktree(root, path, *, runner=subprocess.run) -> dict`
  - `provider_status(config) -> dict` with keys `provider`, `status`, `reason`
  - `child_env(config, base: Mapping[str, str]) -> dict[str, str]`
  - `executor_argv(model: str, role: str, worktree: Path, config) -> list[str]`
  - `run_worker(...) -> dict` with keys `ok`, `outcome`, `stop_reason`, `usage`, `cost_usd`, `session_id`, `events`

- [ ] **Step 1: Write the failing tests**

```python
def test_argv_carries_the_routed_model_and_the_role_turn_budget(self):
    argv = local.executor_argv("claude-sonnet-5", "implement", self.wt, cfg)
    self.assertEqual(argv[argv.index("--model") + 1], "claude-sonnet-5")
    self.assertIn("--max-turns", argv)
    self.assertIn("--verbose", argv)
    self.assertIn("stream-json", argv)
    self.assertNotIn("--dangerously-skip-permissions", argv)

def test_openrouter_is_available_later_without_a_key(self):
    with mock.patch.dict(os.environ, {}, clear=True):
        status = local.provider_status({"provider": "openrouter"})
    self.assertEqual(status["status"], "AVAILABLE_LATER")

def test_openrouter_environment_is_built_from_the_process_environment_only(self):
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-x"}, clear=True):
        env = local.child_env({"provider": "openrouter"}, os.environ)
    self.assertEqual(env["ANTHROPIC_BASE_URL"], "https://openrouter.ai/api")
    self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "sk-or-x")
    self.assertEqual(env["ANTHROPIC_API_KEY"], "")

def test_missing_openrouter_key_leaves_the_claude_provider_working(self):
    with mock.patch.dict(os.environ, {}, clear=True):
        env = local.child_env({"provider": "claude"}, os.environ)
    self.assertNotIn("ANTHROPIC_BASE_URL", env)
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement the worktree and executor half of `local.py`**

`run_worker` spawns the CLI with `cwd=worktree`, reads stdout line by line, parses each JSON line, appends it to `runs/<run_id>/stdout.jsonl`, records the last assistant text as `last_action`, and enforces the role's wall-clock timeout by terminating the child and returning `outcome="timeout"`. The `result` event supplies `stop_reason`, `usage`, `total_cost_usd` and `session_id`.

- [ ] **Step 4: Run and watch them pass**

- [ ] **Step 5: Commit** — `git commit -m "Run a local headless worker in its own worktree"`

---

### Task 4: Run loop, verification gate, recovery (`local`, part 2)

**Files:**
- Modify: `services/agentops/local.py`
- Modify: `tests/test_agentops_local.py`

**Interfaces:**
- Consumes: Task 3 output, `leases`, `state`, `governance`, `toolchain.run_fast_checks`.
- Produces:
  - `load_leases(root, paths) -> dict` (seeds from tracked `ops/state/tasks.json`, writes only to `.agentops/local/leases.json`)
  - `save_leases(paths, tasks) -> None`
  - `changed_paths(root, worktree, *, runner=subprocess.run) -> list[str]`
  - `verify(root, paths, worktree, *, kind="fast", runner=None) -> dict`
  - `classify_outcome(run: dict, verification: dict, violations: list[str]) -> str`
  - `recover(root, paths, *, runner=subprocess.run) -> dict`
  - `run_once(root, paths, *, dry_run: bool = False, ...) -> dict`

- [ ] **Step 1: Write the failing tests**

```python
def test_the_writer_cap_from_policy_is_enforced(self):
    # one active lease, max_parallel_writers = 1
    with self.assertRaises(leases.LeaseConflict):
        local.run_once(self.root, self.paths)["dispatched"]

def test_runtime_state_never_writes_tracked_ops_state(self):
    before = self.tasks_json.read_text(encoding="utf-8")
    local.run_once(self.root, self.paths, dry_run=True)
    self.assertEqual(self.tasks_json.read_text(encoding="utf-8"), before)

def test_verification_failure_blocks_completion(self):
    outcome = local.classify_outcome({"ok": True}, {"ok": False}, [])
    self.assertEqual(outcome, "verification_failed")

def test_a_governance_violation_is_refused(self):
    outcome = local.classify_outcome({"ok": True}, {"ok": True}, ["ops/policy.json"])
    self.assertEqual(outcome, "governance_refused")

def test_an_interrupted_worker_keeps_its_worktree(self):
    report = local.recover(self.root, self.paths)
    self.assertEqual(report["workers"][0]["state"], "interrupted")
    self.assertTrue(self.worktree.exists())
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement the loop half of `local.py`**

`run_once` refuses when `state.autonomy_enabled(policy)` is false unless `dry_run=True`. Order: context → candidate → plan → lease (existing module) → worktree → writer → `changed_paths` → `governance.violations` → `verify` → `classify_outcome` → lease release or `begin_repair` within the existing ceilings. Every transition appends an event.

- [ ] **Step 4: Run and watch them pass**

- [ ] **Step 5: Commit** — `git commit -m "Close the local lifecycle from lease to verdict"`

---

### Task 5: Read-only dashboard

**Files:**
- Create: `services/agentops/dashboard.py`
- Create: `tests/test_agentops_dashboard.py`

**Interfaces:**
- Consumes: `localstate`, `local`, `control_center`.
- Produces:
  - `DEFAULT_HOST = "127.0.0.1"`, `DEFAULT_PORT = 4317`
  - `snapshot(root, paths) -> dict`
  - `page(data: dict) -> str`
  - `build_server(root, paths, host, port) -> ThreadingHTTPServer`
  - `serve(root, paths, *, host, port) -> None`

- [ ] **Step 1: Write the failing tests**

```python
def test_a_mutating_request_is_refused(self):
    conn.request("POST", "/state"); self.assertEqual(conn.getresponse().status, 405)

def test_reading_the_dashboard_does_not_change_runtime_state(self):
    before = self.paths.workers.read_bytes()
    self.get("/"); self.get("/state")
    self.assertEqual(self.paths.workers.read_bytes(), before)

def test_the_page_never_contains_a_provider_secret(self):
    with mock.patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-secret"}):
        body = self.get("/")
    self.assertNotIn("sk-or-secret", body)
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement `dashboard.py`**

`GET /` renders vanilla HTML/CSS: coordinator row, current task, queue, worker cards (role, model, provider/lane, task, branch, worktree, phase, elapsed, last action, verification), failures/escalations, usage totals, recent events, and the existing `control_center.render()` output inside an escaped `<pre>` panel (rendered defensively — a `gh` failure must not fail the page). `GET /state` returns the same dict as JSON. Anything else: 405. `<meta http-equiv="refresh" content="5">`.

- [ ] **Step 4: Run and watch them pass**

- [ ] **Step 5: Commit** — `git commit -m "Show the local runtime on a read-only page"`

---

### Task 6: CLI verbs and PowerShell wrappers

**Files:**
- Modify: `services/agentops/cli.py`
- Create: `scripts/agentops-local.ps1`
- Create: `scripts/agentops-provider.ps1`
- Modify: `tests/test_agentops_local.py`

**Interfaces:**
- Consumes: `local`, `dashboard`, `localstate`, `toolchain`.
- Produces: `agentops run [--dry-run] [--once] [--interval N]`, `agentops serve [--host H] [--port P]`, `agentops resume`, `agentops provider [claude|openrouter|status]`, `agentops stop`; `status` gains a `local` block.

- [ ] **Step 1: Write the failing tests**

```python
def test_run_refuses_while_autonomy_is_disabled(self):
    code = cli.main(["run", "--once", "--root", str(self.root)])
    self.assertEqual(code, 0)
    self.assertIn("AUTONOMY_ENABLED is false", self.stdout.getvalue())

def test_provider_status_reports_available_later_without_a_key(self):
    with mock.patch.dict(os.environ, {}, clear=True):
        cli.main(["provider", "status", "--root", str(self.root)])
    self.assertIn("AVAILABLE_LATER", self.stdout.getvalue())
```

- [ ] **Step 2: Run and watch them fail**

- [ ] **Step 3: Implement the CLI commands and the two wrappers**

`agentops-local.ps1 start|stop|status|resume` and `agentops-provider.ps1 claude|openrouter|status` are thin argument maps over the CLI — no duplicated logic.

- [ ] **Step 4: Run and watch them pass**

- [ ] **Step 5: Commit** — `git commit -m "Add the local runtime commands"`

---

### Task 7: Dry run, full verification, documentation

**Files:**
- Create: `docs/agentops-local-runtime.md`
- Modify: `tests/test_agentops_local.py` (dry-run lifecycle assertions)

- [ ] **Step 1: Run the whole AgentOps suite** — `uv run --locked python -m unittest discover -s tests -p "test_agentops_*.py"`; expect 481 existing plus the new tests, zero failures.
- [ ] **Step 2: Run `ruff format --check`, `ruff check`, `mypy`.**
- [ ] **Step 3: Execute the dry-run lifecycle** — synthetic task, throwaway branch, real harmless headless Claude call inside its own worktree, events, verification, dashboard visibility, cleanup. Never Task 15, never a push.
- [ ] **Step 4: Dashboard smoke** — start `serve`, fetch `/` and `/state`, confirm 405 on POST, stop.
- [ ] **Step 5: Secret scan** — grep the diff and `.agentops/` for key material; confirm nothing but env-var *names* appears.
- [ ] **Step 6: `git diff --check`, `git status --short`, read the full diff.**
- [ ] **Step 7: Write `docs/agentops-local-runtime.md`** — start/stop/status/resume, provider switch, the OpenRouter key command, uv resolution order, where state lives.
- [ ] **Step 8: Commit** — `git commit -m "Document and verify the local runtime"`
