const SUPPORTED_REPOSITORY = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
const SUPPORTED_REPOSITORIES = new Set(["xiaocow666/codesense", "xiaocow666/caifusi"]);

export function scheduledMode(cron) {
  return cron === "0 10 * * *" ? "daily-report" : "reconcile";
}

export function actionCanBeReclaimed(existing, now = Date.now()) {
  if (existing?.status === "failed") return true;
  if (existing?.status !== "running") return false;
  const updatedAt = Date.parse(String(existing.updated_at || ""));
  return Number.isFinite(updatedAt) && now - updatedAt >= 15 * 60 * 1000;
}

export function isReviewRequest(text) {
  return /(?:复审|重新评审|审一下|审查一下|帮我看一下).*(?:PR|pull\s*request)|(?:PR|pull\s*request).*(?:复审|重新评审|审一下|审查一下|帮我看一下)/i.test(String(text || ""));
}

export function isKnowledgeCandidate(text) {
  const value = String(text || "").trim();
  if (value.length < 12) return false;
  return /(?:归档|整理进知识库|经验|排查|解决方案|复盘|版本更新|架构|技术要点|踩坑|教程|问题定位|回归验证|部署记录)/i.test(value);
}

export function extractPullRequestReference(text, projectRepository) {
  const value = String(text || "");
  const repository = String(projectRepository || "").trim();
  if (/别的项目|其他项目|无关项目/i.test(value)) return null;
  const link = value.match(/https?:\/\/github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)\/pull\/(\d+)/i);
  if (link) {
    if (!SUPPORTED_REPOSITORIES.has(link[1].toLowerCase())) return null;
    if (repository && link[1].toLowerCase() !== repository.toLowerCase()) return null;
    return { repository: repository || (link[1].toLowerCase() === "xiaocow666/codesense" ? "XiaoCow666/CodeSense" : "XiaoCow666/Caifusi"), number: Number(link[2]) };
  }
  if (!SUPPORTED_REPOSITORY.test(repository)) return null;
  const number = value.match(/(?:PR|pull\s*request)\s*#?\s*(\d+)/i);
  return number ? { repository, number: Number(number[1]) } : null;
}

export function formatDailyReport({ date, projects = [], githubReviews = 0, merged = 0, completedTasks = 0, nextTasks = 0, errors = 0 } = {}) {
  const lines = [
    `线上自动化日报 ${date || ""}`.trim(),
    `PR 评审：${githubReviews} 次，合并：${merged} 个；任务完成：${completedTasks} 项；自动续派：${nextTasks} 项；失败重试：${errors} 次。`,
  ];
  for (const project of projects) {
    const statuses = Object.entries(project.tasks || {}).map(([status, count]) => `${status} ${count}`).join("，") || "暂无任务";
    lines.push(`${project.name}：${statuses}；开放 PR ${project.openPrs || 0} 个。`);
  }
  if (errors > 0) lines.push("请查看失败事件记录，线上流程会继续重试，无法确认成功的动作不会标记为已完成。");
  else lines.push("当前没有失败重试，线上事件会继续按 Webhook 和定时对账处理。");
  return lines.join("\n").slice(0, 12000);
}
