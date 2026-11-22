import { courses, points, edges } from "./graph-data.js";
import { createCourseNetwork } from "./network.js";
import { networkPanel } from "./network-panel.js";

const page = document.querySelector(".course-knowledge-graph");
const byId = items => new Map(items.map(item => [item.id, item]));
const courseById = byId(courses);
const pointById = byId(points);
const chapters = byId(courses.flatMap(course => course.chapters.map(chapter => ({...chapter, course: course.id}))));
const chapterPoints = new Map([...chapters.keys()].map(id => [id, points.filter(point => point.chapter === id)]));
const state = {mode:"network", course:courses[0].id, enabled:new Set(courseById.keys()), expanded:new Set([courses[0].chapters[0].id]), selected:courses[0].chapters[0].id, related:true, layoutVersion:0};
const ui = Object.fromEntries(["graph","toolbar","search","search-results","surface","list","details","canvas-controls","map-empty","graph-footer","network-hint"].map(id => [id, page.querySelector("#" + id)]));
const view = {width:1000, height:580, scale:1, x:0, y:0, layer:null};
let pan;
const network = createCourseNetwork(ui.graph,{select:pick,toggle:toggleNetworkChapter,clear:resetNetwork});
const course = () => courseById.get(state.course);
const label = node => node.shortName || node.name;
const cross = edge => pointById.get(edge.source).course !== pointById.get(edge.target).course;
const h = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"})[c]);
const visiblePoints = () => points.filter(p => state.mode === "network" ? p.course === state.course : state.enabled.has(p.course));
const relatedVisible = () => state.related || state.mode === "network";

function visibleEdges(items) {
  const ids = new Set(items.map(point => point.id));
  return edges.filter(e => ids.has(e.source) && ids.has(e.target) && (relatedVisible() || e.type === "prerequisite"));
}

function svg(tag, attrs = {}, value) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, attr] of Object.entries(attrs)) node.setAttribute(key, attr);
  if (value !== undefined) node.textContent = value;
  return node;
}

function action(key, text, disabled = false) {
  return '<button type="button" class="action" data-control="' + key + '" data-action="' + key + '"' + (disabled ? " disabled" : "") + '>' + text + '</button>';
}

function paintToolbar(summary) {
  const focused = document.activeElement?.dataset.control;
  if (state.mode === "network") {
    const current = course();
    const all = current.chapters.every(c => state.expanded.has(c.id));
    const topic = pointById.get(state.selected);
    const parent = chapters.get(topic?.chapter || state.selected);
    const crumb = '<span aria-hidden="true">/</span>' +
      (topic ? '<button type="button" class="network-parent" data-network-up>' + h(label(parent)) + '</button><span aria-hidden="true">/</span><strong>' + h(label(topic)) + '</strong>' :
        '<strong>' + (parent ? h(label(parent)) : '总览') + '</strong>');
    ui.toolbar.innerHTML = '<div class="network-crumb"><select id="network-course" class="course-select" data-control="course" aria-label="切换课程">' +
      courses.map(c => '<option value="' + h(c.id) + '"' + (c.id === state.course ? " selected" : "") + '>' + h(c.name) + '</option>').join("") +
      '</select>' + crumb + '</div><div class="network-count">' + summary.nodes + ' 个节点 · ' + summary.relations + ' 条关系</div><div class="tool-group right">' +
      action("up","返回上一级",!parent) + action("root","回到根节点") +
      action("expand",all ? "收起全部" : "展开全部") + action("relayout","重排位置") + '</div>';
  } else {
    ui.toolbar.innerHTML = '<div class="tool-group"><span class="tool-label">显示课程</span>' +
      courses.map(c => '<button type="button" class="chip" data-course="' + h(c.id) + '" data-control="' + h(c.id) + '" aria-pressed="' + state.enabled.has(c.id) + '"><i class="dot" style="--dot:' + h(c.color) + '"></i>' + h(c.name) + '</button>').join("") +
      '</div><div class="tool-group right"><label class="check"><input type="checkbox" id="show-related" data-control="related"' + (state.related ? " checked" : "") + '>显示拓展关联</label></div>';
  }
  if (focused) [...ui.toolbar.querySelectorAll("[data-control]")].find(el => el.dataset.control === focused)?.focus({preventScroll:true});
}

