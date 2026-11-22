import "../../vendor/d3/7.9.0/d3.min.js";
const { d3 } = globalThis;

export function createCourseNetwork(element, {select, toggle, clear}) {
  const svg = d3.select(element);
  const palette = ["#0072b2","#e69f00","#009e73","#d55e00","#56b4e9","#cc79a7","#f0e442","#5c6b7a"];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  let layer, linkLayer, nodeLayer, simulation, links, nodes;
  let settings, model, hovered, signature, order, width, height;
  let changedCamera = false;
  let fitTimer;

  function zoomed(event) {
    layer.attr("transform",event.transform);
    layer.classed("network-far",event.transform.k < .8 || model.visibleConcepts > 12);
    if(event.sourceEvent) changedCamera=true;
  }

  const zoom = d3.zoom().scaleExtent([.42,2.2]).on("zoom",zoomed);
  const drag = d3.drag().clickDistance(4).container(() => layer.node())
    .filter((event,d) => !event.button && d.kind !== "root")
    .on("start",(event,d) => {
      if(!event.active) simulation.alphaTarget(.18).restart();
      d.fx=d.x;
      d.fy=d.y;
    })
    .on("drag",(event,d) => { d.fx=event.x; d.fy=event.y; })
    .on("end",(event,d) => {
      if(!event.active) simulation.alphaTarget(0);
      d.fx=null;
      d.fy=null;
    });

  function graphModel(course,points,edges) {
    const root={...course,kind:"root",radius:30,color:"#3d4bc0"};
    const chapters=course.chapters.map((chapter,index)=>({
      ...chapter,kind:"chapter",radius:22,color:palette[index%palette.length],index,
      angle:index/course.chapters.length*Math.PI*2-Math.PI/2,
    }));
    const byId=new Map([root,...chapters].map(node=>[node.id,node]));
    for(const p of points){
      const connections=edges.filter(e=>e.source===p.id||e.target===p.id).length;
      const parent=byId.get(p.chapter);
      byId.set(p.id,{...p,kind:"concept",radius:8.5 + Math.min(1+connections,4)*1.1,color:parent.color});
    }
    const relations = new Map();
    const add = (from,to,kind,relation) => {
      const id=kind+":"+from+">"+to;
      if(!relations.has(id)) relations.set(id,{id,from,to,kind,relation,color:byId.get(from).color});
    };
    for(const c of chapters) add(root.id,c.id,"owner");
    for(const p of points) add(p.chapter,p.id,"member");
    for(const edge of edges){
      const source=byId.get(edge.source);
      const target=byId.get(edge.target);
      if(edge.type==="prerequisite"&&source.chapter!==target.chapter) add(source.chapter,target.chapter,"path",edge);
      add(source.id,target.id,"concept",edge);
    }
    return {root,chapters,byId,relations:[...relations.values()],visibleConcepts:0};
  }

  function attach() {
    element.replaceChildren();
    const defs=svg.append("defs");
    const arrow=defs.append("marker").attr("id","network-arrow").attr("viewBox","0 0 10 10").attr("refX",9)
      .attr("refY",5).attr("markerWidth",5.5).attr("markerHeight",5.5).attr("orient","auto-start-reverse");
    arrow.append("path").attr("d","M1 1l8 4-8 4").attr("fill","none").attr("stroke","#5359dc").attr("stroke-width",1.45);
    layer=svg.append("g").attr("class","network-viewport");
    linkLayer=layer.append("g");
    nodeLayer=layer.append("g");
    svg.call(zoom).on("dblclick.zoom",null);
    svg.on("click.course-network",event=>{
      if(event.defaultPrevented||event.target.closest("[data-node]")) return;
      clear();
    });
    svg.call(zoom.transform,d3.zoomIdentity);
  }

  function textWidth(text){
    return Array.from(text).reduce((sum,char)=>sum+(char.codePointAt(0)>0x2e80?11:6.1),0);
  }

  function linesFor(node) {
    const name=node.shortName||node.name;
    if(node.kind!=="concept"||textWidth(name)<=108) return [name];
    let line="";
    let index=0;
    while(index<name.length&&textWidth(line+name[index])<=108) line+=name[index++];
    const delimiter=Math.max(line.lastIndexOf("、"),line.lastIndexOf(" "),line.lastIndexOf("·"));
    if(delimiter>line.length*.55) {
      index=delimiter+1;
      line=name.slice(0,index);
    }
    const tail=name.slice(index).trim();
    let second="";
    for(const char of tail){
      if(textWidth(second+char)>102) break;
      second+=char;
    }
    return [line,second+(second.length<tail.length?"…":"")];
  }

  function curve({source:a,target:b,kind}) {
    const distance=Math.hypot(b.x-a.x,b.y-a.y)||1;
    const dx=(b.x-a.x)/distance, dy=(b.y-a.y)/distance;
    const x=a.x+dx*(a.radius+1), y=a.y+dy*(a.radius+1);
    const gap=b.radius+(kind==="path"?7:2);
    const endX=b.x-dx*gap, endY=b.y-dy*gap;
    const bend=kind==="path"?26:kind==="concept"?12:0;
    if(!bend) return "M"+x+","+y+"L"+endX+","+endY;
    return "M"+x+","+y+"Q"+((x+endX)/2-dy*bend)+","+((y+endY)/2+dx*bend)+" "+endX+","+endY;
  }

  function ticked() {
    links.select(".network-line").attr("d",curve);
    links.select(".network-flow").attr("d",curve);
    nodes.attr("transform",d=>"translate("+d.x+" "+d.y+")");
  }

  function focus() {
    const id=hovered||settings.selected;
    const near=new Set();
    links.each(edge=>{
      if(edge.from===id) near.add(edge.to);
      if(edge.to===id) near.add(edge.from);
    });
    nodes.classed("network-selected",d=>d.id===settings.selected).classed("network-near",d=>near.has(d.id))
      .classed("network-dim",d=>Boolean(hovered)&&d.id!==hovered&&!near.has(d.id))
      .attr("aria-pressed",d=>String(d.id===settings.selected))
      .attr("aria-expanded",d=>d.kind==="chapter"?String(settings.expanded.has(d.id)):null);
    links.classed("network-near",d=>d.from===id||d.to===id)
      .classed("network-dim",d=>Boolean(hovered)&&d.from!==hovered&&d.to!==hovered);
  }

  function measure() {
    return {w:Math.max(300,element.clientWidth),h:Math.max(320,element.clientHeight)};
  }

  function animateCamera(camera,duration=400) {
    const target=reduced.matches?svg:svg.transition("network-camera").duration(duration);
    target.call(zoom.transform,camera);
  }

  function fit(force=false) {
    if(!nodes||changedCamera&&!force) return;
    const all=nodes.data();
    const left=d3.min(all,d=>d.x-Math.max(d.radius,textWidth(d.shortName||d.name)/2));
    const right=d3.max(all,d=>d.x+Math.max(d.radius,textWidth(d.shortName||d.name)/2));
    const top=d3.min(all,d=>d.y-d.radius-9);
    const bottom=d3.max(all,d=>d.y+d.radius+29);
    if(!force&&left>=16&&right<=width-16&&top>=16&&bottom<=height-45) return;
    const keepRoot=settings.expanded.size===1&&width>540;
    const middleX=width/2;
    const middleY=height/2;
    const scale=keepRoot
      ? Math.max(.42,Math.min((middleX-21)/Math.max(middleX-left,right-middleX),(middleY-40)/Math.max(middleY-top,bottom-middleY),1))
      : Math.max(.42,Math.min((width-42)/(right-left),(height-72)/(bottom-top),1.1));
    const x=keepRoot?middleX*(1-scale):(width-scale*(left+right))/2;
    const y=keepRoot?middleY*(1-scale):(height-25-scale*(top+bottom))/2;
    animateCamera(d3.zoomIdentity.translate(x,y).scale(scale));
  }

  function drawNodes(data) {
    const joined=nodeLayer.selectAll("g.network-node:not(.network-leaving)").data(data,d=>d.id);
    const exiting=joined.exit().classed("network-leaving",true).attr("data-node",null).attr("tabindex",null).style("pointer-events","none");
    if(reduced.matches) exiting.remove();
    else exiting.transition().duration(160).style("opacity",0).remove();
    const enter=joined.enter().append("g").attr("class",d=>"svg-node network-node network-"+d.kind)
      .attr("role","button").attr("tabindex",0).attr("data-node",d=>d.id)
      .attr("aria-label",d=>d.name).style("--node-color",d=>d.color);
    enter.append("circle").attr("class","network-halo").attr("r",d=>d.radius+9);
    enter.append("circle").attr("class","network-dot").attr("r",d=>d.radius);
    enter.each(function(d){
      const group=d3.select(this);
      if(d.kind==="root"){
        for(let i=-1;i<=1;i+=1){
          for(let j=-1;j<=1;j+=1) group.append("circle").attr("class","network-icon-dot").attr("cx",i*8).attr("cy",j*8).attr("r",i===0&&j===0?2.6:1.75);
        }
      } else if(d.kind==="chapter"){
        group.append("text").attr("class","network-number").attr("dominant-baseline","central").text(String(d.index+1).padStart(2,"0"));
      }
      const caption=group.append("text").attr("class","network-label").attr("y",d.radius+15);
      linesFor(d).forEach((line,i)=>caption.append("tspan").attr("x",0).attr("dy",i===0?0:12).text(line));
      group.append("title").text(d.name);
    });
    enter.on("click",(event,d)=>{
      if(event.defaultPrevented) return;
      event.stopPropagation();
      select(d.id);
    }).on("dblclick",(event,d)=>{
      event.preventDefault();
      event.stopPropagation();
      if(d.kind==="chapter") toggle(d.id);
    }).on("keydown",(event,d)=>{
      if(!["Enter"," "].includes(event.key)) return;
      event.preventDefault();
      if(event.key===" "&&d.kind==="chapter") toggle(d.id);
      else select(d.id);
    }).on("pointerenter",(event,d)=>{
      if(event.pointerType==="touch") return;
      hovered=d.id;
      focus();
    }).on("pointerleave",(event,d)=>{
      if(hovered===d.id) hovered=null;
      focus();
    }).call(drag);
    if(!reduced.matches) enter.style("opacity",0).transition().duration(300).style("opacity",null);
    nodes=enter.merge(joined);
  }

  function drawLinks(data) {
    const joined=linkLayer.selectAll("g.network-link:not(.network-leaving)").data(data,d=>d.id);
    const exiting=joined.exit().classed("network-leaving",true).attr("data-relation",null);
    if(reduced.matches) exiting.remove();
    else exiting.transition().duration(160).style("opacity",0).remove();
    const enter=joined.enter().append("g").attr("class",d=>"network-link network-edge-"+d.kind)
      .style("--edge-color",d=>d.color)
      .attr("data-relation",d=>d.relation?.type||null)
      .attr("data-cross",d=>d.relation?"false":null);
    enter.append("path").attr("class","network-line").attr("marker-end",d=>d.kind==="path"?"url(#network-arrow)":null);
    enter.append("path").attr("class","network-flow");
    enter.filter(d=>d.kind==="concept").append("title").text(d=>d.relation.reason);
    if(!reduced.matches) enter.style("opacity",0).transition().duration(260).style("opacity",null);
    links=enter.merge(joined);
  }

  function containPreview(data) {
    return alpha=>{
      for(const node of data){
        if(node.kind==="root"||node.fx!=null) continue;
        const padX=Math.max(node.radius+14,d3.max(linesFor(node),textWidth)/2+15);
        const x=Math.max(padX,Math.min(width-padX,node.x));
        const y=Math.max(node.radius+31,Math.min(height-node.radius-57,node.y));
        node.vx+=(x-node.x)*alpha*.34;
        node.vy+=(y-node.y)*alpha*.34;
      }
    };
  }

  function layout(data,related,init) {
    const center={x:width/2,y:height/2};
    const many=Math.max(0,model.chapters.length-5);
    const ring=settings.expanded.size?146+many*7:120+many*12;
    if(init) for(const d of data){
      d.x=undefined;
      d.y=undefined;
      d.vx=0;
      d.vy=0;
    }
    const matrix=d3.zoomTransform(element);
    layer.classed("network-far",matrix.k<.8||model.visibleConcepts>12);
    for(const d of data){
      if(d.kind==="root"){
        d.x=d.fx=center.x;
        d.y=d.fy=center.y;
      } else if(d.x===undefined&&d.kind==="chapter"){
        d.x=center.x+Math.cos(d.angle)*ring;
        d.y=center.y+Math.sin(d.angle)*ring;
      } else if(d.x===undefined){
        const parent=model.byId.get(d.chapter);
        const siblings=data.filter(point=>point.chapter===d.chapter);
        const angle=siblings.indexOf(d)/siblings.length*Math.PI*2-Math.PI/2;
        d.x=parent.x+Math.cos(angle)*58;
        d.y=parent.y+Math.sin(angle)*58;
      }
    }
    const distance={owner:132,member:96,path:178,concept:104};
    const strength={owner:.16,member:.16,path:.05,concept:.4};
    simulation?.stop();
    clearTimeout(fitTimer);
    const open=settings.expanded.size>0;
    simulation=d3.forceSimulation(data)
      .force("relations",d3.forceLink(related).id(d=>d.id).distance(d=>distance[d.kind]+(d.kind==="owner"?many*8:0)).strength(d=>strength[d.kind]))
      .force("charge",d3.forceManyBody().strength(d=>d.kind==="root"?-1500:d.kind==="chapter"?-620:-360).distanceMax(620))
      .force("collision",d3.forceCollide(d=>Math.max(d.radius+12,d3.max(linesFor(d),textWidth)/2+12)).strength(.95))
      .force("orbit",d3.forceRadial(ring,center.x,center.y).strength(d=>d.kind==="chapter"?(open?.16:.6):0))
      .force("x",d3.forceX(center.x).strength(.03))
      .force("y",d3.forceY(center.y).strength(.03))
      .force("viewport",width>540&&settings.expanded.size===1?containPreview(data):null)
      .alphaDecay(.04)
      .on("tick",ticked)
      .on("end",()=>fit());
    if(reduced.matches) {
      simulation.stop().tick(180);
      ticked();
      fit();
    } else {
      simulation.alpha(init?.92:.78);
      ticked();
      if(open) fitTimer=setTimeout(()=>fit(),660);
    }
  }

  function render(next,reset=false) {
    const newCourse=!layer||model.root.id!==next.course.id;
    settings=next;
    if(newCourse) {
      model=graphModel(next.course,next.items,next.edges);
      signature=null;
      order=null;
      hovered=null;
      attach();
      changedCamera=false;
    }
    const dimensions=measure();
    const resized=width!==dimensions.w||height!==dimensions.h;
    width=dimensions.w;
    height=dimensions.h;
    svg.attr("viewBox","0 0 "+width+" "+height);
    if(reset) {
      changedCamera=false;
      if(!newCourse) animateCamera(d3.zoomIdentity,360);
    }
    const data=[...model.byId.values()].filter(d=>d.kind!=="concept"||next.expanded.has(d.chapter));
    model.visibleConcepts=data.length-model.chapters.length-1;
    const visible=new Set(data.map(d=>d.id));
    const nextSignature=data.map(d=>d.id).join("|");
    const related=model.relations.filter(d=>visible.has(d.from)&&visible.has(d.to));
    if(signature!==nextSignature||resized||order!==next.version) {
      const init=newCourse||resized||order!==next.version;
      signature=nextSignature;
      order=next.version;
      if(hovered&&!visible.has(hovered)) hovered=null;
      const entries=related.map(d=>({...d,source:d.from,target:d.to}));
      drawLinks(entries);
      drawNodes(data);
      layout(data,entries,init);
    }
    focus();
    return {nodes:data.length,relations:related.filter(e=>e.relation).length};
  }

  function detach() {
    if(!layer) return;
    simulation?.stop();
    clearTimeout(fitTimer);
    svg.interrupt("network-camera").on(".zoom",null).on(".course-network",null);
    layer=null;
  }

  function centerOn(id) {
    const d=model?.byId.get(id);
    if(!d||d.x===undefined) return;
    const scale=d3.zoomTransform(element).k;
    changedCamera=true;
    animateCamera(d3.zoomIdentity.translate(width/2-d.x*scale,height/2-d.y*scale).scale(scale));
  }

  return {render,detach,centerOn};
}
