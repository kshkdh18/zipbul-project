'use client';
import {t, useLocale} from './Locale';
import {useMemo,useState} from 'react';
import SpatialRelationGraph from './SpatialRelationGraph';
import {ReactFlow,Background,Controls,MarkerType,Position,ReactFlowProvider,type Node,type Edge} from '@xyflow/react';
import dagre from '@dagrejs/dagre';
import '@xyflow/react/dist/style.css';
import type {Hazard,SceneData} from '../lib/types';
export function graphData(scene:SceneData,selected:string|null,full:boolean){
  const hazards=full?scene.hazards:scene.hazards.filter(h=>h.id===selected);
  const nodes:Node[]=[],edges:Edge[]=[];const seen=new Set<string>();
  const add=(id:string,label:string,kind:string,h:Hazard)=>{if(seen.has(id))return;seen.add(id);nodes.push({id,type:'default',position:{x:0,y:0},sourcePosition:Position.Right,targetPosition:Position.Left,data:{label,hazardId:h.id,kind},className:`graph-node ${kind} ${h.id===selected?'is-selected':''}`,style:{width:190}});};
  const link=(source:string,target:string,label:string,dashed=false)=>edges.push({id:`${source}-${target}`,source,target,label,type:'smoothstep',markerEnd:{type:MarkerType.ArrowClosed,color:'#71797f'},style:{stroke:dashed?'#ad8855':'#6d879b',strokeDasharray:dashed?'5 4':undefined},labelStyle:{fill:'#c2c8cc',fontSize:11},labelBgStyle:{fill:'#202429'}});
  if(full)nodes.push({id:scene.id,type:'default',position:{x:0,y:0},sourcePosition:Position.Right,targetPosition:Position.Left,data:{label:t(scene.title),kind:'scene'},className:'graph-node scene',style:{width:190}});
  for(const h of hazards){add(h.entityId,t("대상 · {0}", h.anchor?.status==='verified'?t("위치 연결됨"):t("위치 검토 필요")),'entity',h);add(h.id,t(h.title),'hazard',h);add(`action-${h.id}`,t(h.check),'action',h);link(h.entityId,h.id,t("관련 대상"),true);link(h.id,`action-${h.id}`,t("점검 제안"),true);
    if(full&&!edges.some(e=>e.source===scene.id&&e.target===h.entityId))link(scene.id,h.entityId,t("현장 소속"));
    for(const e of h.evidence){const f=scene.frames.find(f=>f.id===e.frameId);add(e.id,t("영상 근거 · {0}", f?`${Math.floor(f.timestamp/60)}:${String(Math.floor(f.timestamp%60)).padStart(2,'0')}`:e.frameId),'evidence',h);link(e.id,h.id,t("관찰 근거"));}
  }
  const g=new dagre.graphlib.Graph();g.setGraph({rankdir:'LR',nodesep:34,ranksep:105,marginx:30,marginy:30});g.setDefaultEdgeLabel(()=>({}));nodes.forEach(n=>g.setNode(n.id,{width:190,height:76}));edges.forEach(e=>g.setEdge(e.source,e.target));dagre.layout(g);nodes.forEach(n=>{const p=g.node(n.id);n.position={x:p.x-95,y:p.y-38};});
  return {nodes,edges};
}
export default function RelationGraph({scene,selected,full,onSelect}:{scene:SceneData;selected:string|null;full:boolean;onSelect:(id:string,evidenceId?:string)=>void}){
  const {locale}=useLocale();
  const [view,setView]=useState<'3d'|'2d'>('3d');
  const {nodes,edges}=useMemo(()=>graphData(scene,selected,full),[scene.id,scene.title,scene.hazards,selected,full,locale]);
  return <div className="graph-view">{full&&<div className="graph-view-switch"><button className={view==='3d'?'active':''} onClick={()=>setView('3d')}>{""}{t("3D 탐색")}{""}</button><button className={view==='2d'?'active':''} onClick={()=>setView('2d')}>{""}{t("2D 정렬")}{""}</button></div>}{full&&view==='3d'?<SpatialRelationGraph nodes={nodes} edges={edges} selected={selected} onSelect={onSelect}/>:<ReactFlowProvider><div className="graph-body"><ReactFlow key={`${full}-${selected}-${nodes.length}`} nodes={nodes} edges={edges} fitView fitViewOptions={{padding:.18,maxZoom:1}} minZoom={.08} maxZoom={1.6} nodesDraggable={false} onNodeClick={(_,node)=>{if(node.data.hazardId)onSelect(String(node.data.hazardId),node.data.kind==='evidence'?node.id:undefined);}} colorMode="dark" proOptions={{hideAttribution:true}}><Background color="#343b40" gap={24}/><Controls showInteractive={false}/></ReactFlow><div className="graph-legend"><span><i className="line"/>{""}{t("관찰 근거")}{""}</span><span><i className="line dashed"/>{""}{t("해석·제안")}{""}</span><span>{nodes.length}{""}{t("개 노드 ·")}{" "}{edges.length}{""}{t("개 연결")}{""}</span></div></div></ReactFlowProvider>}</div>;
}
