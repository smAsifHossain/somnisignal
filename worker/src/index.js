const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

function corsHeaders(origin) {
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,X-Turnstile-Token",
    "Access-Control-Max-Age": "86400",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff"
  };
}

function jsonResponse(payload, status, origin) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...corsHeaders(origin) }
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
  return Array.from(new Uint8Array(signature), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function verifyTurnstile(request, env, ip) {
  const token = request.headers.get("X-Turnstile-Token") || "";
  if (!token || !env.TURNSTILE_SECRET) return false;
  const body = new FormData();
  body.set("secret", env.TURNSTILE_SECRET);
  body.set("response", token);
  body.set("remoteip", ip);
  const response = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
    method: "POST",
    body
  });
  if (!response.ok) return false;
  const result = await response.json();
  return result.success === true;
}

export class RateLimiter {
  constructor(state) {
    this.state = state;
  }

  async fetch() {
    const currentHour = Math.floor(Date.now() / 3_600_000);
    const stored = (await this.state.storage.get("counter")) || { hour: currentHour, count: 0 };
    const counter = stored.hour === currentHour ? stored : { hour: currentHour, count: 0 };
    if (counter.count >= 3) {
      return new Response(null, { status: 429 });
    }
    counter.count += 1;
    await this.state.storage.put("counter", counter, { expirationTtl: 3700 });
    return new Response(null, { status: 204 });
  }
}

async function proxyRequest(request, env, allowedOrigin) {
  const incomingUrl = new URL(request.url);
  const upstreamBase = new URL(env.ML_API_BASE_URL);
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
    const upstream = await fetch(upstreamUrl, init);
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
    const allowedPath = url.pathname === "/health" ||
      url.pathname === "/v1/demo-predictions" ||
      url.pathname === "/v1/predictions" ||
      /^\/v1\/predictions\/[0-9a-f]{32}$/.test(url.pathname);
    if (!allowedPath || !["GET", "POST", "DELETE"].includes(request.method)) {
      return jsonResponse({ detail: "Not found." }, 404, allowedOrigin);
    }

    if (request.method === "POST") {
      const length = Number(request.headers.get("Content-Length") || "0");
      if (length > MAX_UPLOAD_BYTES) {
        return jsonResponse({ detail: "Upload exceeds the 25 MB limit." }, 413, allowedOrigin);
      }
      const ip = request.headers.get("CF-Connecting-IP") || "unknown";
      if (!(await verifyTurnstile(request, env, ip))) {
        return jsonResponse({ detail: "Human verification failed." }, 403, allowedOrigin);
      }
      const key = await hashIp(ip, env.RATE_LIMIT_SALT);
      const limiter = env.RATE_LIMITER.get(env.RATE_LIMITER.idFromName(key));
      const limit = await limiter.fetch("https://rate-limit.internal/");
      if (limit.status === 429) {
        return jsonResponse({ detail: "Hourly screening limit reached." }, 429, allowedOrigin);
      }
    }

    return proxyRequest(request, env, allowedOrigin);
  }
};