function detailButton(id, markup) {
  return '<button type="button" class="detail-item" data-select="' + h(id) + '">' + markup + '</button>';
}

function relationList(title, pairs) {
  return '<section><h3>' + title + ' <span class="meta">' + pairs.length + '</span></h3>' +
    (pairs.length ? pairs.map(([edge, id]) => {
      const other = pointById.get(id);
      const badge = cross(edge) ? ' <span class="cross-label">跨课</span>' : '';
      const source = cross(edge) ? courseById.get(other.course).name + ' · ' : '';
      return detailButton(id, h(other.name) + badge + '<small>' + h(source + edge.reason) + '</small>');
    }).join("") : '<p class="meta">当前视图内暂无</p>') + '</section>';
}

function paintDetails(items, activeEdges) {
  if (state.mode === "network") {
    ui.details.innerHTML=networkPanel({items,activeEdges,course:course(),state,chapters,pointById,chapterPoints,label,h});
    return;
  }
  const point = pointById.get(state.selected);
  const chapter = chapters.get(state.selected);
  const heading = point ? "知识点详情" : chapter ? "章节详情" : "浏览指南";
  let body = "";
  if (point) {
    const incoming = activeEdges.filter(e => e.target === point.id && e.type === "prerequisite").map(e => [e,e.source]);
    const outgoing = activeEdges.filter(e => e.source === point.id && e.type === "prerequisite").map(e => [e,e.target]);
    const related = activeEdges.filter(e => e.type === "related" && [e.source,e.target].includes(point.id)).map(e => [e,e.source === point.id ? e.target : e.source]);
    body = '<h2>' + h(point.name) + '</h2><div class="meta">' + h(courseById.get(point.course).name + ' · ' + chapters.get(point.chapter).name + (point.sourcePage ? ' · 大纲第 ' + point.sourcePage + ' 页' : '')) +
      '</div><p>' + h(point.description) + '</p>' + relationList("直接先修",incoming) + relationList("后续知识点",outgoing) + (relatedVisible() ? relationList("拓展关联",related) : "");
  } else if (chapter) {
    body = '<h2>' + h(chapter.name) + '</h2><div class="meta">' + h(course().name) + ' · ' + chapterPoints.get(chapter.id).length + ' 个知识点</div><h3>本章知识点</h3>' +
      chapterPoints.get(chapter.id).map(point => detailButton(point.id,h(point.name))).join("");
  } else if (state.mode === "network") {
    body = '<h2>' + h(course().name) + '</h2><div class="meta">' + course().chapters.length + ' 个模块 · ' + items.length + ' 个知识点</div><p>点开章节展开知识点。双击已展开的章节可收起。</p><h3>课程模块</h3>' +
      course().chapters.map((c,i) => detailButton(c.id, String(i+1).padStart(2,"0") + '　' + h(c.name))).join("");
  } else {
    body = '<h2>选择知识点</h2><p>' + (state.mode === "map" ? '点选一个知识点，查看先修路径和直接关联。勾选两门课程即可看到跨课程连线。' : '从列表打开知识点，查看它的先修、后续与拓展关联。') + '</p>';
  }
  ui.details.innerHTML = '<div class="detail-top"><span class="detail-label">' + heading + '</span>' + (state.selected ? '<button type="button" class="clear" data-clear>取消选中</button>' : '') + '</div>' + body;
}

