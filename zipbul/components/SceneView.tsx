'use client';
import {forwardRef,useEffect,useImperativeHandle,useRef} from 'react';
import * as THREE from 'three';
import {GLTFLoader} from 'three/examples/jsm/loaders/GLTFLoader.js';
import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
import type {Anchor,Hazard,NavigationSegment,RuntimeInfo,SceneData,SceneHandle,Vec3} from '../lib/types';
import {canFocus} from '../lib/contracts';
import {partitionMesh} from '../lib/spatial-mesh';
import {createFurniture} from '../lib/furniture';
import {createReconstructedScene} from '../lib/reconstructed-scene';
import {EffectComposer} from 'three/examples/jsm/postprocessing/EffectComposer.js';
import {RenderPass} from 'three/examples/jsm/postprocessing/RenderPass.js';
import {SSAOPass} from 'three/examples/jsm/postprocessing/SSAOPass.js';
import {OutputPass} from 'three/examples/jsm/postprocessing/OutputPass.js';
import {RoomEnvironment} from 'three/examples/jsm/environments/RoomEnvironment.js';
type Props={scene:SceneData;mode:'analysis'|'walk';enhanced:boolean;selectedId:string|null;mapping:boolean;draftAnchor?:Anchor|null;route:Vec3[];onInfo:(i:RuntimeInfo)=>void;onPick:(a:Anchor)=>void;onMarkers:(m:{id:string;x:number;y:number;visible:boolean}[])=>void;onSelect:(id:string)=>void};
type Runtime={handle:SceneHandle;dispose:()=>void;update:(p:Props)=>void};
declare global {interface Window {render_game_to_text?:()=>string;advanceTime?:(ms:number)=>Promise<void>;zipbulScene?:SceneHandle;}}
const asVec=(v:{x:number;y:number;z:number}):Vec3=>[v.x,v.y,v.z];
const vector=(v:Vec3)=>new THREE.Vector3(...v);
let physicsReady:Promise<typeof import('@dimforge/rapier3d-compat').default>|undefined;
function physics(){return physicsReady??=(async()=>{const R=(await import('@dimforge/rapier3d-compat')).default;await R.init();return R;})();}

const SceneView=forwardRef<SceneHandle,Props>(function SceneView(props,ref){
  const host=useRef<HTMLDivElement>(null),runtime=useRef<Runtime|null>(null),latest=useRef(props);latest.current=props;
  useImperativeHandle(ref,()=>({overview:()=>runtime.current?.handle.overview(),zoom:d=>runtime.current?.handle.zoom(d),returnToPlayer:()=>runtime.current?.handle.returnToPlayer(),focus:h=>runtime.current?.handle.focus(h)||false,cameraFromFrame:(f,a)=>runtime.current?.handle.cameraFromFrame(f,a),reset:()=>runtime.current?.handle.reset(),beginWalk:()=>runtime.current?.handle.beginWalk(),getInfo:()=>runtime.current!.handle.getInfo(),getCamera:()=>runtime.current!.handle.getCamera(),validatePath:t=>runtime.current!.handle.validatePath(t)}),[]);
  useEffect(()=>{runtime.current?.update(props);},[props]);
  useEffect(()=>{
    if(!host.current)return;let stopped=false;let dispose:undefined|(()=>void);
    void createScene(host.current,()=>latest.current,()=>stopped).then(r=>{if(stopped){r.dispose();return;}runtime.current=r;dispose=r.dispose;r.update(latest.current);}).catch(e=>{if(!stopped)latest.current.onInfo({ready:false,progress:`장면 준비 오류: ${e.message}`,camera:[0,0,0],target:[0,0,0],player:[0,0,0],grounded:false,paused:true,fps:0,mode:'analysis',correctionIds:[],meshTriangles:0,navigationRevision:1});});
    return()=>{stopped=true;dispose?.();runtime.current=null;};
  },[props.scene.id]);
  return <div ref={host} className="scene-canvas" aria-label="현장 3D 공간"/>;
});
export default SceneView;

