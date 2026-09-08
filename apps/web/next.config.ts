import type { NextConfig } from "next";

const config: NextConfig = {
  // Keep the repository's canonical AGENTS.md and CLAUDE.md authoritative.
  agentRules: false,
  // Development request logs otherwise include the PKCE callback query string.
  logging: { incomingRequests: { ignore: [/^\/auth\/callback(?:\?|$)/] } },
};

export default config;