function paintList(items, activeEdges) {
  const incoming = new Map(items.map(p => [p.id,[]]));
  for (const edge of activeEdges.filter(e => e.type === "prerequisite")) incoming.get(edge.target).push(edge);
  ui.list.innerHTML = items.length ? courses.filter(c => state.enabled.has(c.id)).map(c =>
    '<section><h2><i class="dot" style="--dot:' + h(c.color) + '"></i> ' + h(c.name) + '</h2>' +
    c.chapters.map(chapter => '<h3>' + h(chapter.name) + '</h3><div class="cards">' + chapterPoints.get(chapter.id).map(p =>
      '<button type="button" class="card" data-select="' + h(p.id) + '" aria-pressed="' + (state.selected === p.id) + '"><strong>' + h(p.name) +
      '</strong><small>' + (incoming.get(p.id).length ? '先修　' + h(incoming.get(p.id).map(e => label(pointById.get(e.source))).join("、")) : '暂无直接先修') +
      (incoming.get(p.id).some(cross) ? ' <span class="cross-label">跨课</span>' : '') + '</small></button>').join("") + '</div>').join("") + '</section>').join("") :
    '<p>勾选至少一门课程以查看知识点。</p>';
}

function paintFooter(items, activeEdges) {
  const count = activeEdges.filter(e => e.type === "prerequisite").length;
  const markers = '<span><i class="sample"></i>先修</span>' + (relatedVisible() ? '<span><i class="sample related"></i>拓展关联</span>' : '') +
    (state.mode === "network" ? '<span><i class="sample member"></i>章节归属</span>' : '<span><i class="sample cross"></i>跨课程</span>');
  const measure = items.length + ' 个知识点 · ' + count + ' 条先修' + (relatedVisible() ? ' · ' + (activeEdges.length-count) + ' 条拓展' : '') +
    (state.mode === "network" ? '' : ' · ' + activeEdges.filter(cross).length + ' 条跨课');
  ui["graph-footer"].innerHTML = '<div class="legend">' + markers + '</div><span aria-live="polite">' + measure + '　·　知识点关系为教学推导</span>';
}

function transform() {
  view.layer?.setAttribute("transform", "translate(" + view.x + " " + view.y + ") scale(" + view.scale + ")");
}

function fit(readable = false) {
  view.scale = 1;
  view.x = 0;
  view.y = 0;
  if (readable && state.mode === "map" && ui.graph.clientWidth < 600 && state.enabled.size) {
    const box = ui.graph.getBoundingClientRect();
    const corner = cursor(box.left, box.top);
    view.scale = Math.min(3, 870 / box.width);
    view.x = corner.x - 7 * view.scale;
    view.y = corner.y - 12 * view.scale;
  }
  transform();
}

function cursor(x,y) {
  return new DOMPoint(x,y).matrixTransform(ui.graph.getScreenCTM().inverse());
}

function zoom(factor, x = view.width / 2, y = view.height / 2) {
  const scale = Math.max(.38, Math.min(3.5, view.scale * factor));
  view.x = x - (x - view.x) * scale / view.scale;
  view.y = y - (y - view.y) * scale / view.scale;
  view.scale = scale;
  transform();
}

function canvas(width,height) {
  view.width = width;
  view.height = height;
  ui.graph.setAttribute("viewBox", "0 0 " + width + " " + height);
  const defs = svg("defs");
  for (const [id,color] of Object.entries({arrow:"#6b809f", crossArrow:"#754ca8", focusArrow:"#244e9d"})) {
    const marker = svg("marker",{id,viewBox:"0 0 8 8",refX:7.4,refY:4,markerWidth:6.8,markerHeight:6.8,orient:"auto"});
    marker.append(svg("path",{d:"M0 0L8 4L0 8Z",fill:color}));
    defs.append(marker);
  }
  view.layer = svg("g");
  ui.graph.replaceChildren(defs, view.layer);
  transform();
  return view.layer;
}

