import type { NextConfig } from "next";

const config: NextConfig = {
  // Keep the repository's canonical AGENTS.md and CLAUDE.md authoritative.
  agentRules: false,
};

export default config;
