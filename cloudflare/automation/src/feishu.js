const FEISHU_API_BASE = "https://open.feishu.cn";
let tenantTokenCache = { token: "", expiresAt: 0 };

function textValue(value) {
  return typeof value === "string" ? value : value == null ? "" : String(value);
}

function eventRoot(payload) {
  return payload?.event || payload || {};
}

function openId(value) {
  if (!value) return null;
  if (typeof value === "string") return value;
  return value.open_id || value.user_id || value.union_id || null;
}

export function messageText(message) {
  const content = message?.content;
  if (typeof content !== "string") return textValue(content);
  try {
    const parsed = JSON.parse(content);
    return parsed.text || parsed.content || content;
  } catch {
    return content;
  }
}

export function feishuDetails(payload) {
  const root = eventRoot(payload);
  const message = root.message || payload?.message || {};
  const sender = root.sender || payload?.sender || {};
  const senderId = openId(sender.sender_id || sender.senderId || sender.user_id || sender);
  const mentions = Array.isArray(message.mentions) ? message.mentions : [];
  const users = Array.isArray(root.users) ? root.users : [];
  const member = users[0] || root.user || {};
  return {
    eventType: payload?.header?.event_type || payload?.event_type || "unknown",
    messageId: message.message_id || message.messageId || null,
    chatId: message.chat_id || root.chat_id || payload?.chat_id || null,
    senderOpenId: senderId,
    text: messageText(message),
    mentions,
    memberOpenId: openId(member.user_id || member.user || member),
    memberName: textValue(member.name || member.user_name || member.display_name || member.en_name || "新成员"),
  };
}

export function isDirectMention(payload, botOpenId) {
  const details = feishuDetails(payload);
  if (details.mentions.some((item) => openId(item.id || item.user_id) === botOpenId)) return true;
  if (!botOpenId) return /@(?:牛顿|CodeX|Codex)/i.test(details.text);
  return false;
}

export function isSevereTaskIssue(payload) {
  const details = feishuDetails(payload);
  return /阻塞|无法提交|重复提交|权限申请|权限打不开|任务台.*错误|PR.*冲突|合并失败|一直不通过/i.test(details.text);
}

export function shouldHandleMessage(payload, botOpenId) {
  return isDirectMention(payload, botOpenId) || isSevereTaskIssue(payload);
}

function apiError(method, path, status, code) {
  return new Error(`feishu api ${method} ${path.split("?")[0]} returned ${status}/${code}`);
}

export async function getFeishuTenantToken(env) {
  if (!env.FEISHU_APP_ID || !env.FEISHU_APP_SECRET) throw new Error("feishu app credentials are not configured");
  if (tenantTokenCache.token && tenantTokenCache.expiresAt > Date.now() + 60000) return tenantTokenCache.token;
  const response = await fetch(`${FEISHU_API_BASE}/open-apis/auth/v3/tenant_access_token/internal`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ app_id: env.FEISHU_APP_ID, app_secret: env.FEISHU_APP_SECRET }),
  });
  const value = await response.json();
  if (!response.ok || value.code !== 0 || !value.tenant_access_token) throw apiError("POST", "/open-apis/auth/v3/tenant_access_token/internal", response.status, value.code ?? "unknown");
  tenantTokenCache = { token: value.tenant_access_token, expiresAt: Date.now() + Math.max(60000, Number(value.expire || 7200) * 1000) };
  return tenantTokenCache.token;
}

export async function feishuApi(env, method, path, body) {
  const token = await getFeishuTenantToken(env);
  const headers = { authorization: `Bearer ${token}`, "content-type": "application/json; charset=utf-8" };
  const options = { method, headers };
  if (body !== undefined) options.body = JSON.stringify(body);
  const response = await fetch(`${FEISHU_API_BASE}${path}`, options);
  const value = await response.json().catch(() => ({}));
  if (!response.ok || (value.code !== undefined && value.code !== 0)) throw apiError(method, path, response.status, value.code ?? "unknown");
  return value;
}

function messageContent(text) {
  return JSON.stringify({ text: textValue(text).slice(0, 30000) });
}

function uuidQuery(idempotencyKey) {
  const key = textValue(idempotencyKey).replace(/[^A-Za-z0-9:_-]/g, "_").slice(0, 50);
  return key ? `?uuid=${encodeURIComponent(key)}` : "";
}

export async function sendFeishuText(env, receiveIdType, receiveId, text, idempotencyKey) {
  if (!receiveId) throw new Error("feishu recipient is missing");
  const query = new URLSearchParams({ receive_id_type: receiveIdType });
  if (idempotencyKey) query.set("uuid", textValue(idempotencyKey).replace(/[^A-Za-z0-9:_-]/g, "_").slice(0, 50));
  return feishuApi(env, "POST", `/open-apis/im/v1/messages?${query.toString()}`, { receive_id: receiveId, msg_type: "text", content: messageContent(text) });
}

export async function replyFeishuText(env, messageId, text, idempotencyKey) {
  if (!messageId) throw new Error("feishu message id is missing");
  return feishuApi(env, "POST", `/open-apis/im/v1/messages/${encodeURIComponent(messageId)}/reply${uuidQuery(idempotencyKey)}`, { msg_type: "text", content: messageContent(text) });
}

export function formatMentionReply(text) {
  return textValue(text).trim().slice(0, 30000) || "我收到啦。请把任务名称、PR 编号或具体报错一起发来，我才能准确接着处理。";
}

export function formatMemberOnboarding(projectName, memberName, taskUrl) {
  const link = taskUrl ? `\n任务台入口：${taskUrl}` : "";
  return `欢迎 ${memberName} 加入 ${projectName}。先完成阶段一：阅读项目、跑通启动和测试命令，再提交一份项目理解与架构分析 PR。请把你亲自看到的目录、调用链、运行结果和疑问写进 PR，AI 可以帮你查资料，但结论要由你自己验证。${link}`;
}

export function formatOwnerAlert(title, detail) {
  return `自动流程需要你看一下：${title}\n\n${textValue(detail).slice(0, 8000)}`;
}