function focusPath(activeEdges) {
  const nodes = new Set();
  const selected = new Set();
  if (!pointById.has(state.selected)) return {nodes,selected};
  const queue = [state.selected];
  nodes.add(state.selected);
  while (queue.length) {
    const id = queue.pop();
    for (const edge of activeEdges) {
      if (edge.type !== "prerequisite" || edge.target !== id) continue;
      selected.add(edge);
      if (nodes.has(edge.source)) continue;
      nodes.add(edge.source);
      queue.push(edge.source);
    }
  }
  for (const edge of activeEdges) {
    if (![edge.source,edge.target].includes(state.selected)) continue;
    selected.add(edge);
    nodes.add(edge.source);
    nodes.add(edge.target);
  }
  return {nodes,selected};
}

function lineStyle(edge, focus) {
  const related = edge.type === "related";
  const across = cross(edge);
  const highlighted = focus.selected.has(edge);
  const stroke = across ? "#754ca8" : related ? "#aa7027" : highlighted ? "#244e9d" : "#6b809f";
  const marker = across ? "crossArrow" : highlighted ? "focusArrow" : "arrow";
  return {stroke, fill:"none", "stroke-width": highlighted ? 2.3 : across ? 1.8 : 1.12,
    opacity: highlighted ? 1 : focus.nodes.size ? .24 : across ? .85 : .64,
    "stroke-dasharray": related ? "5 4" : "", ...(related ? {} : {"marker-end":"url(#" + marker + ")"}),
    "data-relation":edge.type,"data-cross":String(across), "data-source":edge.source,"data-target":edge.target};
}

function short(text,max) {
  return text.length > max ? text.slice(0,max-1) + "…" : text;
}

function groupFor(item) {
  return svg("g",{class:"svg-node","data-node":item.id,role:"button",tabindex:0,"aria-label":item.name,"aria-pressed":String(item.id === state.selected)});
}

function mapLayout(items) {
  const columnCount = 5;
  const stride = 199;
  const width = 1040;
  const lanes = [];
  const positions = new Map();
  let laneTop = 51;
  for (const c of courses.filter(item => state.enabled.has(item.id))) {
    const columns = Array.from({length:columnCount}, () => []);
    c.chapters.forEach((chapter,index) => columns[Math.floor(index * columnCount / c.chapters.length)].push(...chapterPoints.get(chapter.id)));
    const height = Math.max(...columns.map(column => column.length)) * 31 + 54;
    lanes.push({course:c,top:laneTop,height});
    columns.forEach((column,i) => column.forEach((p,j) => positions.set(p.id,{column:i, x:39 + i * stride, y:laneTop + 39 + j * 31, w:162, h:27})));
    laneTop += height + 12;
  }
  return {width,height:Math.max(laneTop+4,470),lanes,positions,columnCount,stride};
}

function mapRoute(a,b) {
  const ay = a.y + a.h/2;
  const by = b.y + b.h/2;
  let x = a.x + a.w;
  let target = b.x - 3;
  if (a.column === b.column) {
    target = b.x + b.w + 3;
    return "M" + x + "," + ay + " C" + (x+23) + "," + ay + " " + (target+23) + "," + by + " " + target + "," + by;
  }
  if (a.column > b.column) {
    x = a.x;
    target = b.x + b.w + 3;
  }
  const mid = (x+target)/2;
  return "M" + x + "," + ay + " C" + mid + "," + ay + " " + mid + "," + by + " " + target + "," + by;
}

