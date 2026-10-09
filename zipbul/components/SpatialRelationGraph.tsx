'use client';
import {useEffect,useRef,useState} from 'react';
import {ArrowUpRight,Expand,Pause,Play,ZoomIn,ZoomOut} from 'lucide-react';
import * as THREE from 'three';
import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
import {CSS2DObject,CSS2DRenderer} from 'three/examples/jsm/renderers/CSS2DRenderer.js';
import type {Node,Edge} from '@xyflow/react';

type Props={nodes:Node[];edges:Edge[];selected:string|null;onSelect:(id:string,evidenceId?:string)=>void};
type Handle={zoom:(factor:number)=>void;reset:()=>void;rotate:(enabled:boolean)=>void;highlight:(id:string|null)=>void};
const kindNames:Record<string,string>={scene:'현장',hazard:'위험 해석',evidence:'영상 근거',entity:'공간 대상',action:'현장 점검'};

export default function SpatialRelationGraph(props:Props){
  const host=useRef<HTMLDivElement>(null),runtime=useRef<Handle|null>(null),latest=useRef(props);latest.current=props;
  const [rotating,setRotating]=useState(true),[error,setError]=useState(''),[hovered,setHovered]=useState<string|null>(null);
  const topology=JSON.stringify([props.nodes.map(n=>[n.id,n.data]),props.edges.map(e=>[e.id,e.source,e.target,e.label])]);
  const inspected=props.nodes.find(n=>n.id===(hovered||props.selected));
  const hazards=props.nodes.filter(n=>n.data.kind==='hazard');
  const evidenceCount=props.nodes.filter(n=>n.data.kind==='evidence').length;
  useEffect(()=>{runtime.current?.highlight(props.selected);},[props.selected]);
  useEffect(()=>{
    const element=host.current;if(!element)return;
    const {nodes,edges}=latest.current;
    let renderer:THREE.WebGLRenderer;
    try{renderer=new THREE.WebGLRenderer({antialias:true});}catch{setError('3D 그래프를 준비하지 못했습니다. 2D 정렬 보기로 전환해 주세요.');return;}
    renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x14191e);element.appendChild(renderer.domElement);
    renderer.domElement.setAttribute('aria-label','회전하고 확대할 수 있는 위험 관계 네트워크');
    const labels=new CSS2DRenderer();labels.domElement.className='spatial-graph-labels';element.appendChild(labels.domElement);
    const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(42,1,.1,250);
    const controls=new OrbitControls(camera,element);controls.enableDamping=true;controls.dampingFactor=.075;controls.minDistance=10;controls.maxDistance=110;controls.autoRotateSpeed=.17;
    const reducedMotion=matchMedia('(prefers-reduced-motion: reduce)').matches;
    let autoRotate=!reducedMotion,hovering=false,focused:string|null=null;
    setRotating(autoRotate);controls.autoRotate=autoRotate;
    const network=new THREE.Group();scene.add(network);
    const hazardNodes=nodes.filter(n=>n.data.kind==='hazard');
    const positions=new Map<string,THREE.Vector3>();
    const sceneNode=nodes.find(n=>n.data.kind==='scene');if(sceneNode)positions.set(sceneNode.id,new THREE.Vector3());
    // Each spoke is an actual hazard branch; depth separates its source evidence and proposed checks.
    hazardNodes.forEach((h,i)=>{
      const angle=Math.PI*.25+i/Math.max(hazardNodes.length,1)*Math.PI*2;
      const outward=new THREE.Vector3(Math.cos(angle)*1.4,Math.sin(angle),0),tangent=new THREE.Vector3(-Math.sin(angle)*1.4,Math.cos(angle),0);
      const center=new THREE.Vector3(Math.cos(angle)*10.6,Math.sin(angle)*7.5,Math.sin(i*2.4)*2.1);
      positions.set(h.id,center);
      const related=nodes.filter(n=>n.data.hazardId===h.id),evidence=related.filter(n=>n.data.kind==='evidence');
      for(const node of related){if(node.id===h.id)continue;
        if(node.data.kind==='entity')positions.set(node.id,center.clone().multiplyScalar(.52).add(new THREE.Vector3(0,0,1.7)));
        else if(node.data.kind==='action')positions.set(node.id,center.clone().addScaledVector(outward,3).addScaledVector(tangent,2.7).add(new THREE.Vector3(0,0,2.2)));
        else positions.set(node.id,center.clone().addScaledVector(outward,3.8-evidence.indexOf(node)*.25).addScaledVector(tangent,-2.0-evidence.indexOf(node)*3).add(new THREE.Vector3(0,0,-2.0)));
      }
    });
    // Separate unusually close nodes deterministically, without adding invented relationships.
    for(let iteration=0;iteration<45;iteration++)for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){
      const a=positions.get(nodes[i].id),b=positions.get(nodes[j].id);if(!a||!b)continue;
      const delta=a.clone().sub(b);delta.z*=.3;const distance=delta.length();if(distance>=3.1)continue;
      if(distance<.01)delta.set(1,.2,0);else delta.multiplyScalar(1/distance);
      const force=delta.multiplyScalar((3.1-distance)*.12);
      if(nodes[i].data.kind!=='scene')a.add(force);if(nodes[j].data.kind!=='scene')b.sub(force);
    }
    const meshes=new Map<string,THREE.Mesh<THREE.SphereGeometry,THREE.MeshBasicMaterial>>(),buttons=new Map<string,HTMLButtonElement>();
    const edgeObjects:{edge:Edge;line:THREE.Line;arrow:THREE.Mesh;label:HTMLElement;curve:THREE.QuadraticBezierCurve3;pulse:THREE.Mesh}[]=[];
    const colors:Record<string,number>={scene:0xc4d0d8,hazard:0xe6ae5d,evidence:0x7faed1,entity:0x788b99,action:0xb9c6cf};
    let reset=()=>{};
    function choose(node:Node){if(node.data.kind==='scene'){reset();return;}latest.current.onSelect(String(node.data.hazardId),node.data.kind==='evidence'?node.id:undefined);}
    for(const node of nodes){
      const kind=String(node.data.kind),index=hazardNodes.findIndex(h=>h.id===node.id);
      const mesh=new THREE.Mesh(new THREE.SphereGeometry(.1,12,8),new THREE.MeshBasicMaterial({color:colors[kind],transparent:true,opacity:0}));
      mesh.position.copy(positions.get(node.id)||new THREE.Vector3());network.add(mesh);meshes.set(node.id,mesh);
      const button=document.createElement('button');button.type='button';button.className=`network-node ${kind}`;button.dataset.nodeId=node.id;button.dataset.hazardId=String(node.data.hazardId||'');button.title=String(node.data.label);button.setAttribute('aria-label',`${kindNames[kind]}: ${node.data.label}`);
      const disc=document.createElement('span');disc.className='network-disc';
      const glyph=document.createElement('span');glyph.className='network-glyph';glyph.textContent=kind==='hazard'?`H-${String(index+1).padStart(2,'0')}`:kind==='scene'?(String(node.data.label).match(/현장\s*(\d+)/)?.[1]||'공간'):kind==='evidence'?String(node.data.label).split('·').at(-1)!.trim():kind==='action'?'점검':'대상';
      const label=document.createElement('span');label.className='network-node-title';label.textContent=kind==='scene'?'현장 연결망':kind==='hazard'?String(node.data.label):kind==='evidence'?'영상 근거':kind==='entity'?(String(node.data.label).includes('연결됨')?'위치 연결됨':'위치 검토 필요'):'점검 제안';
      disc.append(glyph);button.append(disc,label);
      button.addEventListener('pointerdown',e=>e.stopPropagation());button.addEventListener('click',e=>{e.stopPropagation();choose(node);});
      button.addEventListener('pointerenter',()=>{hovering=true;controls.autoRotate=false;setHovered(node.id);highlight(node.data.kind==='scene'?null:String(node.data.hazardId));});
      button.addEventListener('pointerleave',()=>{hovering=false;controls.autoRotate=autoRotate;setHovered(null);highlight(latest.current.selected);});
      button.addEventListener('focus',()=>{controls.autoRotate=false;setHovered(node.id);highlight(node.data.kind==='scene'?null:String(node.data.hazardId));});
      button.addEventListener('blur',()=>{if(!hovering)controls.autoRotate=autoRotate;setHovered(null);highlight(latest.current.selected);});
      const object=new CSS2DObject(button);object.center.set(.5,.5);mesh.add(object);buttons.set(node.id,button);
    }
    for(const edge of edges){
      const a=positions.get(edge.source),b=positions.get(edge.target);if(!a||!b)continue;
      const membership=edge.source===sceneNode?.id,dashed=!!edge.style?.strokeDasharray,color=membership?0x536471:dashed?0xad8955:0x709fbe;
      const middle=a.clone().lerp(b,.5);middle.z+=membership?-.6:1.1;
      const curve=new THREE.QuadraticBezierCurve3(a,middle,b);
      const material=dashed?new THREE.LineDashedMaterial({color,dashSize:.13,gapSize:.10,transparent:true,opacity:.65}):new THREE.LineBasicMaterial({color,transparent:true,opacity:.65});
      const line=new THREE.Line(new THREE.BufferGeometry().setFromPoints(curve.getPoints(40)),material);line.computeLineDistances();network.add(line);
      const arrow=new THREE.Mesh(new THREE.ConeGeometry(.065,.20,8),new THREE.MeshBasicMaterial({color,transparent:true,opacity:.8}));arrow.position.copy(curve.getPoint(.73));arrow.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),curve.getTangent(.73).normalize());network.add(arrow);
      const pulse=new THREE.Mesh(new THREE.SphereGeometry(.045,8,6),new THREE.MeshBasicMaterial({color,transparent:true,opacity:.7}));pulse.visible=false;network.add(pulse);
      const text=document.createElement('span');text.className='network-edge-label';text.textContent=String(edge.label);const edgeLabel=new CSS2DObject(text);edgeLabel.position.copy(curve.getPoint(.5));network.add(edgeLabel);
      edgeObjects.push({edge,line,arrow,label:text,curve,pulse});
    }
    const bounds=new THREE.Box3().setFromPoints([...positions.values()]),center=bounds.getCenter(new THREE.Vector3());
    const size=bounds.getSize(new THREE.Vector3());
    reset=()=>{const distance=Math.max((size.y+8),(size.x+10)/Math.max(camera.aspect,.4))*.5/Math.tan(THREE.MathUtils.degToRad(21));controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(1.8,1.0,Math.max(29,distance)));controls.update();};
    function highlight(selected:string|null){
      focused=selected;
      const active=new Set(nodes.filter(n=>n.data.hazardId===selected).map(n=>n.id));if(sceneNode)active.add(sceneNode.id);
      for(const [id,button]of buttons){button.classList.toggle('is-dim',!!selected&&!active.has(id));button.classList.toggle('is-selected',id===selected);}
      for(const {edge,line,arrow,label,pulse}of edgeObjects){const emphasized=!!selected&&active.has(edge.source)&&active.has(edge.target),dim=!!selected&&!emphasized;
        (line.material as THREE.Material).opacity=dim?.10:emphasized?.95:.60;(arrow.material as THREE.Material).opacity=dim?.1:.8;label.classList.toggle('is-active',emphasized);pulse.visible=emphasized&&!reducedMotion;}
    }
    let initialized=false;
    const resize=()=>{const w=element.clientWidth,h=element.clientHeight;renderer.setSize(w,h);labels.setSize(w,h);camera.aspect=w/Math.max(h,1);camera.updateProjectionMatrix();if(!initialized){reset();initialized=true;}};
    const observer=new ResizeObserver(resize);observer.observe(element);resize();highlight(latest.current.selected);
    runtime.current={zoom:factor=>{camera.position.sub(controls.target).multiplyScalar(factor).add(controls.target);controls.update();},reset,rotate:enabled=>{autoRotate=enabled;controls.autoRotate=enabled&&!hovering;},highlight};
    let animation=0,previous=performance.now(),elapsed=0;
    const draw=(now:number)=>{const dt=Math.min((now-previous)/1000,.05);previous=now;elapsed+=dt;controls.update(dt);
      for(let i=0;i<edgeObjects.length;i++){const e=edgeObjects[i];if(e.pulse.visible)e.pulse.position.copy(e.curve.getPoint((elapsed*.19+i*.137)%1));}
      renderer.render(scene,camera);labels.render(scene,camera);element.dataset.azimuth=String(controls.getAzimuthalAngle());element.dataset.focused=focused||'';animation=requestAnimationFrame(draw);
    };
    animation=requestAnimationFrame(draw);
    return()=>{cancelAnimationFrame(animation);observer.disconnect();controls.dispose();runtime.current=null;scene.traverse(o=>{if(o instanceof THREE.Mesh||o instanceof THREE.Line){o.geometry.dispose();for(const m of Array.isArray(o.material)?o.material:[o.material])m.dispose();}});renderer.dispose();renderer.domElement.remove();labels.domElement.remove();};
  },[topology]);
  return <div className="graph-body spatial-graph network-graph">
    <div ref={host} className="spatial-graph-canvas"/>
    <div className="network-overview"><span className="network-eyebrow">RELATION EXPLORER</span><h3>위험의 연결을<br/>한눈에.</h3><p>현장에서 발견한 대상과<br/>영상 근거, 점검의 관계를 탐색하세요.</p><div className="network-counts"><div><strong>{String(hazards.length).padStart(2,'0')}</strong><span>점검 항목</span></div><div><strong>{String(evidenceCount).padStart(2,'0')}</strong><span>영상 근거</span></div></div><div className="network-legend"><span><i className="risk"/>위험 해석</span><span><i className="evidence"/>영상 근거</span><span><i/>대상 · 점검</span></div></div>
    {inspected&&<div className="network-inspector"><div><span>{kindNames[String(inspected.data.kind)]}</span><small>{props.edges.filter(e=>e.source===inspected.id||e.target===inspected.id).length}개 직접 연결</small></div><h4>{String(inspected.data.label)}</h4><p>{inspected.data.kind==='hazard'?'관찰 근거와 점검 제안이 연결된 항목입니다.':inspected.data.kind==='scene'?'입력된 현장에 속한 대상들을 연결합니다.':'선택하면 해당 점검 항목과 원본 영상 근거로 연결됩니다.'}</p>{inspected.data.hazardId!=null&&<button onClick={()=>props.onSelect(String(inspected.data.hazardId),inspected.data.kind==='evidence'?inspected.id:undefined)}>점검 선택<ArrowUpRight size={13}/></button>}</div>}
    <div className="spatial-graph-toolbar"><button aria-label="그래프 확대" title="확대" onClick={()=>runtime.current?.zoom(.82)}><ZoomIn size={16}/></button><button aria-label="그래프 축소" title="축소" onClick={()=>runtime.current?.zoom(1.22)}><ZoomOut size={16}/></button><button title="전체 관계 맞추기" onClick={()=>runtime.current?.reset()}><Expand size={16}/></button><span className="network-toolbar-divider"/><button className={rotating?'active':''} onClick={()=>{runtime.current?.rotate(!rotating);setRotating(!rotating);}}>{rotating?<Pause size={13}/>:<Play size={13}/>}자동 회전</button></div>
    <div className="network-meta"><span>{props.nodes.length} NODES / {props.edges.length} LINKS</span><small>의미 관계 · 실제 현장 좌표와 무관</small></div>
    <div className="spatial-graph-guide">드래그 회전 · 휠 확대 · 우클릭 드래그 이동</div>
    {error&&<div className="graph-empty spatial-graph-error">{error}</div>}
  </div>;
}
