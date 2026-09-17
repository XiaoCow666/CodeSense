const MAX_BODY_BYTES = 512 * 1024;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function now() {
  return new Date().toISOString();
}

function timingSafeEqual(left, right) {
  if (!left || !right || left.length !== right.length) return false;
  let result = 0;
  for (let i = 0; i < left.length; i += 1) {
    result |= left.charCodeAt(i) ^ right.charCodeAt(i);
  }
  return result === 0;
}

async function sha256Hmac(secret, value) {
  const key = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    new TextEncoder().encode(value),
  );
  return Array.from(new Uint8Array(signature), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

async function verifyGithubSignature(request, rawBody, secret) {
  const supplied = request.headers.get("x-hub-signature-256") || "";
  const expected = `sha256=${await sha256Hmac(secret, rawBody)}`;
  return timingSafeEqual(supplied, expected);
}

function getDeliveryId(request, parsed) {
  return (
    request.headers.get("x-github-delivery") ||
    parsed?.header?.event_id ||
    parsed?.event_id ||
    null
  );
}

async function parseBody(request) {
  const raw = await request.text();
  if (new TextEncoder().encode(raw).byteLength > MAX_BODY_BYTES) {
    throw new Error("request body is too large");
  }
  try {
    return { raw, value: JSON.parse(raw) };
  } catch {
    throw new Error("request body must be valid JSON");
  }
}

async function enqueue(env, envelope) {
  const eventId = envelope.event_id || crypto.randomUUID();
  await env.EVENTS_QUEUE.send({
    ...envelope,
    event_id: eventId,
    queued_at: now(),
  });
  return eventId;
}

async function internalSecretMatches(request, env) {
  const secret = env.INTERNAL_RECONCILE_SECRET;
  if (!secret) return false;
  const authorization = request.headers.get("authorization") || "";
  return timingSafeEqual(authorization, `Bearer ${secret}`);
}

async function handleGithubWebhook(request, env) {
  if (!env.GITHUB_WEBHOOK_SECRET) {
    return json({ error: "github webhook secret is not configured" }, 503);
  }
  const { raw, value } = await parseBody(request);
  if (!(await verifyGithubSignature(request, raw, env.GITHUB_WEBHOOK_SECRET))) {
    return json({ error: "invalid github signature" }, 401);
  }

  const eventType = request.headers.get("x-github-event") || "unknown";
  const eventId = getDeliveryId(request, value) || crypto.randomUUID();
  const queuedId = await enqueue(env, {
    event_id: eventId,
    source: "github",
    event_type: eventType,
    delivery_id: eventId,
    payload: value,
  });
  return json({ accepted: true, event_id: queuedId });
}

async function handleFeishuEvent(request, env) {
  const { value } = await parseBody(request);
  if (value?.type === "url_verification") {
    if (
      env.FEISHU_VERIFICATION_TOKEN &&
      value.token !== env.FEISHU_VERIFICATION_TOKEN
    ) {
      return json({ error: "invalid feishu verification token" }, 401);
    }
    return json({ challenge: value.challenge });
  }

  const eventType = value?.header?.event_type || value?.event_type || "unknown";
  const eventId = value?.header?.event_id || value?.event_id || crypto.randomUUID();
  const queuedId = await enqueue(env, {
    event_id: eventId,
    source: "feishu",
    event_type: eventType,
    delivery_id: eventId,
    payload: value,
  });
  return json({ accepted: true, event_id: queuedId });
}

async function handleReconcile(request, env) {
  if (!(await internalSecretMatches(request, env))) {
    return json({ error: "invalid internal secret" }, 401);
  }
  let value = {};
  if (request.headers.get("content-length") !== "0") {
    try {
      value = (await parseBody(request)).value;
    } catch {
      value = {};
    }
  }
  const eventId = crypto.randomUUID();
  const queuedId = await enqueue(env, {
    event_id: eventId,
    source: "internal",
    event_type: "reconcile",
    delivery_id: eventId,
    payload: value,
  });
  return json({ accepted: true, event_id: queuedId });
}

async function persistEvent(env, message) {
  const event = message.body || {};
  const seenAt = now();
  const payload = JSON.stringify(event.payload ?? event);
  const result = await env.STATE_DB.prepare(
    `INSERT INTO event_inbox
      (event_id, source, event_type, delivery_id, payload_json, status,
       attempts, first_seen_at, last_seen_at)
     VALUES (?, ?, ?, ?, ?, 'queued', 1, ?, ?)
     ON CONFLICT(event_id) DO UPDATE SET
       last_seen_at = excluded.last_seen_at,
       attempts = event_inbox.attempts + 1`,
  )
    .bind(
      event.event_id || crypto.randomUUID(),
      event.source || "unknown",
      event.event_type || "unknown",
      event.delivery_id || null,
      payload,
      seenAt,
      seenAt,
    )
    .run();

  if (!result.success) throw new Error("failed to persist event");

  if (env.REVIEW_ENGINE_URL) {
    const headers = { "content-type": "application/json" };
    if (env.REVIEW_ENGINE_TOKEN) {
      headers.authorization = `Bearer ${env.REVIEW_ENGINE_TOKEN}`;
    }
    const response = await fetch(env.REVIEW_ENGINE_URL, {
      method: "POST",
      headers,
      body: JSON.stringify({
        event_id: event.event_id,
        source: event.source,
        event_type: event.event_type,
        payload: event.payload,
      }),
    });
    if (!response.ok) {
      throw new Error(`review engine returned ${response.status}`);
    }
  }

  await env.STATE_DB.prepare(
    "UPDATE event_inbox SET status = 'processed', processed_at = ?, error = NULL WHERE event_id = ?",
  )
    .bind(seenAt, event.event_id)
    .run();
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (request.method === "GET" && url.pathname === "/healthz") {
        return json({
          status: "ok",
          service: "codesense-project-automation",
          configured: {
            github_webhook: Boolean(env.GITHUB_WEBHOOK_SECRET),
            feishu_events: Boolean(env.FEISHU_VERIFICATION_TOKEN),
            reconcile: Boolean(env.INTERNAL_RECONCILE_SECRET),
            review_engine: Boolean(env.REVIEW_ENGINE_URL),
          },
          now: now(),
        });
      }
      if (request.method !== "POST") return json({ error: "not found" }, 404);
      if (url.pathname === "/webhooks/github") {
        return await handleGithubWebhook(request, env);
      }
      if (url.pathname === "/webhooks/feishu") {
        return await handleFeishuEvent(request, env);
      }
      if (url.pathname === "/internal/reconcile") {
        return await handleReconcile(request, env);
      }
      return json({ error: "not found" }, 404);
    } catch (error) {
      console.error("automation request failed", error);
      return json({ error: "request failed" }, 500);
    }
  },

  async queue(batch, env) {
    for (const message of batch.messages) {
      try {
        await persistEvent(env, message);
        message.ack();
      } catch (error) {
        console.error("automation queue message failed", error);
        message.retry();
      }
    }
  },
};
