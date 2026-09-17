import { feishuApi } from "./feishu.js";

const FIELD_NAMES = {
  title: "任务名称",
  description: "任务说明",
  status: "状态",
  assignee: "负责人",
  reviewer: "评审人",
  priority: "优先级",
  pr: "GitHub PR / Issue",
  type: "任务类型",
  mode: "任务模式",
  area: "项目区域",
  target: "问题/目标",
  evidence: "复现与证据",
  blocked: "阻塞原因",
  due: "截止日期",
  plan: "计划改动",
  learning: "学习总结",
  verification: "验证结果",
  relatedDoc: "关联文档",
  acceptance: "验收标准",
};

const CHINESE_STAGES = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二", "十三", "十四"];
const PROJECT_ENV = {
  codesense: { key: "codesense", name: "CodeSense", repository: "XiaoCow666/CodeSense", baseToken: "FEISHU_CODESENSE_BASE_TOKEN", tableId: "FEISHU_CODESENSE_TASK_TABLE_ID", wikiParent: "FEISHU_CODESENSE_WIKI_PARENT_TOKEN", chatIds: "FEISHU_CODESENSE_CHAT_IDS" },
  caifusi: { key: "caifusi", name: "Caifusi", repository: "XiaoCow666/Caifusi", baseToken: "FEISHU_CAIFUSI_BASE_TOKEN", tableId: "FEISHU_CAIFUSI_TASK_TABLE_ID", wikiParent: "FEISHU_CAIFUSI_WIKI_PARENT_TOKEN", chatIds: "FEISHU_CAIFUSI_CHAT_IDS" },
};

function valueText(value) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(valueText).join(", ");
  if (typeof value === "object") return value.name || value.text || value.id || JSON.stringify(value);
  return String(value);
}

function fieldsForProject(env, project) {
  const baseToken = env[project.baseToken];
  const tableId = env[project.tableId];
  const wikiParent = env[project.wikiParent];
  if (!baseToken || !tableId || !wikiParent) throw new Error(`${project.key} Feishu resource identifiers are not configured`);
  return { baseToken, tableId, wikiParent };
}

export function projectForRepository(env, repository) {
  const value = String(repository || "").toLowerCase();
  return Object.values(PROJECT_ENV).find((project) => project.repository.toLowerCase() === value) || null;
}

export function projectForChat(env, chatId) {
  if (!chatId) return null;
  return Object.values(PROJECT_ENV).find((project) => String(env[project.chatIds] || "").split(",").map((item) => item.trim()).filter(Boolean).includes(chatId)) || null;
}

async function listRecords(env, project) {
  const { baseToken, tableId } = fieldsForProject(env, project);
  const records = [];
  let offset = 0;
  while (true) {
    const query = new URLSearchParams({ limit: "200", offset: String(offset) });
    const response = await feishuApi(env, "GET", `/open-apis/base/v3/bases/${encodeURIComponent(baseToken)}/tables/${encodeURIComponent(tableId)}/records?${query.toString()}`);
    const data = response.data || {};
    const names = Array.isArray(data.fields) ? data.fields : [];
    const rows = Array.isArray(data.data) ? data.data : [];
    const ids = Array.isArray(data.record_id_list) ? data.record_id_list : [];
    rows.forEach((row, index) => {
      const fields = {};
      names.forEach((name, fieldIndex) => { fields[name] = row[fieldIndex] ?? null; });
      records.push({ record_id: ids[index] || null, fields });
    });
    if (!data.has_more || rows.length === 0) break;
    offset += rows.length;
    if (offset > 2000) throw new Error(`${project.key} task table exceeded the safe read limit`);
  }
  return records.filter((record) => record.record_id);
}

