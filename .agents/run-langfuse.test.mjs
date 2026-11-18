import assert from "node:assert/strict";
import { test } from "node:test";
import { cliEnvironment } from "./run-langfuse.mjs";

test("shell URL and keys override dotenv values across APP aliases", () => {
  const env = cliEnvironment(
    {
      APP_LANGFUSE_BASE_URL: "https://remote.example.test",
      APP_LANGFUSE_PUBLIC_KEY: "shell-public",
      APP_LANGFUSE_SECRET_KEY: "shell-secret",
    },
    {
      LANGFUSE_HOST: "http://localhost:3000",
      LANGFUSE_PUBLIC_KEY: "dotenv-public",
      LANGFUSE_SECRET_KEY: "dotenv-secret",
    },
  );
  assert.equal(env.LANGFUSE_HOST, "https://remote.example.test");
  assert.equal(env.LANGFUSE_PUBLIC_KEY, "shell-public");
  assert.equal(env.LANGFUSE_SECRET_KEY, "shell-secret");
});

test("BASE_URL takes precedence over HOST within the same source", () => {
  const env = cliEnvironment(
    {
      LANGFUSE_BASE_URL: "https://preferred.example.test",
      LANGFUSE_HOST: "https://other.example.test",
    },
    {},
  );
  assert.equal(env.LANGFUSE_HOST, "https://preferred.example.test");
  assert.equal(env.LANGFUSE_BASE_URL, env.LANGFUSE_HOST);
});

test("external URLs never receive fallback local development keys", () => {
  const env = cliEnvironment(
    {},
    { LANGFUSE_HOST: "https://remote.example.test" },
  );
  assert.equal(env.LANGFUSE_PUBLIC_KEY, "");
  assert.equal(env.LANGFUSE_SECRET_KEY, "");
});

test("local defaults follow the Compose port", () => {
  const env = cliEnvironment({}, { LANGFUSE_PORT: "3010" });
  assert.equal(env.LANGFUSE_HOST, "http://127.0.0.1:3010");
  assert.equal(env.LANGFUSE_PUBLIC_KEY, "pk-lf-template-local");
  assert.equal(env.LANGFUSE_SECRET_KEY, "sk-lf-template-local");
});

test("explicit local project credentials override the development defaults", () => {
  const env = cliEnvironment(
    {},
    {
      LANGFUSE_PUBLIC_KEY: "custom-public",
      LANGFUSE_SECRET_KEY: "custom-secret",
    },
  );
  assert.equal(env.LANGFUSE_PUBLIC_KEY, "custom-public");
  assert.equal(env.LANGFUSE_SECRET_KEY, "custom-secret");
});
