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
const ACTIVE_TASK_STATUSES = new Set(["待开始", "进行中", "待评审", "阻塞"]);
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

export async function listProjectRecords(env, project) {
  return listRecords(env, project);
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

async function lookupGithubMember(env, repository, githubLogin) {
  if (!env.STATE_DB || !repository || !githubLogin) return null;
  return env.STATE_DB.prepare(
    "SELECT repository, github_login, assignee_open_id, assignee_name FROM github_member_identity WHERE repository = ? AND github_login = ?",
  ).bind(repository, githubLogin).first();
}

async function rememberGithubMember(env, repository, githubLogin, assigneeOpenId, assigneeName) {
  if (!env.STATE_DB || !repository || !githubLogin || !assigneeOpenId) return;
  await env.STATE_DB.prepare(
    `INSERT INTO github_member_identity (repository, github_login, assignee_open_id, assignee_name, updated_at)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(repository, github_login) DO UPDATE SET
       assignee_open_id = excluded.assignee_open_id,
       assignee_name = excluded.assignee_name,
       updated_at = excluded.updated_at`,
  ).bind(repository, githubLogin, assigneeOpenId, assigneeName || null, new Date().toISOString()).run();
}

function assigneeId(record) {
  const value = record?.fields?.[FIELD_NAMES.assignee];
  return Array.isArray(value) ? value[0]?.id || null : null;
}

function assigneeName(record) {
  return valueText(record?.fields?.[FIELD_NAMES.assignee]) || "成员";
}

export function taskRecordSnapshot(record) {
  return {
    recordId: record?.record_id || record?.recordId || null,
    taskName: valueText(record?.fields?.[FIELD_NAMES.title]) || valueText(record?.taskName),
    status: valueText(record?.fields?.[FIELD_NAMES.status]) || valueText(record?.status),
    assigneeOpenId: assigneeId(record) || record?.assigneeOpenId || null,
    assigneeName: assigneeName(record) || record?.assigneeName || "成员",
    prUrl: valueText(record?.fields?.[FIELD_NAMES.pr]) || valueText(record?.prUrl),
    stage: parseStageNumber(valueText(record?.fields?.[FIELD_NAMES.title]) || valueText(record?.taskName)),
  };
}

export function nextStageEligibility(records, record) {
  const snapshot = record?.taskName ? record : taskRecordSnapshot(record);
  if (snapshot.status !== "已完成") return { eligible: false, reason: "status_not_completed" };
  if (!snapshot.assigneeOpenId) return { eligible: false, reason: "assignee_missing" };
  if (!snapshot.stage) return { eligible: false, reason: "stage_missing" };
  if (snapshot.stage >= 14) return { eligible: false, reason: "final_stage" };
  const hasActiveNextStage = (Array.isArray(records) ? records : [])
    .map((item) => item?.taskName ? item : taskRecordSnapshot(item))
    .some((item) => item.assigneeOpenId === snapshot.assigneeOpenId
      && item.stage === snapshot.stage + 1
      && item.status !== "已完成");
  if (hasActiveNextStage) return { eligible: false, reason: "next_stage_exists" };
  return {
    eligible: true,
    assigneeOpenId: snapshot.assigneeOpenId,
    assigneeName: snapshot.assigneeName,
    nextStage: snapshot.stage + 1,
  };
}

export function nextStageForCompletedRecord(records, record) {
  const eligibility = nextStageEligibility(records, record);
  if (!eligibility.eligible) return null;
  return {
    assigneeOpenId: eligibility.assigneeOpenId,
    assigneeName: eligibility.assigneeName,
    nextStage: eligibility.nextStage,
  };
}

export function selectTaskForGithubIdentity(records, assigneeOpenId) {
  const candidates = (Array.isArray(records) ? records : []).filter((record) => {
    const snapshot = taskRecordSnapshot(record);
    const mode = valueText(record?.fields?.[FIELD_NAMES.mode]);
    return snapshot.assigneeOpenId === assigneeOpenId
      && ACTIVE_TASK_STATUSES.has(snapshot.status)
      && Boolean(snapshot.stage)
      && !snapshot.prUrl
      && (!mode || mode === "阶段任务");
  });
  return candidates.length === 1 ? candidates[0] : null;
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

const STAGE_STORIES = {
  1: {
    title: "先认识项目现场",
    situation: (project) => `你刚接手 ${project}，先把“它做什么、从哪里启动”说清楚。`,
    target: "跑通一条真实入口，形成自己的项目地图。",
    action: (repositoryUrl) => `阅读 README、入口文件和一条调用链，亲自运行一次安装、启动或测试命令（仓库：${repositoryUrl}）。`,
    result: "提交一份带文件路径和命令输出的项目理解文档 PR。",
    area: "README、入口文件、主要模块和测试命令",
    plan: "先阅读，再运行，最后记录实际看到的结果",
    acceptance: "PR 指向 main；包含项目定位、目录、调用链和实际命令结果。",
    type: "文档",
  },
  2: {
    title: "找到一个真实问题",
    situation: (project) => `${project} 已经能运行，现在从使用者视角找一个小问题。`,
    target: "把一个真实问题复现出来，并说明它影响谁。",
    action: (repositoryUrl) => `记录输入、实际输出和复现步骤，再在 ${repositoryUrl} 中提交一个小范围修复。`,
    result: "PR 同时包含复现证据、改动和验证结果。",
    area: "真实运行链路和相关模块",
    plan: "先复现，再确认影响范围，最后修改一处行为",
    acceptance: "PR 能按步骤复现问题，并证明修复后的结果。",
    type: "研发",
  },
  3: {
    title: "追到问题根因",
    situation: "问题已经出现，表面现象还不等于原因。",
    target: "沿调用链找到一个可以验证的根因。",
    action: "用日志、断点或最小实验排除两个假设，只保留有证据的结论。",
    result: "PR 让别人能从证据走到根因。",
    area: "调用链、状态变化和错误来源",
    plan: "记录观察，再验证假设，最后保留一条根因证据",
    acceptance: "PR 写明观察、两个假设、验证过程和根因。",
    type: "研发",
  },
  4: {
    title: "把修复变成回归验证",
    situation: "修复已经有效，下一次改动仍可能把它带回来。",
    target: "把这次故障变成自动回归验证。",
    action: "先写一个能复现旧问题的测试，再让修复后的测试通过。",
    result: "PR 展示修复前失败、修复后通过。",
    area: "测试目录、失败路径和回归命令",
    plan: "先让测试复现旧问题，再提交修复并重新运行",
    acceptance: "PR 包含一个回归测试，并提供前后两次结果。",
    type: "研发",
  },
  5: {
    title: "把边界情况试出来",
    situation: "正常输入已经通过，边界输入还没有经过检查。",
    target: "确认边界行为符合项目预期。",
    action: "选择两种真实边界输入，记录结果；只有发现错误时才修改代码。",
    result: "PR 给出边界证据和处理决定。",
    area: "输入校验、异常路径和边界测试",
    plan: "选边界输入，记录输出，再决定是否改动",
    acceptance: "PR 写清两种边界输入、实际输出和处理理由。",
    type: "研发",
  },
  6: {
    title: "让别人能跑通关键路径",
    situation: "新成员接手时，最容易卡在环境和入口。",
    target: "让另一个人能按你的说明跑通关键路径。",
    action: "从干净环境按文档执行一次，删掉无效步骤，补上真实报错处理。",
    result: "PR 附可复现命令和关键输出。",
    area: "安装、启动、测试和常见报错",
    plan: "按新手视角走一遍，再只改真正卡住的步骤",
    acceptance: "PR 的命令可以在干净环境执行，并记录关键结果。",
    type: "研发",
  },
  7: {
    title: "让失败信息能帮上忙",
    situation: "失败时用户只看到一个结果，定位成本很高。",
    target: "让一条失败路径给出可行动的信息。",
    action: "追踪一次失败请求，补充必要日志或错误提示，不泄露凭据。",
    result: "PR 让维护者能根据提示定位位置。",
    area: "失败路径、日志和错误提示",
    plan: "复现一次失败，确认缺失信息，再补最小提示",
    acceptance: "PR 展示失败前后的提示，并说明没有记录敏感内容。",
    type: "研发",
  },
  8: {
    title: "改善一处真实使用卡点",
    situation: "核心流程已经能运行，学习体验还有一个明显阻力。",
    target: "改善一处小范围的学习或使用路径。",
    action: "用一次真实操作找到卡点，改动一个提示、页面或调用环节，并做前后验证。",
    result: "PR 展示改动前后的操作路径和验证结果。",
    area: "学习路径、用户提示和相关调用环节",
    plan: "亲自走一遍流程，记录卡点，再验证改动效果",
    acceptance: "PR 说明卡点、改动位置和前后操作结果。",
    type: "研发",
  },
  9: {
    title: "补上一盏运行中的灯",
    situation: "功能能完成，不代表运行过程容易观察。",
    target: "为一条关键路径补上可验证的运行信号。",
    action: "选择一个状态、耗时或失败点，补充最小观测信息并确认输出。",
    result: "PR 说明信号何时出现、如何读取。",
    area: "状态、耗时、日志和运行检查",
    plan: "选一个看不见的状态，补信号，再实际读取一次",
    acceptance: "PR 包含触发条件、输出样例和读取方法。",
    type: "研发",
  },
  10: {
    title: "用一次测量验证优化",
    situation: "优化需要证据，凭感觉容易把问题改复杂。",
    target: "用一次测量确认一个小优化是否有效。",
    action: "先记录基线，再做一处低风险优化，重复同一测量。",
    result: "PR 给出前后数据和没有优化的部分。",
    area: "关键路径、测量方法和前后结果",
    plan: "先测量，再改动，最后用同一方法复测",
    acceptance: "PR 有基线、改动后数据和测量命令。",
    type: "研发",
  },
  11: {
    title: "整理一处真实维护难点",
    situation: "连续改动后，代码里可能留下重复路径或隐含假设。",
    target: "整理一处确实影响维护的复杂点。",
    action: "从调用者角度删掉一层重复或补上一个明确校验，并运行相关测试。",
    result: "PR 说明删改理由和行为保持情况。",
    area: "重复逻辑、输入校验和相关测试",
    plan: "找到实际维护痛点，小范围整理，再验证行为没有变化",
    acceptance: "PR 说明维护痛点、改动边界和测试结果。",
    type: "研发",
  },
  12: {
    title: "把一次经验变成方法",
    situation: "项目已经积累了几次真实改动，需要把经验变成规则。",
    target: "从历史问题中提炼一条可复用的检查方法。",
    action: "选择一次已合并改动，复盘触发、处理和验证过程，补到文档或工具中。",
    result: "PR 让下一位成员能按这条方法工作。",
    area: "历史 PR、项目文档和工作检查",
    plan: "选一次真实记录，提炼步骤，再让一个新例子验证",
    acceptance: "PR 引用历史记录，并用一个新例子验证方法。",
    type: "文档",
  },
  13: {
    title: "带别人走一遍流程",
    situation: "你已经熟悉一条链路，现在换成带别人走一遍。",
    target: "找出新手最可能卡住的一步并修好。",
    action: "让一名成员或 AI 按你的说明执行，记录卡点，修改说明或代码并验证。",
    result: "PR 附执行记录和改动前后差异。",
    area: "新手入口、说明文档和关键流程",
    plan: "先让别人照做，再根据实际卡点修改",
    acceptance: "PR 有执行记录、卡点和改动后的复现结果。",
    type: "研发",
  },
  14: {
    title: "独立完成一个小闭环",
    situation: "你已经能处理局部问题，现在负责一次完整交付。",
    target: "从发现问题到合并交付完成一次自主管理。",
    action: "自己选题、复现、改动、验证、写 PR，并回应评审意见。",
    result: "PR 合并后留下可复用的方案或文档。",
    area: "问题发现、实现、验证、评审和知识沉淀",
    plan: "独立完成选题、实现、验证和评审跟进",
    acceptance: "PR 完成复现、改动、验证、评审回复和合并后的记录。",
    type: "研发",
  },
};

export function stageTaskContent(projectName, stage, assigneeName, repositoryUrl = "") {
  const project = String(projectName || "项目");
  const member = String(assigneeName || "成员");
  const stageNumber = Number(stage);
  const story = STAGE_STORIES[stageNumber] || STAGE_STORIES[14];
  const action = typeof story.action === "function" ? story.action(repositoryUrl || `https://github.com/${project}`) : story.action;
  return {
    title: `阶段${stageLabel(stageNumber)}：${story.title}（${member}）`,
    description: [`S：${typeof story.situation === "function" ? story.situation(project) : story.situation}`, `T：${story.target}`, `A：${action}`, `R：${story.result}`].join("\n"),
    area: `${project}：${story.area}`,
    target: story.target,
    plan: story.plan,
    acceptance: story.acceptance,
    type: story.type,
  };
}

function tomorrowDeadline() {
  const deadline = new Date(Date.now() + 24 * 60 * 60 * 1000);
  deadline.setUTCHours(10, 0, 0, 0);
  return deadline.toISOString();
}

function stageOneFields(project, memberOpenId, memberName, reviewerOpenId) {
  const repositoryUrl = `https://github.com/${project.repository}`;
  const content = stageTaskContent(project.name, 1, memberName, repositoryUrl);
  return {
    [FIELD_NAMES.title]: content.title,
    [FIELD_NAMES.description]: content.description,
    [FIELD_NAMES.status]: ["待开始"],
    [FIELD_NAMES.assignee]: [{ id: memberOpenId }],
    [FIELD_NAMES.reviewer]: reviewerOpenId ? [{ id: reviewerOpenId }] : [],
    [FIELD_NAMES.priority]: ["中"],
    [FIELD_NAMES.type]: [content.type],
    [FIELD_NAMES.mode]: ["阶段任务"],
    [FIELD_NAMES.area]: content.area,
    [FIELD_NAMES.target]: content.target,
    [FIELD_NAMES.plan]: content.plan,
    [FIELD_NAMES.acceptance]: content.acceptance,
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
  const content = stageTaskContent(project.name, nextStage, assigneeName, repositoryUrl);
  return {
    [FIELD_NAMES.title]: content.title,
    [FIELD_NAMES.description]: content.description,
    [FIELD_NAMES.status]: ["待开始"],
    [FIELD_NAMES.assignee]: [{ id: assignee }],
    [FIELD_NAMES.reviewer]: reviewerOpenId ? [{ id: reviewerOpenId }] : [],
    [FIELD_NAMES.priority]: ["中"],
    [FIELD_NAMES.type]: [content.type],
    [FIELD_NAMES.mode]: ["阶段任务"],
    [FIELD_NAMES.area]: content.area,
    [FIELD_NAMES.target]: content.target,
    [FIELD_NAMES.plan]: content.plan,
    [FIELD_NAMES.acceptance]: content.acceptance,
    [FIELD_NAMES.due]: tomorrowDeadline(),
    [FIELD_NAMES.relatedDoc]: valueText(record.fields[FIELD_NAMES.relatedDoc]) || null,
  };
}

export async function ensureNextStageTask(env, project, record, records = []) {
  const snapshot = taskRecordSnapshot(record);
  const eligibility = nextStageEligibility(records, snapshot);
  if (!eligibility.eligible) return { created: false, record_id: null, next_stage: null, reason: eligibility.reason };
  const recordId = await createRecord(env, project, nextTaskFields(project, record, eligibility.nextStage, eligibility.assigneeOpenId, eligibility.assigneeName, env.FEISHU_BOT_OPEN_ID));
  return { created: true, record_id: recordId, next_stage: eligibility.nextStage, assignee_open_id: eligibility.assigneeOpenId, assignee_name: eligibility.assigneeName };
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
  const githubLogin = String(outcome.author_login || "").trim();
  let record = records.find((item) => prMatches(item, prUrl, outcome.number));
  let linkedAutomatically = false;
  if (!record && githubLogin) {
    const identity = await lookupGithubMember(env, project.repository, githubLogin);
    const candidate = identity ? selectTaskForGithubIdentity(records, identity.assignee_open_id) : null;
    if (candidate) {
      await updateRecord(env, project, candidate.record_id, { [FIELD_NAMES.pr]: prUrl });
      record = { ...candidate, fields: { ...candidate.fields, [FIELD_NAMES.pr]: prUrl } };
      linkedAutomatically = true;
    }
  }
  if (!record) return { matched: false, reason: "task_not_linked", project: project.key };
  const assignee = assigneeId(record);
  const assigneeName = valueText(record.fields[FIELD_NAMES.assignee]) || "成员";
  if (githubLogin && assignee) await rememberGithubMember(env, project.repository, githubLogin, assignee, assigneeName);
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
  return { matched: true, project: project.key, record_id: record.record_id, assignee_open_id: assignee, assignee_name: assigneeName, linked_automatically: linkedAutomatically, next_task: nextTask };
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
