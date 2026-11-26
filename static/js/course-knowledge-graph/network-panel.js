export function networkPanel({items, activeEdges, course, state, chapters, pointById, chapterPoints, label, h}) {
  const current = typeof course === "function" ? course() : course;
  const point = pointById.get(state.selected);
  const chapter = chapters.get(point?.chapter || state.selected);
  const ownPoints = chapter ? chapterPoints.get(chapter.id) : items;
  const ownIds = new Set(ownPoints.map(item => item.id));
  const relevant = activeEdges.filter(edge => point
    ? edge.source === point.id || edge.target === point.id
    : ownIds.has(edge.source) || ownIds.has(edge.target));
  const opened = chapter && state.expanded.has(chapter.id);
  const everyChapterOpen = current.chapters.every(item => state.expanded.has(item.id));
  const status = chapter ? opened ? "已展开" : "已收起" : "浏览中";
  const chapterIndex = chapter ? current.chapters.findIndex(item => item.id === chapter.id) : -1;
  const chapterNumber = String(chapterIndex + 1).padStart(2, "0");
  const kinds = { prerequisite: "先修", related: "拓展" };
  const predecessor = relevant.filter(edge => edge.type === "prerequisite" && edge.target === point?.id);
  const successor = relevant.filter(edge => edge.type === "prerequisite" && edge.source === point?.id);

  const title = point?.name || chapter?.name || current.name;
  const summary = point?.description || (chapter
    ? ownPoints.slice(0, 2).map(item => item.description).join("")
    : "展开章节查看知识点，以及不同主题之间的先修关系。");
  const tags = point ? [chapter.name, point.sourcePage && "大纲第 " + point.sourcePage + " 页"].filter(Boolean)
    : chapter ? ["第 " + (chapterIndex + 1) + " 章", label(current)]
    : ["课程总览", current.outlineRevision && current.outlineRevision + " 版大纲"].filter(Boolean);
  const stats = point ? [[1, "知识点"], [relevant.length, "关系"], [predecessor.length, "先修"], [successor.length, "后续"]]
    : [[ownPoints.length, "知识点"], [relevant.length, "关系"], [chapter ? ownPoints.length : current.chapters.length, "可展开"],
      [chapter ? ownPoints.length : current.chapters.length, "可进入"]];
  const attributes = [
    ["类型", point ? "知识点" : chapter ? "章节节点" : "根节点"],
    ["状态", status],
    ["分类", chapter?.name || "总览"],
    ["视图 ID", point?.id || (chapter ? chapterNumber : current.outlineCode || current.id)],
    ["关联", point ? chapter.name : chapter ? ownPoints.length + " 个知识点" : current.chapters.length + " 个章节"],
  ];

  function primary(text, attribute) {
    return '<button type="button" class="network-panel-button network-panel-primary" ' + attribute + '>' + text + '</button>';
  }

  function secondary(text, attribute) {
    return '<button type="button" class="network-panel-button" ' + attribute + '>' + text + '</button>';
  }

  const select = id => 'data-select="' + h(id) + '"';
  const acts = point
    ? primary("定位到该章", select(chapter.id)) + secondary("回到总览", "data-clear")
    : chapter ? primary(opened ? "收起节点" : "展开节点", 'data-network-action="toggle"') + secondary("查看首个知识点", select(ownPoints[0].id))
    : primary(everyChapterOpen ? "收起全部" : "展开全部", 'data-network-action="expand"') + secondary("从第 1 章开始", select(current.chapters[0].id));

  const ordered = point ? [...predecessor, ...successor, ...relevant.filter(edge => edge.type === "related")] : [];
  const relationDetails = ordered.length ? '<details class="network-panel-links"><summary>查看知识点关系与理由</summary>' +
    ordered.map(edge => {
      const other = pointById.get(edge.source === point.id ? edge.target : edge.source);
      const kind = edge.type === "prerequisite" && edge.source === point.id ? "后续" : kinds[edge.type];
      return '<button type="button" class="network-panel-link" ' + select(other.id) + '><span><b>' + h(kind) + '</b> ' + h(other.name) +
        '</span><small>' + h(edge.reason) + '</small></button>';
    }).join("") + '</details>' : '';

  return '<div class="network-panel-head"><span class="network-panel-caption">节点详情</span><span class="network-panel-badge">' +
    (point ? "知识点" : status) + '</span></div><h2 class="network-panel-title">' + h(title) + '</h2><p class="network-panel-desc">' + h(summary) +
    '</p><div class="network-panel-tags">' + tags.map(tag => '<span># ' + h(tag) + '</span>').join("") +
    '</div><dl class="network-panel-stats">' + stats.map(([value, name]) => '<div><dt>' + name + '</dt><dd>' + value + '</dd></div>').join("") +
    '</dl><h3 class="network-panel-section">属性信息</h3><dl class="network-panel-attributes">' +
    attributes.map(([key, value]) => '<div><dt>' + key + '</dt><dd' + (key === "视图 ID" ? ' class="network-panel-id"' : '') + '>' + h(value) + '</dd></div>').join("") +
    '</dl>' + relationDetails + '<h3 class="network-panel-section">操作</h3><div class="network-panel-actions">' + acts + '</div>';
}
