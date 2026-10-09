import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import type {LocalScene, ManualState, SceneData, Hazard, Run, RouteRecord} from '../lib/types';
import {fittedScene,RECONSTRUCTION_VERSION} from '../lib/scene-layout';
import {representativeEnhancements} from '../lib/representative-room';
export const root=path.resolve(process.env.ZIPBUL_DATA_DIR||'data/scenes');fs.mkdirSync(root,{recursive:true});
export function sceneDir(id:string){if(!/^scene-[\w-]+$/.test(id))throw new Error('잘못된 현장 ID');return path.join(root,id);}
export function read<T>(file:string,fallback:T):T {try{return JSON.parse(fs.readFileSync(file,'utf8'));}catch(e:any){if(e.code==='ENOENT')return fallback;throw e;}}
export function write(file:string,value:unknown){fs.mkdirSync(path.dirname(file),{recursive:true});const tmp=`${file}.${crypto.randomUUID()}.tmp`;fs.writeFileSync(tmp,JSON.stringify(value,null,2));fs.renameSync(tmp,file);}
export function local(id:string){const s=read<LocalScene|null>(path.join(sceneDir(id),'scene.json'),null);if(!s)throw new Error('현장을 찾을 수 없습니다.');return s;}
export function list(){return fs.readdirSync(root).filter(x=>/^scene-[\w-]+$/.test(x)).map(id=>{try{const s=local(id);return {id,title:s.title,createdAt:s.createdAt};}catch{return null;}}).filter(Boolean).sort((a,b)=>(b?.createdAt||'').localeCompare(a?.createdAt||''));}
export function manual(id:string){return read<ManualState>(path.join(sceneDir(id),'manual.json'),{revision:0,hazards:{},reviews:{},navigationRevision:1,corrections:[]});}
export function saveManual(id:string,m:ManualState){write(path.join(sceneDir(id),'manual.json'),m);}
export function runs(id:string){return read<Run[]>(path.join(sceneDir(id),'runs.json'),[]);}
export function runDetail(id:string,runId:string){
  const run=runs(id).find(r=>r.id===runId);if(!run)return null;
  const dir=path.join(sceneDir(id),'revisions');
  const files=fs.existsSync(dir)?fs.readdirSync(dir).filter(name=>name.startsWith(`${run.id}-`)&&/^run-[\w-]+-\d+\.json$/.test(name)).sort():[];
  const latest=files.at(-1),hazards=latest?read<Hazard[]>(path.join(dir,latest),[]).filter(h=>h.runId===run.id):[];
  return {run,hazards,savedAt:latest?new Date(Number(latest.match(/-(\d+)\.json$/)![1])).toISOString():null};
}
export function updateRun(id:string,runId:string,fn:(r:Run)=>void){const all=runs(id);const r=all.find(x=>x.id===runId);if(!r)throw new Error('분석 실행이 없습니다.');fn(r);write(path.join(sceneDir(id),'runs.json'),all);return r;}
export function snapshot(id:string):SceneData {
  const {files,sourceDirectory,createdAt,...s}=local(id);const m=manual(id);
  const output=read<Hazard[]>(path.join(sceneDir(id),'hazards.json'),[]);const byId=new Map(output.map(h=>[h.id,h]));
  for(const [hid,h]of Object.entries(m.hazards)){const existing=byId.get(hid);byId.set(hid,existing?{...existing,anchor:h.anchor,evidence:h.origin==='manual'?h.evidence:existing.evidence}:{...h,retained:h.origin!=='manual'});}
  for(const h of byId.values()){h.review=m.reviews[h.id]?.status||'unreviewed';if(h.anchor&&h.anchor.assetRevision!==s.assetRevision)h.anchor={...h.anchor,status:'stale'};}
  // Bump when collision simplification or fitted colliders change; prior route audits become stale.
  const navigationRevision=m.navigationRevision+RECONSTRUCTION_VERSION*100000;
  const navigationChecks=read<RouteRecord[]>(path.join(sceneDir(id),'navigation.json'),[]).map(r=>{const stale=r.assetRevision!==s.assetRevision||r.navigationRevision!==navigationRevision;return {...r,stale,valid:!stale&&r.valid};});
  return {...s,reconstruction:fittedScene(s.assetRevision).length?{version:RECONSTRUCTION_VERSION,assetCount:fittedScene(s.assetRevision).length,sourceFrameIds:s.frames.map(f=>f.id)}:undefined,navigationChecks,hazards:[...byId.values()],runs:runs(id),manualRevision:m.revision,navigationRevision,corrections:m.corrections,enhancements:representativeEnhancements(s.assetRevision)};
}
export function publish(id:string,runId:string,hazards:Hazard[]){
  if(runs(id).find(r=>r.id===runId)?.status==='canceled')return;
  const old=read<Hazard[]>(path.join(sceneDir(id),'hazards.json'),[]);const merged=new Map(old.map(h=>[h.id,h]));for(const h of hazards)merged.set(h.id,h);
  const records=[...merged.values()];write(path.join(sceneDir(id),'revisions',`${runId}-${Date.now()}.json`),records);write(path.join(sceneDir(id),'hazards.json'),records);
}
