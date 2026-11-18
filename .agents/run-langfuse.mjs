// Map the local Compose/app settings to the official Langfuse CLI environment.
import { existsSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { parseEnv } from "node:util";

const agentDirectory = dirname(fileURLToPath(import.meta.url));

export function cliEnvironment(shell, values) {
  const setting = (...names) => {
    for (const source of [shell, values]) {
      for (const name of names) {
        if (source[name]) return source[name];
      }
    }
  };
  const host =
    setting("LANGFUSE_BASE_URL", "LANGFUSE_HOST", "APP_LANGFUSE_BASE_URL") ||
    `http://127.0.0.1:${setting("LANGFUSE_PORT") || "3000"}`;
  const local = ["localhost", "127.0.0.1", "[::1]"].includes(
    new URL(host).hostname,
  );
  return {
    ...shell,
    LANGFUSE_HOST: host,
    LANGFUSE_BASE_URL: host,
    LANGFUSE_PUBLIC_KEY:
      setting("LANGFUSE_PUBLIC_KEY", "APP_LANGFUSE_PUBLIC_KEY") ||
      (local ? "pk-lf-template-local" : ""),
    LANGFUSE_SECRET_KEY:
      setting("LANGFUSE_SECRET_KEY", "APP_LANGFUSE_SECRET_KEY") ||
      (local ? "sk-lf-template-local" : ""),
  };
}

if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  const envPath = resolve(agentDirectory, "..", ".env");
  const values = existsSync(envPath)
    ? parseEnv(readFileSync(envPath, "utf8"))
    : {};
  const result = spawnSync(
    process.execPath,
    [
      resolve(
        agentDirectory,
        "tools/node_modules/@langfuse/cli/bin/langfuse.mjs",
      ),
      ...process.argv.slice(2),
    ],
    { env: cliEnvironment(process.env, values), stdio: "inherit" },
  );
  if (result.error) {
    console.error("Install the agent tools with make agent-install.");
  }
  process.exit(result.status ?? 1);
}
