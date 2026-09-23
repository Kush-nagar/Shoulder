import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

test("production browser assets contain no server auth configuration or session SDK", () => {
  const root = "apps/web/.next/static";
  const files = readdirSync(root, { recursive: true }).filter((file) =>
    file.endsWith(".js"),
  );
  assert.ok(files.length > 0, "Build the web app before the bundle check");
  for (const file of files) {
    const content = readFileSync(join(root, file), "utf8");
    assert.ok(
      !/SUPABASE_(?:SERVICE_ROLE|SECRET|PUBLISHABLE_KEY|AUTH_ISSUER|URL)|GOOGLE_CLIENT_(?:ID|SECRET)|GOCSPX-|API_BASE_URL|refresh_token|shoulder-auth/.test(
        content,
      ),
      `Server authentication content in browser asset: ${file}`,
    );
  }
});