function paintMap(items, activeEdges) {
  const map = mapLayout(items);
  const layer = canvas(map.width,map.height);
  if (!items.length) return;
  for (const {course:c,top,height} of map.lanes) {
    layer.append(svg("rect",{x:15,y:top,width:1010,height,rx:11,fill:c.color,"fill-opacity":.06,stroke:c.color,"stroke-opacity":.32}));
    layer.append(svg("circle",{cx:30,cy:top+20,r:4,fill:c.color}));
    layer.append(svg("text",{x:42,y:top+25,fill:"#1b3357","font-size":15,"font-weight":750},c.name));
  }
  for (let i = 0; i < map.columnCount; i += 1) {
    const x = 25 + i * map.stride;
    layer.append(svg("text",{x:x+95,y:31,"text-anchor":"middle",fill:"#4b6083","font-size":13,"font-weight":680},"阶段 " + (i+1)));
    if (i) layer.append(svg("path",{d:"M"+x+" 41V"+(map.height-16),stroke:"#aabbd5","stroke-dasharray":"3 5"}));
  }
  const focus = focusPath(activeEdges);
  for (const edge of [...activeEdges].sort((a,b) => Number(focus.selected.has(a)) - Number(focus.selected.has(b)))) {
    const line = svg("path",{d:mapRoute(map.positions.get(edge.source),map.positions.get(edge.target)),...lineStyle(edge,focus)});
    line.append(svg("title",{},pointById.get(edge.source).name + " → " + pointById.get(edge.target).name + " · " + edge.reason));
    layer.append(line);
  }
  for (const point of items) {
    const {x,y,w,h:height} = map.positions.get(point.id);
    const selected = state.selected === point.id;
    const color = courseById.get(point.course).color;
    const group = groupFor(point);
    group.setAttribute("opacity",focus.nodes.size && !focus.nodes.has(point.id) ? ".46" : "1");
    group.append(svg("rect",{x,y,width:w,height,rx:6,fill:selected ? "#e5efff" : "#fff",stroke:selected ? "#244e9d" : color,"stroke-opacity": selected ? 1 : .62,"stroke-width": selected ? 2 : 1}));
    group.append(svg("circle",{cx:x+11,cy:y+height/2,r:3.2,fill:color}));
    group.append(svg("text",{x:x+20,y:y+height/2,"dominant-baseline":"central",fill:"#243756","font-size":12,"font-weight":selected?750:580},short(label(point),11)));
    group.append(svg("title",{},point.name));
    layer.append(group);
  }
}

