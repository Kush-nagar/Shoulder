import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

test("secret-bearing files are ignored and tracked/new source contains no credential patterns", () => {
  const examples = [
    ".env",
    ".env.local",
    ".env.remote",
    "supabase/.temp/project-ref",
    "supabase/.temp/postgres-version",
    "apps/web/.env.local",
    "supabase/.env.signing-keys.json",
    "services/api/.env",
    "infra/private.key",
    "infra/cert.pem",
    ".vercel/project.json",
  ];
  const ignored = execFileSync("git", ["check-ignore", "--stdin"], {
    input: examples.join("\n"),
    encoding: "utf8",
  })
    .trim()
    .split(/\r?\n/);
  assert.deepEqual(ignored, examples);
  const files = execFileSync(
    "git",
    ["ls-files", "--cached", "--others", "--exclude-standard", "-z"],
    { encoding: "utf8" },
  )
    .split("\0")
    .filter(Boolean);
  const credential =
    /(?:-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|\bAKIA[A-Z0-9]{16}\b|\bgh[pousr]_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b|\bsk_live_[A-Za-z0-9]{20,}\b)/;
  for (const file of files) {
    assert.ok(
      !/(^|\/)\.env(?:\.|$)/.test(file) || file.endsWith(".env.example"),
      `Secret file tracked: ${file}`,
    );
    assert.ok(
      !credential.test(readFileSync(file, "utf8")),
      `Possible credential in ${file}`,
    );
  }
});

test("local config, runtime version check, and stack contract agree on the Postgres major version", () => {
  // ADR 0015: one major version locally and in production, so local checks are
  // evidence for production migrations.
  const major = "17";
  assert.match(
    readFileSync("supabase/config.toml", "utf8"),
    new RegExp(`^major_version = ${major}$`, "m"),
  );
  assert.match(
    readFileSync("scripts/infra.ps1", "utf8"),
    new RegExp(`\\$version -notmatch '\\^${major}\\\\\\.\\d+'`),
  );
  assert.match(
    readFileSync("AGENTS.md", "utf8"),
    new RegExp(`^\\| Database \\| Postgres ${major} on Supabase;`, "m"),
  );
  assert.match(
    readFileSync("docs/03-schema.md", "utf8"),
    new RegExp(`^Postgres ${major} \\(`, "m"),
  );
});

test("local start removes only a conflicting linked Postgres version override", () => {
  const source = readFileSync("scripts/infra.ps1", "utf8");
  // Execute the actual start guard without Docker or the Supabase CLI.
  const start = source.indexOf("        $pinnedPostgres =");
  const end = source.indexOf("        $network =", start);
  assert.ok(
    start >= 0 && end > start,
    "Local Postgres version guard is missing",
  );
  const guard = source.slice(start, end);
  const images = readFileSync("infra/supabase-images.json", "utf8");
  const pinned = Object.keys(JSON.parse(images))
    .find((name) => name.includes("/postgres:"))
    .split(":")
    .at(-1);
  const quote = (value) => `'${value.replaceAll("'", "''")}'`;
  const root = mkdtempSync(join(tmpdir(), "shoulder-version-guard-"));
  try {
    for (const [name, version] of [
      ["mismatch", `${pinned}-hosted`],
      ["matching", `${pinned}\n`],
      ["missing", null],
    ]) {
      const workspace = join(root, name);
      const state = join(workspace, "supabase", ".temp");
      mkdirSync(state, { recursive: true });
      const versionFile = join(state, "postgres-version");
      if (version !== null) writeFileSync(versionFile, version);
      for (const file of ["project-ref", "pooler-url", "other-state"]) {
        writeFileSync(join(state, file), `preserve-${file}`);
      }
      execFileSync(process.platform === "win32" ? "powershell.exe" : "pwsh", [
        "-NoProfile",
        "-NonInteractive",
        "-Command",
        `$ErrorActionPreference = 'Stop'; Set-Location -LiteralPath ${quote(workspace)}; $images = ${quote(images)} | ConvertFrom-Json; ${guard}`,
      ]);
      assert.equal(existsSync(versionFile), name === "matching", name);
      if (name === "matching") {
        assert.equal(readFileSync(versionFile, "utf8"), version);
      }
      for (const file of ["project-ref", "pooler-url", "other-state"]) {
        assert.equal(
          readFileSync(join(state, file), "utf8"),
          `preserve-${file}`,
        );
      }
    }
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("font manifest pin and distributed license match the installed package", () => {
  const manifest = JSON.parse(readFileSync("apps/web/package.json", "utf8"));
  const installed = JSON.parse(
    readFileSync(
      "apps/web/node_modules/@fontsource-variable/inter-tight/package.json",
      "utf8",
    ),
  );
  assert.equal(
    manifest.dependencies["@fontsource-variable/inter-tight"],
    installed.version,
  );
  assert.match(installed.version, /^\d+\.\d+\.\d+$/);
  assert.equal(
    readFileSync("apps/web/public/licenses/inter-tight-OFL.txt", "utf8"),
    readFileSync(
      "apps/web/node_modules/@fontsource-variable/inter-tight/LICENSE",
      "utf8",
    ),
  );
});