async function createRecord(env, project, fields) {
  const { baseToken, tableId } = fieldsForProject(env, project);
  const response = await feishuApi(env, "POST", `/open-apis/base/v3/bases/${encodeURIComponent(baseToken)}/tables/${encodeURIComponent(tableId)}/records/batch_create`, { create_records: [fields] });
  const ids = response.data?.record_id_list || response.data?.records?.map((record) => record.record_id) || [];
  if (!ids[0]) throw new Error(`${project.key} task table did not return a record id`);
  return ids[0];
}

async function updateRecord(env, project, recordId, fields) {
  const { baseToken, tableId } = fieldsForProject(env, project);
  return feishuApi(env, "POST", `/open-apis/base/v3/bases/${encodeURIComponent(baseToken)}/tables/${encodeURIComponent(tableId)}/records/batch_update`, { update_records: { [recordId]: fields } });
}

function assigneeId(record) {
  const value = record?.fields?.[FIELD_NAMES.assignee];
  return Array.isArray(value) ? value[0]?.id || null : null;
}

export function parseStageNumber(title) {
  const value = String(title || "");
  const arabic = value.match(/阶段\s*(\d+)/);
  if (arabic) return Number(arabic[1]);
  const chinese = value.match(/阶段\s*([零一二三四五六七八九十百]+)/);
  if (!chinese) return null;
  const digits = { 零: 0, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
  if (chinese[1] === "十") return 10;
  if (chinese[1].startsWith("十")) return 10 + (digits[chinese[1][1]] || 0);
  if (chinese[1].endsWith("十")) return (digits[chinese[1][0]] || 0) * 10;
  return digits[chinese[1]] ?? null;
}

function stageLabel(number) {
  return CHINESE_STAGES[number] || String(number);
}

function tomorrowDeadline() {
  const deadline = new Date(Date.now() + 24 * 60 * 60 * 1000);
  deadline.setUTCHours(10, 0, 0, 0);
  return deadline.toISOString();
}

function stageOneFields(project, memberOpenId, memberName, reviewerOpenId) {
  const repositoryUrl = `https://github.com/${project.repository}`;
  return {
    [FIELD_NAMES.title]: `阶段一：${project.name} 项目理解与架构分析（${memberName}）`,
    [FIELD_NAMES.description]: `请在 ${repositoryUrl} 中阅读 README、主要目录和关键调用链，尝试安装、启动和运行测试。写出项目定位、模块职责、一次完整运行流程、实际验证结果、风险疑问和你自己的理解。允许 AI 辅助检索和解释，提交前必须亲自核对文件、命令和结果。最后提交正式文档型 PR，PR description 要写明查阅文件、AI 使用方式、验证命令和未解决问题。`,
    [FIELD_NAMES.status]: ["待开始"],
    [FIELD_NAMES.assignee]: [{ id: memberOpenId }],
    [FIELD_NAMES.reviewer]: reviewerOpenId ? [{ id: reviewerOpenId }] : [],
    [FIELD_NAMES.priority]: ["中"],
    [FIELD_NAMES.type]: ["文档"],
    [FIELD_NAMES.mode]: ["阶段任务"],
    [FIELD_NAMES.area]: `${project.name} README、入口文件、主要模块和测试命令`,
    [FIELD_NAMES.target]: "形成一份有实际阅读和运行证据的项目理解文档",
    [FIELD_NAMES.acceptance]: "正式 PR 指向 main；说明项目定位、目录与模块、核心调用链、安装运行测试结果、风险疑问和个人理解；没有业务代码、生产配置或凭据变更。",
    [FIELD_NAMES.due]: tomorrowDeadline(),
  };
}

export async function ensureStageOneTask(env, project, memberOpenId, memberName) {
  const records = await listRecords(env, project);
  const active = records.find((record) => assigneeId(record) === memberOpenId && parseStageNumber(valueText(record.fields[FIELD_NAMES.title])) === 1 && valueText(record.fields[FIELD_NAMES.status]) !== "已完成");
  if (active) return { created: false, record_id: active.record_id, task_url: null };
  const recordId = await createRecord(env, project, stageOneFields(project, memberOpenId, memberName, env.FEISHU_BOT_OPEN_ID));
  return { created: true, record_id: recordId, task_url: null };
}

function prMatches(record, prUrl, number) {
  const value = valueText(record.fields[FIELD_NAMES.pr]);
  return value.includes(prUrl) || (value.includes("github.com") && value.includes(`/pull/${number}`));
}

function nextTaskFields(project, record, nextStage, assignee, assigneeName, reviewerOpenId) {
  const repositoryUrl = `https://github.com/${project.repository}`;
  return {
    [FIELD_NAMES.title]: `阶段${stageLabel(nextStage)}：${project.name} 真实问题改进与验证（${assigneeName}）`,
    [FIELD_NAMES.description]: `请在 ${repositoryUrl} 中自己选择一个真实问题，先写观察、复现步骤和两个根因假设，再使用 AI 辅助检索与解释。完成一个小范围、可回退的真实行为改进，保留正常路径，补一条修复前失败、修复后通过的回归验证和一条边界验证。PR description 要写清复现输入、根因、改动文件与函数、验证命令和未验证范围；评审时用自己的话解释技术取舍。`,
    [FIELD_NAMES.status]: ["待开始"],
    [FIELD_NAMES.assignee]: [{ id: assignee }],
    [FIELD_NAMES.reviewer]: reviewerOpenId ? [{ id: reviewerOpenId }] : [],
    [FIELD_NAMES.priority]: ["中"],
    [FIELD_NAMES.type]: ["研发"],
    [FIELD_NAMES.mode]: ["阶段任务"],
    [FIELD_NAMES.area]: `${project.name} 的真实运行链路、相关模块和回归测试`,
    [FIELD_NAMES.target]: `通过真实问题定位、修复和验证继续熟悉 ${project.name}`,
    [FIELD_NAMES.plan]: "先记录观察和假设，再确定一个小范围改动与验证矩阵",
    [FIELD_NAMES.acceptance]: "正式 PR 指向 main；有真实行为改动、回归验证、边界验证、复现与根因证据；能够解释调用链和 AI 建议的采纳或拒绝。",
    [FIELD_NAMES.due]: tomorrowDeadline(),
    [FIELD_NAMES.relatedDoc]: valueText(record.fields[FIELD_NAMES.relatedDoc]) || null,
  };
}

function outcomeText(outcome) {
  const review = outcome.review || {};
  const merged = outcome.merged === true || outcome.merge?.merged === true;
  const lines = [merged ? `已合并，合并提交：${outcome.merge?.sha || "GitHub 返回的提交"}` : `当前处理结果：${review.decision || "已检查"}`, review.summary || ""];
  if (review.blocking_findings?.length) lines.push("需要修改：", ...review.blocking_findings);
  if (review.requested_changes?.length) lines.push("修改方法：", ...review.requested_changes);
  if (review.non_blocking_findings?.length) lines.push("后续建议：", ...review.non_blocking_findings);
  if (review.test_evidence?.length) lines.push("验证信息：", ...review.test_evidence);
  if (outcome.gate?.reasons?.length && !merged) lines.push(`等待条件：${outcome.gate.reasons.join(", ")}`);
  return lines.filter(Boolean).join("\n").slice(0, 12000);
}

export async function applyGithubOutcome(env, outcome) {
  const project = projectForRepository(env, outcome.repository);
  if (!project) return { matched: false, reason: "repository_not_configured" };
  const records = await listRecords(env, project);
  const prUrl = `https://github.com/${project.repository}/pull/${Number(outcome.number)}`;
  const record = records.find((item) => prMatches(item, prUrl, outcome.number));
  if (!record) return { matched: false, reason: "task_not_linked", project: project.key };
  const assignee = assigneeId(record);
  const assigneeName = valueText(record.fields[FIELD_NAMES.assignee]) || "成员";
  const merged = outcome.merged === true || outcome.merge?.merged === true;
  const updateFields = { [FIELD_NAMES.status]: merged ? ["已完成"] : ["进行中"], [FIELD_NAMES.verification]: outcomeText(outcome), [FIELD_NAMES.blocked]: null };
  if (env.FEISHU_BOT_OPEN_ID) updateFields[FIELD_NAMES.reviewer] = [{ id: env.FEISHU_BOT_OPEN_ID }];
  await updateRecord(env, project, record.record_id, updateFields);
  let nextTask = null;
  if (merged && assignee) {
    const currentStage = parseStageNumber(valueText(record.fields[FIELD_NAMES.title]));
    if (currentStage && currentStage < 14) {
      const nextStage = currentStage + 1;
      const alreadyActive = records.some((item) => assigneeId(item) === assignee && parseStageNumber(valueText(item.fields[FIELD_NAMES.title])) === nextStage && valueText(item.fields[FIELD_NAMES.status]) !== "已完成");
      if (!alreadyActive) {
        const nextId = await createRecord(env, project, nextTaskFields(project, record, nextStage, assignee, assigneeName, env.FEISHU_BOT_OPEN_ID));
        nextTask = { record_id: nextId, stage: nextStage };
      }
    }
  }
  return { matched: true, project: project.key, record_id: record.record_id, assignee_open_id: assignee, assignee_name: assigneeName, next_task: nextTask };
}

function knowledgeMarkdown(record) {
  const review = record.review || {};
  const lines = [`# ${record.title || `PR #${record.number}`}`, "", `- 项目：${record.repository}`, `- 来源：${record.url}`, `- head SHA：${record.headSha || "未提供"}`, `- 处理时间：${new Date().toISOString()}`, "", "## 评审结论", review.summary || "本次记录没有摘要。"];
  if (review.blocking_findings?.length) lines.push("", "## 需要处理的问题", ...review.blocking_findings.map((item) => `- ${item}`));
  if (review.requested_changes?.length) lines.push("", "## 具体修改方法", ...review.requested_changes.map((item) => `- ${item}`));
  if (review.non_blocking_findings?.length) lines.push("", "## 后续学习和改进", ...review.non_blocking_findings.map((item) => `- ${item}`));
  if (review.test_evidence?.length) lines.push("", "## 验证信息", ...review.test_evidence.map((item) => `- ${item}`));
  if (record.merge?.merged) lines.push("", "## 合并结果", `已合并，合并提交：${record.merge.sha || "GitHub 返回的提交"}`);
  return lines.join("\n").slice(0, 30000);
}

export async function appendKnowledgeRecord(env, record) {
  const project = projectForRepository(env, record.repository);
  if (!project) return { created: false, reason: "repository_not_configured" };
  const { wikiParent } = fieldsForProject(env, project);
  const response = await feishuApi(env, "POST", "/open-apis/docs_ai/v1/documents", { content: knowledgeMarkdown(record), extra_param: JSON.stringify({ open_create_async: true }), format: "markdown", parent_token: wikiParent });
  const data = response.data || {};
  if (data.task_id) {
    for (let attempt = 0; attempt < 10; attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 750));
      const status = await feishuApi(env, "GET", `/open-apis/docs_ai/v1/async_tasks/${encodeURIComponent(data.task_id)}`);
      const task = status.data || {};
      if (["failed", "error"].includes(task.status)) throw new Error("feishu knowledge document creation failed");
      if (["success", "succeeded", "completed"].includes(task.status)) {
        const document = task.document || task.result?.document || task.result || {};
        return { created: true, document_id: document.document_id || document.id || null, url: document.url || null };
      }
    }
    throw new Error("feishu knowledge document creation is still pending");
  }
  const document = data.document || data;
  return { created: true, document_id: document.document_id || document.id || null, url: document.url || null };
}
