const MAX_REQUEST_BYTES = 25 * 1024 * 1024 + 128 * 1024;
const TURNSTILE_ACTION = "research_upload";
const RATE_LIMIT = 3;
const RATE_WINDOW_MS = 60 * 60 * 1000;
const RECENT_COMPLETION_TTL_MS = 60 * 60 * 1000;
const PRIVATE_ORIGIN = "http://localhost:8000";

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,X-Turnstile-Token",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Vary": "Origin"
  };
}

function jsonResponse(payload, status, origin, extraHeaders = {}) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...corsHeaders(origin),
      ...extraHeaders
    }
  });
}

async function hashIp(ip, salt) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(salt),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(ip));
  return Array.from(
    new Uint8Array(signature),
    (byte) => byte.toString(16).padStart(2, "0")
  ).join("");
}

async function verifyTurnstile(request, env, ip) {
  const token = request.headers.get("X-Turnstile-Token") || "";
  if (
    !token ||
    token.length > 2048 ||
    !env.TURNSTILE_SECRET ||
    !env.TURNSTILE_EXPECTED_HOSTNAME
  ) {
    return false;
  }

  const body = new FormData();
  body.set("secret", env.TURNSTILE_SECRET);
  body.set("response", token);
  body.set("remoteip", ip);
  body.set("idempotency_key", crypto.randomUUID());

  try {
    const response = await fetch(
      "https://challenges.cloudflare.com/turnstile/v0/siteverify",
      { method: "POST", body }
    );
    if (!response.ok) return false;
    const result = await response.json();
    return result.success === true &&
      result.hostname === env.TURNSTILE_EXPECTED_HOSTNAME &&
      result.action === TURNSTILE_ACTION;
  } catch {
    return false;
  }
}

export class RateLimiter {
  constructor(state) {
    this.state = state;
  }

  async fetch() {
    const now = Date.now();
    const cutoff = now - RATE_WINDOW_MS;
    const stored = (await this.state.storage.get("timestamps")) || [];
    const timestamps = stored.filter((timestamp) => timestamp > cutoff);

    if (timestamps.length >= RATE_LIMIT) {
      const retryAfter = Math.max(1, Math.ceil((timestamps[0] + RATE_WINDOW_MS - now) / 1000));
      return new Response(null, {
        status: 429,
        headers: { "Retry-After": String(retryAfter) }
      });
    }

    timestamps.push(now);
    await this.state.storage.put("timestamps", timestamps);
    await this.state.storage.setAlarm(timestamps[0] + RATE_WINDOW_MS);
    return new Response(null, { status: 204 });
  }

  async alarm() {
    const now = Date.now();
    const timestamps = ((await this.state.storage.get("timestamps")) || [])
      .filter((timestamp) => timestamp > now - RATE_WINDOW_MS);
    if (timestamps.length === 0) {
      await this.state.storage.deleteAll();
      return;
    }
    await this.state.storage.put("timestamps", timestamps);
    await this.state.storage.setAlarm(timestamps[0] + RATE_WINDOW_MS);
  }
}

export class AnalysisCounter {
  constructor(state) {
    this.state = state;
  }

  async fetch(request) {
    if (request.method === "GET") {
      const count = Number(await this.state.storage.get("completedCount")) || 0;
      return Response.json({ completed_analyses: count });
    }

    if (request.method !== "POST") {
      return new Response(null, { status: 405 });
    }

    let payload;
    try {
      payload = await request.json();
    } catch {
      return Response.json({ detail: "Invalid request." }, { status: 400 });
    }

    const jobId = String(payload.job_id || "");
    if (!/^[0-9a-f]{32}$/.test(jobId)) {
      return Response.json({ detail: "Invalid job identifier." }, { status: 400 });
    }

    const now = Date.now();
    const cutoff = now - RECENT_COMPLETION_TTL_MS;
    const count = await this.state.storage.transaction(async (transaction) => {
      const stored = (await transaction.get("recentCompletions")) || {};
      const recentCompletions = Object.fromEntries(
        Object.entries(stored).filter(([, completedAt]) => completedAt > cutoff)
      );
      let completedCount = Number(await transaction.get("completedCount")) || 0;

      if (!(jobId in recentCompletions)) {
        recentCompletions[jobId] = now;
        completedCount += 1;
      }

      await transaction.put("completedCount", completedCount);
      await transaction.put("recentCompletions", recentCompletions);
      return completedCount;
    });
    await this.state.storage.setAlarm(now + RECENT_COMPLETION_TTL_MS);
    return Response.json({ completed_analyses: count });
  }

  async alarm() {
    const now = Date.now();
    const cutoff = now - RECENT_COMPLETION_TTL_MS;
    const stored = (await this.state.storage.get("recentCompletions")) || {};
    const recentCompletions = Object.fromEntries(
      Object.entries(stored).filter(([, completedAt]) => completedAt > cutoff)
    );

    if (Object.keys(recentCompletions).length === 0) {
      await this.state.storage.delete("recentCompletions");
      return;
    }

    await this.state.storage.put("recentCompletions", recentCompletions);
    const nextExpiry = Math.min(...Object.values(recentCompletions)) + RECENT_COMPLETION_TTL_MS;
    await this.state.storage.setAlarm(nextExpiry);
  }
}