function paint(reset=false) {
  const items=visiblePoints(), activeEdges=visibleEdges(items);
  const listMode=state.mode==="list";
  const networkMode=state.mode==="network";
  const focusedNode=document.activeElement?.closest?.("[data-node]")?.dataset.node;
  const focusedCard=document.activeElement?.closest?.("#list [data-select]")?.dataset.select;
  page.querySelector(".explorer").dataset.view=state.mode;
  page.querySelectorAll("[data-mode]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.mode===state.mode)));
  ui.surface.hidden=listMode;
  ui["canvas-controls"].hidden=listMode||networkMode||!items.length;
  ui["network-hint"].hidden=!networkMode;
  ui["map-empty"].hidden=listMode||items.length>0;
  ui["graph-footer"].hidden=networkMode;
  ui.list.hidden=!listMode;
  if(!networkMode) network.detach();
  const summary=networkMode?network.render({course:course(),items,edges:activeEdges,expanded:state.expanded,selected:state.selected,version:state.layoutVersion},reset):null;
  paintToolbar(summary);
  paintDetails(items,activeEdges);
  if(!networkMode) {
    paintFooter(items,activeEdges);
    if(listMode) paintList(items,activeEdges);
    else {
      paintMap(items,activeEdges);
      if(reset) fit(true);
    }
  }
  if(focusedNode) findBy(ui.graph,"node",focusedNode)?.focus({preventScroll:true});
  if(focusedCard) findBy(ui.list,"select",focusedCard)?.focus({preventScroll:true});
}
const findBy=(parent,attr,id)=>[...parent.querySelectorAll("[data-"+attr+"]")].find(el=>el.dataset[attr]===id);

function resetNetwork() {
  state.selected=state.course;
  state.expanded.clear();
  paint(true);
  ui.details.scrollTop=0;
}

function toggleNetworkChapter(id) {
  if (!chapters.has(id)) return;
  if (state.expanded.has(id)) state.expanded.delete(id);
  else state.expanded.add(id);
  state.selected=id;
  paint();
  ui.details.scrollTop=0;
}

function toggleAllNetworkChapters() {
  const ids=course().chapters.map(c=>c.id);
  const closing=ids.every(chapter=>state.expanded.has(chapter));
  state.expanded=new Set(closing?[]:ids);
  if(closing&&pointById.has(state.selected)) state.selected=pointById.get(state.selected).chapter;
  paint(closing);
}

function pick(id, fromSearch=false) {
  if(state.mode==="network"&&id!==state.course) {
    const chapter=chapters.has(id)?id:pointById.get(id)?.chapter;
    if(!chapter) return;
    state.expanded.add(chapter);
  }
  state.selected=id;
  paint();
  ui.details.scrollTop=0;
  if(state.mode==="list") {
    findBy(ui.list,"select",id)?.scrollIntoView({block:"nearest"});
  } else if(fromSearch&&state.mode==="network") {
    network.centerOn(id);
  } else if(fromSearch) {
    const bounds=findBy(ui.graph,"node",id)?.getBoundingClientRect();
    if(bounds) {
      const at=cursor(bounds.x+bounds.width/2,bounds.y+bounds.height/2);
      view.x+=view.width/2-at.x;
      view.y+=view.height/2-at.y;
      transform();
    }
  }
}

function refreshSearch() {
  const term=ui.search.value.trim().toLowerCase();
  const results=ui["search-results"];
  results.hidden=!term;
  if(!term) return;
  const matches=visiblePoints().filter(p=>[p.name,p.shortName,p.description,chapters.get(p.chapter).name].join(" ").toLowerCase().includes(term)).slice(0,8);
  results.innerHTML=matches.length?matches.map(p=>'<button type="button" data-select="'+h(p.id)+'"><span>'+h(p.name)+'</span><small>'+h(label(courseById.get(p.course)))+'</small></button>').join(""):'<p>未找到匹配的知识点</p>';
}

function acceptSearch(id) {
  ui.search.value="";
  ui["search-results"].hidden=true;
  pick(id,true);
}

page.querySelector(".views").addEventListener("click",event=>{
  const mode=event.target.closest("[data-mode]")?.dataset.mode;
  if(!mode||mode===state.mode) return;
  state.mode=mode;
  const selected=visiblePoints().find(p=>p.id===state.selected);
  if(mode==="network") {
    state.selected=selected?.id || course().chapters[0].id;
    state.expanded.add(selected?.chapter || state.selected);
  } else if(!selected) state.selected=null;
  ui.search.value="";
  refreshSearch();
  paint(true);
});
ui.toolbar.addEventListener("change",event=>{
  if(event.target.id==="network-course"){
    state.course=event.target.value;
    state.selected=course().chapters[0].id;
    state.expanded=new Set([state.selected]);
    state.layoutVersion=0;
    paint(true);
  } else if(event.target.id==="show-related"){
    state.related=event.target.checked;
    paint();
  }
  refreshSearch();
});
ui.toolbar.addEventListener("click",event=>{
  const button=event.target.closest("button");
  if(!button) return;
  if(button.hasAttribute("data-network-up")) {
    pick(pointById.get(state.selected).chapter);
    return;
  }
  const id=button.dataset.course;
  if(id){
    if(state.enabled.has(id)) state.enabled.delete(id);
    else state.enabled.add(id);
    if(!visiblePoints().some(p=>p.id===state.selected)) state.selected=null;
  } else {
    switch(button.dataset.action){
      case "root":
        resetNetwork();
        return;
      case "up":
        state.selected=pointById.get(state.selected)?.chapter || state.course;
        paint();
        return;
      case "expand":
        toggleAllNetworkChapters();
        return;
      case "relayout":
        state.layoutVersion+=1;
        break;
      default:
        return;
    }
  }
  paint(true);
  refreshSearch();
});

function delegatedDetail(event){
  const action=event.target.closest("[data-network-action]")?.dataset.networkAction;
  if(action==="toggle") { toggleNetworkChapter(state.selected); return; }
  if(action==="expand") { toggleAllNetworkChapters(); return; }
  const id=event.target.closest("[data-select]")?.dataset.select;
  if(id) pick(id);
  else if(event.target.closest("[data-clear]")){
    state.selected=state.mode==="network"?state.course:null;
    paint();
  }
}
ui.details.addEventListener("click",delegatedDetail);
ui.list.addEventListener("click",delegatedDetail);
ui.graph.addEventListener("click",event=>{
  if(state.mode==="network") return;
  const id=event.target.closest("[data-node]")?.dataset.node;
  if(id) pick(id);
});
ui.graph.addEventListener("keydown",event=>{
  if(state.mode==="network") return;
  const id=event.target.closest("[data-node]")?.dataset.node;
  if(!id||!["Enter"," "].includes(event.key)) return;
  event.preventDefault();
  pick(id);
});
ui.graph.addEventListener("wheel",event=>{
  if(state.mode==="network"||!visiblePoints().length) return;
  event.preventDefault();
  const at=cursor(event.clientX,event.clientY);
  zoom(Math.exp(-event.deltaY*.0014),at.x,at.y);
},{passive:false});
ui.graph.addEventListener("pointerdown",event=>{
  if(state.mode==="network"||event.button!==0||event.target.closest("[data-node]")) return;
  pan={id:event.pointerId,at:cursor(event.clientX,event.clientY)};
  ui.graph.setPointerCapture(event.pointerId);
  ui.graph.classList.add("panning");
});
ui.graph.addEventListener("pointermove",event=>{
  if(pan?.id!==event.pointerId) return;
  const at=cursor(event.clientX,event.clientY);
  view.x+=at.x-pan.at.x;
  view.y+=at.y-pan.at.y;
  pan.at=at;
  transform();
});
for(const type of ["pointerup","pointercancel","lostpointercapture"]) ui.graph.addEventListener(type,()=>{
  pan=null;
  ui.graph.classList.remove("panning");
});
ui["canvas-controls"].addEventListener("click",event=>{
  const key=event.target.closest("[data-zoom]")?.dataset.zoom;
  if(key==="fit") fit();
  else if(key) zoom(key==="in"?1.23:1/1.23);
});
ui.search.addEventListener("input",refreshSearch);
ui.search.addEventListener("focus",refreshSearch);
ui.search.addEventListener("keydown",event=>{
  const results=ui["search-results"];
  if(event.key==="Escape") results.hidden=true;
  else if(event.key==="ArrowDown"&&!results.hidden){
    event.preventDefault();
    results.querySelector("button")?.focus();
  } else if(event.key==="Enter"&&!results.hidden){
    const id=results.querySelector("[data-select]")?.dataset.select;
    if(id) acceptSearch(id);
  }
});
ui["search-results"].addEventListener("click",event=>{
  const id=event.target.closest("[data-select]")?.dataset.select;
  if(id) acceptSearch(id);
});
document.addEventListener("click",event=>{
  if(!page.querySelector(".search").contains(event.target)) ui["search-results"].hidden=true;
});
document.addEventListener("keydown",event=>{
  const editing=event.target instanceof HTMLInputElement||event.target instanceof HTMLTextAreaElement||event.target.isContentEditable;
  if(event.key==="/"&&!editing&&!event.altKey&&!event.ctrlKey&&!event.metaKey&&!event.defaultPrevented){
    event.preventDefault();
    ui.search.focus();
  }
});
paint(true);

new ResizeObserver(()=>{ if(state.mode==="network") paint(); }).observe(ui.surface);