import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";

test("secret-bearing files are ignored and tracked/new source contains no credential patterns", () => {
  const examples = [
    ".env",
    ".env.local",
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