function isAllowedRoute(method, pathname) {
  if (method === "GET" && pathname === "/health") return true;
  if (method === "GET" && pathname === "/v1/stats") return true;
  if (method === "POST" && pathname === "/v1/research-predictions") return true;
  if (["GET", "DELETE"].includes(method) && /^\/v1\/predictions\/[0-9a-f]{32}$/.test(pathname)) {
    return true;
  }
  return false;
}

function analysisCounter(env) {
  if (!env.ANALYSIS_COUNTER) return null;
  return env.ANALYSIS_COUNTER.get(env.ANALYSIS_COUNTER.idFromName("global"));
}

async function getAnalysisCount(env, allowedOrigin) {
  const counter = analysisCounter(env);
  if (!counter) {
    return jsonResponse({ detail: "Screening statistics are temporarily unavailable." }, 503, allowedOrigin);
  }
  try {
    const response = await counter.fetch("https://analysis-counter.internal/count");
    const payload = await response.json();
    return jsonResponse(payload, response.status, allowedOrigin);
  } catch {
    return jsonResponse({ detail: "Screening statistics are temporarily unavailable." }, 503, allowedOrigin);
  }
}

async function countCompletedAnalysis(env, jobId) {
  const counter = analysisCounter(env);
  if (!counter) return;
  try {
    await counter.fetch("https://analysis-counter.internal/completed", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId })
    });
  } catch {
    // A statistics failure must never prevent delivery of a screening result.
  }
}

async function proxyRequest(request, env, allowedOrigin) {
  const incomingUrl = new URL(request.url);
  const upstreamBase = new URL(PRIVATE_ORIGIN);
  const upstreamUrl = new URL(incomingUrl.pathname + incomingUrl.search, upstreamBase);
  const headers = new Headers({
    "Authorization": `Bearer ${env.ML_API_TOKEN}`,
    "Accept": "application/json"
  });
  const contentType = request.headers.get("Content-Type");
  if (contentType) headers.set("Content-Type", contentType);

  const init = {
    method: request.method,
    headers,
    redirect: "manual",
    body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body
  };
  try {
    const upstream = await env.ML_ORIGIN.fetch(upstreamUrl, init);
    const responseHeaders = new Headers(corsHeaders(allowedOrigin));
    responseHeaders.set("Content-Type", upstream.headers.get("Content-Type") || "application/json");
    const retryAfter = upstream.headers.get("Retry-After");
    if (retryAfter) responseHeaders.set("Retry-After", retryAfter);
    return new Response(upstream.body, { status: upstream.status, headers: responseHeaders });
  } catch {
    return jsonResponse(
      { detail: "Screening service temporarily offline. No prediction was generated." },
      503,
      allowedOrigin
    );
  }
}

export default {
  async fetch(request, env) {
    const origin = request.headers.get("Origin") || "";
    const allowedOrigin = env.ALLOWED_ORIGIN;
    if (!allowedOrigin || origin !== allowedOrigin) {
      return new Response("Origin not allowed", { status: 403 });
    }
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: corsHeaders(allowedOrigin) });
    }

    const url = new URL(request.url);
    if (!isAllowedRoute(request.method, url.pathname)) {
      return jsonResponse({ detail: "Not found." }, 404, allowedOrigin);
    }

    if (request.method === "GET" && url.pathname === "/v1/stats") {
      return getAnalysisCount(env, allowedOrigin);
    }

    if (!env.ML_API_TOKEN || !env.ML_ORIGIN) {
      return jsonResponse({ detail: "Screening service temporarily offline." }, 503, allowedOrigin);
    }

    if (request.method === "POST") {
      const lengthHeader = request.headers.get("Content-Length");
      const length = lengthHeader === null ? null : Number(lengthHeader);
      if (length !== null && (!Number.isFinite(length) || length < 0 || length > MAX_REQUEST_BYTES)) {
        return jsonResponse({ detail: "Upload exceeds the 25 MB limit." }, 413, allowedOrigin);
      }

      const ip = request.headers.get("CF-Connecting-IP") || "";
      if (!ip || !(await verifyTurnstile(request, env, ip))) {
        return jsonResponse({ detail: "Human verification failed." }, 403, allowedOrigin);
      }
      if (!env.RATE_LIMIT_SALT || !env.RATE_LIMITER) {
        return jsonResponse({ detail: "Screening service temporarily offline." }, 503, allowedOrigin);
      }

      const key = await hashIp(ip, env.RATE_LIMIT_SALT);
      const limiter = env.RATE_LIMITER.get(env.RATE_LIMITER.idFromName(key));
      const limit = await limiter.fetch("https://rate-limit.internal/");
      if (limit.status === 429) {
        return jsonResponse(
          { detail: "Three research screenings per hour are allowed." },
          429,
          allowedOrigin,
          { "Retry-After": limit.headers.get("Retry-After") || "3600" }
        );
      }
    }

    const response = await proxyRequest(request, env, allowedOrigin);
    const completedMatch = request.method === "GET"
      ? url.pathname.match(/^\/v1\/predictions\/([0-9a-f]{32})$/)
      : null;
    if (completedMatch && response.ok) {
      try {
        const job = await response.clone().json();
        if (job.status === "completed") {
          await countCompletedAnalysis(env, completedMatch[1]);
        }
      } catch {
        // Preserve the upstream response if its body cannot be inspected.
      }
    }
    return response;
  }
};
