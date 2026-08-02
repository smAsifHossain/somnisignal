import assert from "node:assert/strict";
import test from "node:test";

import worker, { RateLimiter } from "../src/index.js";

const ORIGIN = "https://smasifhossain.github.io";

function baseEnv() {
  return {
    ALLOWED_ORIGIN: ORIGIN,
    ML_API_TOKEN: "x".repeat(64),
    ML_ORIGIN: {
      fetch: async () => Response.json({ status: "healthy" })
    },
    TURNSTILE_SECRET: "secret",
    TURNSTILE_EXPECTED_HOSTNAME: "smasifhossain.github.io",
    RATE_LIMIT_SALT: "salt",
    RATE_LIMITER: {
      idFromName: (name) => name,
      get: () => ({ fetch: async () => new Response(null, { status: 204 }) })
    }
  };
}

function request(path, init = {}) {
  return new Request(`https://worker.example${path}`, {
    ...init,
    headers: {
      Origin: ORIGIN,
      ...(init.headers || {})
    }
  });
}

test("rejects untrusted origins and the reserved upload route", async () => {
  const env = baseEnv();
  const wrongOrigin = await worker.fetch(new Request("https://worker.example/health", {
    headers: { Origin: "https://attacker.example" }
  }), env);
  assert.equal(wrongOrigin.status, 403);

  const reservedUpload = await worker.fetch(request("/v1/predictions", { method: "POST" }), env);
  assert.equal(reservedUpload.status, 404);
});

test("research upload requires a valid Turnstile hostname and action", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = async (url) => {
    assert.match(String(url), /siteverify/);
    return Response.json({ success: true, hostname: "wrong.example", action: "research_upload" });
  };

  const response = await worker.fetch(request("/v1/research-predictions", {
    method: "POST",
    headers: {
      "CF-Connecting-IP": "192.0.2.10",
      "X-Turnstile-Token": "token"
    },
    body: new FormData()
  }), baseEnv());
  assert.equal(response.status, 403);
});

test("forwards only the protected research route with the private bearer token", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  let upstreamAuthorization = "";
  let upstreamUrl = "";
  globalThis.fetch = async (url) => {
    assert.match(String(url), /siteverify/);
    return Response.json({
      success: true,
      hostname: "smasifhossain.github.io",
      action: "research_upload"
    });
  };
  const env = baseEnv();
  env.ML_ORIGIN.fetch = async (url, init) => {
    upstreamUrl = String(url);
    upstreamAuthorization = new Headers(init.headers).get("Authorization");
    return Response.json({ job_id: "a".repeat(32), status: "queued" }, { status: 202 });
  };

  const body = new FormData();
  body.set("adult_confirmed", "true");
  const response = await worker.fetch(request("/v1/research-predictions", {
    method: "POST",
    headers: {
      "CF-Connecting-IP": "192.0.2.10",
      "X-Turnstile-Token": "token"
    },
    body
  }), env);

  assert.equal(response.status, 202);
  assert.equal(upstreamUrl, "http://localhost:8000/v1/research-predictions");
  assert.equal(upstreamAuthorization, `Bearer ${"x".repeat(64)}`);
  assert.equal(response.headers.get("Access-Control-Allow-Origin"), ORIGIN);
});

test("enforces a rolling three-request hourly limit", async () => {
  const values = new Map();
  const storage = {
    get: async (key) => values.get(key),
    put: async (key, value) => { values.set(key, value); },
    setAlarm: async () => {},
    deleteAll: async () => { values.clear(); }
  };
  const limiter = new RateLimiter({ storage });
  assert.equal((await limiter.fetch()).status, 204);
  assert.equal((await limiter.fetch()).status, 204);
  assert.equal((await limiter.fetch()).status, 204);
  const blocked = await limiter.fetch();
  assert.equal(blocked.status, 429);
  assert.ok(Number(blocked.headers.get("Retry-After")) > 0);
});

test("rejects an oversized multipart request before verification", async () => {
  const response = await worker.fetch(request("/v1/research-predictions", {
    method: "POST",
    headers: { "Content-Length": String(26 * 1024 * 1024) },
    body: "x"
  }), baseEnv());
  assert.equal(response.status, 413);
});