async function createScene(host:HTMLDivElement,getProps:()=>Props,stopped:()=>boolean):Promise<Runtime>{
  const source=getProps().scene;
  const info:RuntimeInfo={ready:false,progress:'원본 공간 불러오는 중',camera:source.spawn.position,target:source.spawn.target,player:source.spawn.position,grounded:false,paused:true,fps:0,mode:'analysis',correctionIds:[],meshTriangles:source.sourceInfo.triangles,navigationRevision:source.navigationRevision};
  const report=()=>{if(!stopped())getProps().onInfo({...info});};report();
  const renderer=new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance',preserveDrawingBuffer:true});
  renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setClearColor(0x24272a);renderer.shadowMap.enabled=true;renderer.shadowMap.autoUpdate=false;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
  renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.NoToneMapping;
  host.appendChild(renderer.domElement);renderer.domElement.tabIndex=0;
  const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(58,1,.05,140);
  camera.position.copy(vector(source.spawn.position));camera.lookAt(vector(source.spawn.target));
  const composer=new EffectComposer(renderer),ssao=new SSAOPass(scene,camera,1,1,16),outputPass=new OutputPass();ssao.kernelRadius=.28;ssao.minDistance=.002;ssao.maxDistance=.04;composer.addPass(new RenderPass(scene,camera));composer.addPass(ssao);composer.addPass(outputPass);
  const controls=new OrbitControls(camera,renderer.domElement);controls.target.copy(vector(source.spawn.target));controls.enableDamping=true;controls.dampingFactor=.12;controls.minDistance=.1;controls.maxDistance=70;controls.maxPolarAngle=Math.PI;
  const ambient=new THREE.HemisphereLight(0xffffff,0x9c968d,1.3);scene.add(ambient);
  const sun=new THREE.DirectionalLight(0xfff4df,2.3);sun.position.set(-5.4,1.42,2.8);sun.target.position.set(-4.5,-1.36,3.1);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.bias=-.0008;sun.shadow.normalBias=.03;Object.assign(sun.shadow.camera,{left:-18,right:18,top:18,bottom:-18,near:.05,far:40});scene.add(sun,sun.target);
  if(source.assetRevision==='70dc87f915b3ace9'){sun.position.set(6,12,8);sun.target.position.set(8,-1.4,1);sun.intensity=1.65;ambient.intensity=1.65;Object.assign(sun.shadow.camera,{left:-23,right:23,top:23,bottom:-23,far:65});}
  const markers=new THREE.Group();scene.add(markers);const correctionVisuals=new THREE.Group();scene.add(correctionVisuals);
  let routeLine:THREE.Line|undefined;let shaderMode=false;let ready=false;let mode='analysis',paused=true,inspecting=false;
  let materialPairs:{mesh:THREE.Mesh;original:THREE.Material|THREE.Material[];enhanced:THREE.Material|THREE.Material[]}[]=[];sun.visible=false;ambient.visible=false;
  const loader=new GLTFLoader();
  const loaded=await loader.loadAsync(source.meshUrl,p=>{info.progress=`원본 공간 준비 ${p.total?Math.round(p.loaded/p.total*100):Math.round(p.loaded/1048576)}${p.total?'%':' MB'}`;report();});
  if(stopped()){loaded.scene.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();for(const m of Array.isArray(o.material)?o.material:[o.material]){(m as THREE.MeshBasicMaterial).map?.dispose();m.dispose();}}});controls.dispose();renderer.dispose();renderer.domElement.remove();throw new Error('장면 준비가 취소되었습니다.');}
  const model=loaded.scene;partitionMesh(model);model.updateMatrixWorld(true);scene.add(model);
  const rebuilt=await createReconstructedScene(source);scene.add(rebuilt.group);
  const pmrem=new THREE.PMREMGenerator(renderer);const roomEnvironment=new RoomEnvironment();const environment=pmrem.fromScene(roomEnvironment,.04).texture;roomEnvironment.dispose();pmrem.dispose();scene.environment=environment;scene.environmentIntensity=.35;
  const furniture=createFurniture(rebuilt.records.length?[]:source.enhancements||[]);furniture.visible=false;scene.add(furniture);
  const replacementBounds=(rebuilt.records.length?[]:source.enhancements||[]).map(r=>new THREE.Box3(vector(r.bounds.min),vector(r.bounds.max)));
  const materialCache=new Map<THREE.Material,THREE.Material>();
  model.traverse(o=>{if(!(o instanceof THREE.Mesh))return;
    if(!o.geometry.attributes.normal)o.geometry.computeVertexNormals();
    const convert=(m:THREE.Material)=>{if(materialCache.has(m))return materialCache.get(m)!;const a=m as THREE.MeshBasicMaterial;const n=new THREE.MeshStandardMaterial({map:a.map,color:a.color||new THREE.Color(0x999999),side:THREE.DoubleSide,roughness:.94,metalness:0});if(n.map)n.map.anisotropy=Math.min(renderer.capabilities.getMaxAnisotropy(),8);materialCache.set(m,n);return n;};
    materialPairs.push({mesh:o,original:o.material,enhanced:Array.isArray(o.material)?o.material.map(convert):convert(o.material)});o.castShadow=true;o.receiveShadow=true;
    const g=o.geometry;if(g.index&&replacementBounds.some(b=>g.boundingBox&&b.intersectsBox(g.boundingBox))){
      const p=g.getAttribute('position'),idx=g.index,kept:number[]=[];const point=new THREE.Vector3();
      for(let i=0;i<idx.count;i+=3){const a=idx.getX(i),b=idx.getX(i+1),c=idx.getX(i+2);point.set((p.getX(a)+p.getX(b)+p.getX(c))/3,(p.getY(a)+p.getY(b)+p.getY(c))/3,(p.getZ(a)+p.getZ(b)+p.getZ(c))/3);if(!replacementBounds.some(b=>b.containsPoint(point)))kept.push(a,b,c);}
      g.userData.originalIndex=idx;g.userData.enhancedIndex=new THREE.BufferAttribute(Uint32Array.from(kept),1);
    }
  });
  const originalNeedsLight=materialPairs.some(p=>(Array.isArray(p.original)?p.original:[p.original]).some(m=>!(m instanceof THREE.MeshBasicMaterial)));ambient.visible=originalNeedsLight;
  info.progress='이동·충돌 공간 준비 중';report();
  const R=await physics();
  const world=new R.World({x:0,y:-9.81,z:0});
  const collisionGLB=await loader.loadAsync(source.collisionUrl);if(stopped()){world.free();controls.dispose();scene.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();for(const m of Array.isArray(o.material)?o.material:[o.material]){(m as THREE.MeshBasicMaterial).map?.dispose();m.dispose();}}});renderer.dispose();renderer.domElement.remove();throw new Error('장면 준비가 취소되었습니다.');}collisionGLB.scene.updateMatrixWorld(true);
  collisionGLB.scene.traverse(o=>{if(!(o instanceof THREE.Mesh))return;const g=o.geometry.clone().applyMatrix4(o.matrixWorld);const pos=new Float32Array(g.attributes.position.array),ind=g.index?new Uint32Array(g.index.array):Uint32Array.from({length:pos.length/3},(_,i)=>i);const collider=world.createCollider(R.ColliderDesc.trimesh(pos,ind).setFriction(.6));if(rebuilt.colliders.length)collider.setEnabled(false);g.dispose();});
  const fittedColliderIds=new Map<number,string>();
  for(const r of rebuilt.colliders){const c=world.createCollider(R.ColliderDesc.cuboid(...r.half).setTranslation(...r.position).setRotation({x:0,y:Math.sin(r.yaw/2),z:0,w:Math.cos(r.yaw/2)}));fittedColliderIds.set(c.handle,r.id);}
  for(const r of rebuilt.records.length?[]:source.enhancements||[]){if(r.kind==='desk')continue;const half=r.kind==='lectern'?[.44,.51,.57]:[.23,.26,.23];const c=world.createCollider(R.ColliderDesc.cuboid(half[0],half[1],half[2]).setTranslation(r.position[0],r.position[1]+(r.kind==='lectern'?.51:.4),r.position[2]).setRotation({x:0,y:Math.sin(r.yaw/2),z:0,w:Math.cos(r.yaw/2)}));fittedColliderIds.set(c.handle,r.id);}
  let correctionHandles:number[]=[];const correctionIds=new Map<number,string>();let navRevision=-1;
  const capsuleHalf=.57,capsuleRadius=.22,eyeOffset=.75;
  const body=world.createRigidBody(R.RigidBodyDesc.kinematicPositionBased().setTranslation(...source.spawn.position));
  const playerCollider=world.createCollider(R.ColliderDesc.capsule(capsuleHalf,capsuleRadius),body);
  const controller=world.createCharacterController(.025);controller.enableAutostep(.22,.18,true);controller.enableSnapToGround(.25);controller.setMaxSlopeClimbAngle(Math.PI/4);
  let spawn=new THREE.Vector3(...source.spawn.position),walkTarget=vector(source.spawn.target),yaw=0,pitch=0,vy=0;const keys=new Set<string>();
  const euler=new THREE.Euler(0,0,0,'YXZ');
  function syncAngles(){euler.setFromQuaternion(camera.quaternion,'YXZ');yaw=euler.y;pitch=euler.x;}
  function groundAt(p:THREE.Vector3,range=4){return world.castRayAndGetNormal(new R.Ray({x:p.x,y:p.y,z:p.z},{x:0,y:-1,z:0}),range,true,undefined,undefined,playerCollider,body);}
  function reset(){focusMotion=undefined;world.step();let start=vector(source.spawn.position);let supported=false;
    const preferred=source.assetRevision==='70dc87f915b3ace9'?source.frames[7]?.camera.slice(0,3).map(r=>r[3]) as Vec3:source.enhancements?.length?source.frames[2]?.camera.slice(0,3).map(r=>r[3]) as Vec3:source.spawn.position;
    for(const candidate of [preferred,source.spawn.position,...source.cameraPath]){if(candidate?.length!==3)continue;const p=vector(candidate),hit=groundAt(p,3);if(!hit||hit.timeOfImpact<.85||Math.abs(hit.normal.y)<.7)continue;p.y-=hit.timeOfImpact-(capsuleHalf+capsuleRadius+.035);const blocked=world.intersectionWithShape(p,{x:0,y:0,z:0,w:1},new R.Capsule(capsuleHalf,capsuleRadius),undefined,undefined,playerCollider,body);if(blocked)continue;start=p;supported=true;const nearest=source.frames.filter(f=>f.camera.length===4).sort((a,b)=>vector(a.camera.slice(0,3).map(r=>r[3]) as Vec3).distanceTo(p)-vector(b.camera.slice(0,3).map(r=>r[3]) as Vec3).distanceTo(p))[0];if(nearest)walkTarget=new THREE.Vector3(...nearest.camera.slice(0,3).map((r,i)=>candidate[i]-r[2]*3) as Vec3);break;}
    if(!supported)start.y-=eyeOffset;
    body.setTranslation(start,true);body.setNextKinematicTranslation(start);world.step();spawn.copy(start);vy=0;camera.position.copy(start).add(new THREE.Vector3(0,eyeOffset,0));camera.lookAt(walkTarget);syncAngles();info.player=asVec(start);info.grounded=supported;paused=true;inspecting=false;info.paused=true;
  }
  function unlock(){if(document.pointerLockElement===renderer.domElement)document.exitPointerLock();paused=true;info.paused=true;keys.clear();}
  const keyDown=(e:KeyboardEvent)=>{if((e.target as HTMLElement)?.closest('input,textarea,select,[contenteditable=true]'))return;
    if(e.code==='Escape'){focusMotion=undefined;unlock();if(inspecting)returnToPlayer();return;}
    if(e.code==='KeyF'){if(document.fullscreenElement)void document.exitFullscreen();else void host.parentElement?.requestFullscreen();return;}
    if(e.code==='KeyE'&&mode==='walk'&&!paused){const nearest=getProps().scene.hazards.filter(h=>h.anchor&&canFocus(h.anchor,source.assetRevision)).map(h=>({h,d:camera.position.distanceTo(vector(h.anchor!.position))})).sort((a,b)=>a.d-b.d)[0];if(nearest&&nearest.d<5)getProps().onSelect(nearest.h.id);return;}
    if((mode==='analysis'||!paused)&&['KeyW','KeyA','KeyS','KeyD','KeyQ','KeyE','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','ShiftLeft','ShiftRight'].includes(e.code)){if(document.querySelector('.modal-backdrop,.graph-overlay,.chat-panel'))return;e.preventDefault();keys.add(e.code);focusMotion=undefined;}
    if(mode==='analysis'&&['Equal','Minus','NumpadAdd','NumpadSubtract'].includes(e.code)){e.preventDefault();focusMotion=undefined;const direction=controls.target.clone().sub(camera.position);const factor=(e.code==='Minus'||e.code==='NumpadSubtract')?-.18:.18;camera.position.addScaledVector(direction,factor);}
  };
  const keyUp=(e:KeyboardEvent)=>keys.delete(e.code);
  const mouseMove=(e:MouseEvent)=>{if(mode!=='walk'||paused)return;if(document.pointerLockElement!==renderer.domElement&&(e.buttons!==1||e.target!==renderer.domElement))return;yaw-=e.movementX*.002;pitch=THREE.MathUtils.clamp(pitch-e.movementY*.002,-1.4,1.4);};
  let wasLocked=false;
  const lockChange=()=>{const locked=document.pointerLockElement===renderer.domElement;if(wasLocked&&!locked){paused=true;info.paused=true;keys.clear();}wasLocked=locked;report();};
  const blur=()=>{keys.clear();if(document.hidden)unlock();};
  const ray=new THREE.Raycaster(),mouse=new THREE.Vector2();let pointerStart:[number,number]=[0,0];
  const pointerDown=(e:PointerEvent)=>{focusMotion=undefined;pointerStart=[e.clientX,e.clientY];};
  function pick(e:MouseEvent){if(!ready)return;const p=getProps();if(p.mapping){if(Math.hypot(e.clientX-pointerStart[0],e.clientY-pointerStart[1])>5)return;const r=renderer.domElement.getBoundingClientRect();mouse.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);ray.setFromCamera(mouse,camera);const hit=ray.intersectObject(model,true)[0];if(hit&&hit.face){unlock();const normal=hit.face.normal.clone().transformDirection(hit.object.matrixWorld);p.onPick({position:asVec(hit.point),cameraPosition:asVec(camera.position),cameraTarget:asVec(hit.point),method:'manual',status:'verified',assetRevision:source.assetRevision,surface:{mesh:hit.object.userData.primitiveKey,face:hit.object.userData.sourceFaces?.[hit.faceIndex||0]??(hit.faceIndex||0),normal:asVec(normal)}});}return;}
    if(mode==='walk'&&!inspecting)beginWalk();
  }
  function beginWalk(){focusMotion=undefined;rebuilt.ceilingGroup.visible=true;if(!ready||mode!=='walk'||getProps().mapping)return;inspecting=false;paused=false;info.paused=false;renderer.domElement.focus({preventScroll:true});camera.position.copy(vector(asVec(body.translation()))).add(new THREE.Vector3(0,eyeOffset,0));syncAngles();void renderer.domElement.requestPointerLock()?.catch(()=>{info.progress='포인터 잠금 불가 · 드래그로 시점 조작';paused=false;info.paused=false;report();});}
  window.addEventListener('keydown',keyDown);window.addEventListener('keyup',keyUp);window.addEventListener('mousemove',mouseMove);window.addEventListener('blur',blur);document.addEventListener('pointerlockchange',lockChange);renderer.domElement.addEventListener('click',pick);renderer.domElement.addEventListener('pointerdown',pointerDown);
  let focusMotion:{from:THREE.Vector3;to:THREE.Vector3;targetFrom:THREE.Vector3;target:THREE.Vector3;t:number;duration:number}|undefined;
  controls.addEventListener('start',()=>{focusMotion=undefined;});
  let savedAnalysis:{position:THREE.Vector3;target:THREE.Vector3}|undefined;
  function setView(pos:Vec3,target:Vec3,animate=false){unlock();if(mode==='walk')controls.target.copy(camera.position).addScaledVector(camera.getWorldDirection(new THREE.Vector3()),3);inspecting=mode==='walk';focusMotion=undefined;if(animate&&!window.matchMedia('(prefers-reduced-motion: reduce)').matches){focusMotion={from:camera.position.clone(),to:vector(pos),targetFrom:controls.target.clone(),target:vector(target),t:0,duration:THREE.MathUtils.clamp(camera.position.distanceTo(vector(pos))*.045+.8,.85,1.25)};}else{camera.position.copy(vector(pos));controls.target.copy(vector(target));camera.lookAt(vector(target));if(mode==='analysis')syncAngles();}}
  function returnToPlayer(){focusMotion=undefined;inspecting=false;unlock();if(mode==='walk'){camera.position.copy(vector(asVec(body.translation()))).add(new THREE.Vector3(0,eyeOffset,0));camera.quaternion.setFromEuler(new THREE.Euler(pitch,yaw,0,'YXZ'));}else if(savedAnalysis){camera.position.copy(savedAnalysis.position);controls.target.copy(savedAnalysis.target);camera.lookAt(controls.target);}}
  function overview(){rebuilt.ceilingGroup.visible=false;const box=new THREE.Box3(vector(source.bounds.min),vector(source.bounds.max)),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()).length();setView(asVec(center.clone().add(new THREE.Vector3(size*.3,size*.65,size*.65))),asVec(center));}
  const handle:SceneHandle={overview,zoom(factor){focusMotion=undefined;camera.position.addScaledVector(controls.target.clone().sub(camera.position),factor);controls.update();},returnToPlayer,reset,beginWalk,getInfo:()=>({...info}),getCamera:()=>({position:asVec(camera.position),target:asVec(controls.target)}),focus(h){if(!canFocus(h.anchor,source.assetRevision)){focusMotion=undefined;unlock();return false;}if(!inspecting)savedAnalysis={position:camera.position.clone(),target:controls.target.clone()};const a=h.anchor!,target=vector(a.position),from=vector(a.cameraPosition),direction=from.clone().sub(target);const pos=target.clone().add(direction.normalize().multiplyScalar(Math.min(from.distanceTo(target),1.35)));setView(asVec(pos),a.position,true);return true;},cameraFromFrame(f,animate=false){if(f.camera.length!==4)return;if(animate&&!inspecting)savedAnalysis={position:camera.position.clone(),target:controls.target.clone()};const pos=f.camera.slice(0,3).map(r=>r[3]) as Vec3;const target=f.camera.slice(0,3).map((r,i)=>pos[i]-r[2]*3) as Vec3;setView(pos,target,animate);},validatePath(target){
    const points:Vec3[]=[],segments:NavigationSegment[]=[],used=new Set<string>();const revisions={assetRevision:source.assetRevision,navigationRevision:navRevision};const start=new THREE.Vector3(...asVec(body.translation()));const end=vector(target);const diff=end.clone().sub(start);diff.y=0;const length=diff.length();if(length>25)return {points,segments,...revisions,correctionIds:[],valid:false,reason:'너무 먼 대상입니다. 가까운 위치에서 다시 확인하세요.'};if(length<.2)return {points,segments,...revisions,correctionIds:[],valid:false,reason:'현재 위치와 겹칩니다.'};
    const step=diff.normalize().multiplyScalar(.15);const probeBody=world.createRigidBody(R.RigidBodyDesc.kinematicPositionBased().setTranslation(start.x,start.y,start.z));const probe=world.createCollider(R.ColliderDesc.capsule(capsuleHalf,capsuleRadius),probeBody);const check=world.createCharacterController(.025);check.enableAutostep(.22,.18,true);check.enableSnapToGround(.25);let p=start.clone(),valid=true,reason='게임 내 충돌·접지 검증';
    try{world.step();for(let i=0;i<Math.ceil(length/.15);i++){check.computeColliderMovement(probe,{x:step.x,y:-.12,z:step.z},undefined,undefined,c=>c.handle!==playerCollider.handle);const move=check.computedMovement();if(Math.hypot(move.x,move.z)<.07){valid=false;reason='벽 또는 장애물로 이동 연결이 막혀 있습니다.';break;}const from=asVec(p);p.add(new THREE.Vector3(move.x,move.y,move.z));probeBody.setNextKinematicTranslation(p);world.step();const hit=world.castRayAndGetNormal(new R.Ray({x:p.x,y:p.y,z:p.z},{x:0,y:-1,z:0}),capsuleHalf+capsuleRadius+.25,true,undefined,undefined,probe,probeBody,c=>c.handle!==playerCollider.handle);if(!hit||Math.abs(hit.normal.y)<.45){segments.push({from,to:asVec(p),valid:false,sourceSupport:'unknown',correctionIds:[]});valid=false;reason='바닥 지지를 확인하지 못한 구간입니다.';break;}const cid=correctionIds.get(hit.collider.handle)||fittedColliderIds.get(hit.collider.handle);if(cid)used.add(cid);segments.push({from,to:asVec(p),valid:true,sourceSupport:cid?'partial':'supported',correctionIds:cid?[cid]:[]});points.push([p.x,p.y-hit.timeOfImpact+.04,p.z]);}}
    finally{world.removeCharacterController(check);world.removeRigidBody(probeBody);world.step();}
    return {points:valid?points:[],segments,...revisions,correctionIds:[...used],valid,reason};
  }};
  let markerSignature='',routeReference:Vec3[]|undefined;
  function update(p:Props){
    if(mode!==p.mode){unlock();focusMotion=undefined;if(p.mode==='walk'){savedAnalysis={position:camera.position.clone(),target:controls.target.clone()};camera.position.copy(vector(asVec(body.translation()))).add(new THREE.Vector3(0,eyeOffset,0));camera.lookAt(walkTarget);syncAngles();}else{inspecting=false;if(savedAnalysis){camera.position.copy(savedAnalysis.position);controls.target.copy(savedAnalysis.target);}}mode=p.mode;info.mode=mode;controls.enabled=mode==='analysis';}
    if(shaderMode!==p.enhanced){shaderMode=p.enhanced;for(const pair of materialPairs){pair.mesh.material=shaderMode?pair.enhanced:pair.original;const g=pair.mesh.geometry;if(g.userData.originalIndex)g.setIndex(shaderMode?g.userData.enhancedIndex:g.userData.originalIndex);}furniture.visible=shaderMode;rebuilt.group.visible=shaderMode;if(rebuilt.records.length)model.visible=!shaderMode;sun.visible=shaderMode;ambient.visible=shaderMode||originalNeedsLight;renderer.toneMapping=shaderMode?THREE.ACESFilmicToneMapping:THREE.NoToneMapping;renderer.toneMappingExposure=1.12;renderer.shadowMap.needsUpdate=shaderMode;}
    if(p.mapping)unlock();
    if(navRevision!==p.scene.navigationRevision){for(const h of correctionHandles){const c=world.getCollider(h);if(c)world.removeCollider(c,true);}correctionHandles=[];correctionIds.clear();while(correctionVisuals.children.length){const m=correctionVisuals.children.pop() as THREE.Mesh;m.geometry.dispose();(m.material as THREE.Material).dispose();}
      for(const c of p.scene.corrections){const col=world.createCollider(R.ColliderDesc.cuboid(...c.halfExtents).setTranslation(...c.center));correctionHandles.push(col.handle);correctionIds.set(col.handle,c.id);const m=new THREE.Mesh(new THREE.BoxGeometry(...c.halfExtents.map(x=>x*2) as Vec3),new THREE.MeshStandardMaterial({color:0x6386a2,transparent:true,opacity:.24,roughness:1}));m.position.set(...c.center);correctionVisuals.add(m);}navRevision=p.scene.navigationRevision;info.navigationRevision=navRevision;world.step();}
    const signature=JSON.stringify([p.selectedId,p.draftAnchor,p.scene.hazards.map(h=>[h.id,h.anchor])]);
    if(signature!==markerSignature){markerSignature=signature;
    for(const m of [...markers.children]){markers.remove(m);if(m instanceof THREE.Mesh){m.geometry.dispose();(m.material as THREE.Material).dispose();}}
    if(p.draftAnchor){const m=new THREE.Mesh(new THREE.SphereGeometry(.055,16,12),new THREE.MeshBasicMaterial({color:0xe5a84b,depthTest:false}));m.position.set(...p.draftAnchor.position);m.renderOrder=9;markers.add(m);}
    for(const h of p.scene.hazards){if(!h.anchor||h.anchor.status==='stale')continue;const isSelected=p.selectedId===h.id;const m=new THREE.Mesh(new THREE.SphereGeometry(isSelected?.07:.045,12,8),new THREE.MeshBasicMaterial({color:h.anchor.status==='verified'?0xe5a84b:0x7ba8d8,transparent:true,opacity:isSelected?1:.7,depthTest:true}));m.position.set(...h.anchor.position);markers.add(m);
      if(isSelected&&canFocus(h.anchor,source.assetRevision)){const ring=new THREE.Mesh(new THREE.RingGeometry(.13,.15,48),new THREE.MeshBasicMaterial({color:0xe5a84b,side:THREE.DoubleSide,transparent:true,opacity:.85,depthWrite:false}));const normal=h.anchor.surface?vector(h.anchor.surface.normal):camera.position.clone().sub(vector(h.anchor.position)).normalize();ring.quaternion.setFromUnitVectors(new THREE.Vector3(0,0,1),normal.normalize());ring.position.copy(vector(h.anchor.position)).addScaledVector(normal,.012);markers.add(ring);}}

    }
    if(routeReference!==p.route){routeReference=p.route;
    if(routeLine){scene.remove(routeLine);routeLine.geometry.dispose();(routeLine.material as THREE.Material).dispose();routeLine=undefined;}
    if(p.route.length>1){routeLine=new THREE.Line(new THREE.BufferGeometry().setFromPoints(p.route.map(vector)),new THREE.LineDashedMaterial({color:0x7ba8d8,dashSize:.16,gapSize:.1}));routeLine.computeLineDistances();scene.add(routeLine);}}
  }
  const resize=()=>{const w=host.clientWidth,h=host.clientHeight;renderer.setSize(w,h);composer.setSize(w,h);camera.aspect=w/Math.max(h,1);camera.updateProjectionMatrix();};const observer=new ResizeObserver(resize);observer.observe(host);resize();
  let frame=0,last=performance.now(),fpsStart=last,fpsFrames=0,anim=0,manualClock=false;
  function step(dt:number){
    if(mode==='analysis'){const forward=camera.getWorldDirection(new THREE.Vector3()),right=new THREE.Vector3().crossVectors(forward,camera.up).normalize();const dz=(keys.has('KeyW')||keys.has('ArrowUp')?1:0)-(keys.has('KeyS')||keys.has('ArrowDown')?1:0),dx=(keys.has('KeyD')||keys.has('ArrowRight')?1:0)-(keys.has('KeyA')||keys.has('ArrowLeft')?1:0),dy=(keys.has('KeyE')?1:0)-(keys.has('KeyQ')?1:0);if(dx||dy||dz){const delta=forward.multiplyScalar(dz).addScaledVector(right,dx).add(new THREE.Vector3(0,dy,0)).normalize().multiplyScalar(dt*(keys.has('ShiftLeft')||keys.has('ShiftRight')?5:2));camera.position.add(delta);controls.target.add(delta);}}
    if(mode==='walk'&&!paused&&!inspecting){const x=(keys.has('KeyD')||keys.has('ArrowRight')?1:0)-(keys.has('KeyA')||keys.has('ArrowLeft')?1:0),z=(keys.has('KeyS')||keys.has('ArrowDown')?1:0)-(keys.has('KeyW')||keys.has('ArrowUp')?1:0);const velocity=new THREE.Vector3(x,0,z).normalize().applyAxisAngle(new THREE.Vector3(0,1,0),yaw).multiplyScalar((keys.has('ShiftLeft')?2.6:1.55)*dt);if(info.grounded&&(x||z)){const at=body.translation();const support=groundAt(new THREE.Vector3(at.x+velocity.x,at.y+.15,at.z+velocity.z),capsuleHalf+capsuleRadius+.45);if(!support||Math.abs(support.normal.y)<.5){velocity.x=0;velocity.z=0;info.progress='바닥 미확인 구간 · 이동 보류';}}
    vy=Math.max(-6,vy-9.81*dt);velocity.y=vy*dt;controller.computeColliderMovement(playerCollider,velocity);const d=controller.computedMovement(),b=body.translation();body.setNextKinematicTranslation({x:b.x+d.x,y:b.y+d.y,z:b.z+d.z});world.timestep=dt;world.step();info.grounded=controller.computedGrounded();if(info.grounded)vy=0;camera.position.copy(vector(asVec(body.translation()))).add(new THREE.Vector3(0,eyeOffset,0));camera.quaternion.setFromEuler(new THREE.Euler(pitch,yaw,0,'YXZ'));if(body.translation().y<source.bounds.min[1]-3)reset();}
    if(focusMotion){const f=focusMotion;f.t=Math.min(1,f.t+dt/f.duration);const t=f.t*f.t*(3-2*f.t);camera.position.lerpVectors(f.from,f.to,t);controls.target.lerpVectors(f.targetFrom,f.target,t);camera.lookAt(controls.target);if(f.t===1)focusMotion=undefined;}
    if(mode==='analysis')controls.update();
    info.camera=asVec(camera.position);info.target=asVec(controls.target);info.player=asVec(body.translation());info.paused=paused;
    const hit=groundAt(vector(info.player),1.2);info.correctionIds=hit?(correctionIds.get(hit.collider.handle)||fittedColliderIds.get(hit.collider.handle)?[(correctionIds.get(hit.collider.handle)||fittedColliderIds.get(hit.collider.handle))!]:[]):[];
  }
  function draw(){if(shaderMode&&rebuilt.records.length)composer.render();else renderer.render(scene,camera);if(frame++%8===0){const p=getProps();p.onMarkers(p.scene.hazards.filter(h=>h.anchor&&h.anchor.status!=='stale').map(h=>{const pos=vector(h.anchor!.position).project(camera);return {id:h.id,x:(pos.x*.5+.5)*host.clientWidth,y:(-pos.y*.5+.5)*host.clientHeight,visible:pos.z>-1&&pos.z<1&&Math.abs(pos.x)<1&&Math.abs(pos.y)<1};}));report();}}
  function tick(now:number){if(stopped())return;const dt=Math.min((now-last)/1000,.05);last=now;if(!manualClock)step(dt||1/60);draw();fpsFrames++;if(now-fpsStart>1000){info.fps=Math.round(fpsFrames*1000/(now-fpsStart));fpsFrames=0;fpsStart=now;}anim=requestAnimationFrame(tick);}
  reset();ready=true;info.ready=true;info.progress='원본 공간 준비 완료';update(getProps());camera.position.copy(vector(source.spawn.position));controls.target.copy(vector(source.spawn.target));camera.lookAt(controls.target);syncAngles();if(source.enhancements?.length&&source.frames[2])handle.cameraFromFrame(source.frames[2]);else if(!source.frames[0]?.camera.length)handle.overview();
  window.zipbulScene=handle;window.render_game_to_text=()=>JSON.stringify({reconstructedAssets:rebuilt.records.length,coordinateSystem:'ARKit meters +Y up; camera forward -Z',...info,selected:getProps().selectedId,focusMoving:!!focusMotion,mapping:getProps().mapping,hazards:getProps().scene.hazards.map(h=>({id:h.id,title:h.title,location:h.anchor?.status||'unplaced',review:h.review,position:h.anchor?.position})),routePoints:getProps().route.length});
  window.advanceTime=async(ms:number)=>{manualClock=true;for(let n=0;n<Math.ceil(ms/(1000/60));n++)step(1/60);draw();await new Promise(r=>setTimeout(r,0));};
  anim=requestAnimationFrame(tick);report();
  return {handle,update,dispose(){unlock();cancelAnimationFrame(anim);observer.disconnect();window.removeEventListener('keydown',keyDown);window.removeEventListener('keyup',keyUp);window.removeEventListener('mousemove',mouseMove);window.removeEventListener('blur',blur);document.removeEventListener('pointerlockchange',lockChange);renderer.domElement.removeEventListener('click',pick);renderer.domElement.removeEventListener('pointerdown',pointerDown);controls.dispose();world.free();environment.dispose();ssao.dispose();outputPass.dispose();composer.dispose();scene.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();const materials=Array.isArray(o.material)?o.material:[o.material];for(const m of materials){(m as THREE.MeshBasicMaterial).map?.dispose();m.dispose();}}});for(const p of materialPairs)for(const m of Array.isArray(p.enhanced)?p.enhanced:[p.enhanced])m.dispose();renderer.dispose();renderer.domElement.remove();if(window.zipbulScene===handle){delete window.zipbulScene;delete window.render_game_to_text;delete window.advanceTime;}}};
}
