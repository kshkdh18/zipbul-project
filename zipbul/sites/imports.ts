import {z} from 'zod';
import {ApiError,json,type SiteEnv,type StoredScene} from './api';
import type {SceneData} from '../lib/types';
// Node/FFmpeg prepares inputs. R2 serves every completed asset independently.
const CHUNK=8*1024*1024;
interface CopyAsset {name:string;size:number;uploadId?:string;parts:{partNumber:number;etag:string}[];done?:boolean}
interface ImportState {id:string;status:string;phase:string;sceneId?:string;record?:StoredScene;assets?:CopyAsset[];error?:string}
const validId=(id:string)=>z.string().regex(/^import-[\w-]+$/).parse(id);
const key=(id:string)=>`imports/${validId(id)}/state.json`;
async function store(env:SiteEnv,s:ImportState){await env.BUCKET.put(key(s.id),JSON.stringify(s));}
async function read(env:SiteEnv,id:string){const object=await env.BUCKET.get(key(id));if(!object)throw new ApiError(404,'가져오기를 찾을 수 없습니다.');return await object.json<ImportState>();}
function origin(env:SiteEnv){if(!env.ZIPBUL_IMPORT_ORIGIN)throw new ApiError(503,'새 파일 처리 서버가 연결되지 않았습니다.');return new URL(env.ZIPBUL_IMPORT_ORIGIN).origin;}
async function upstream(env:SiteEnv,path:string,init:RequestInit={}){
  const base=origin(env);let response:Response;
  try{response=await fetch(base+path,{...init,headers:{...init.headers,Origin:base},redirect:'manual',signal:AbortSignal.timeout(55000)});}catch(error){console.error('import upstream failure',String(error));throw new ApiError(503,'새 파일 처리 서버에 연결할 수 없습니다. 연결된 Mac과 터널이 켜져 있는지 확인하세요.');}
  if(!response.ok){const message=await response.text();throw new ApiError(response.status<500?response.status:503,`파일 처리 요청 실패 (${response.status}): ${message.slice(0,250)}`);}return response;
}
function publicState(s:ImportState){return {id:s.id,status:s.status,phase:s.phase,sceneId:s.sceneId,error:s.error};}
async function prepare(env:SiteEnv,s:ImportState,sceneId:string){
  if(!/^scene-[\w-]+$/.test(sceneId))throw new ApiError(502,'처리된 현장 ID가 잘못됐습니다.');
  const scene=await (await upstream(env,`/api/scenes/${sceneId}/export`)).json() as SceneData;
  if(scene.id!==sceneId||!scene.frames.length)throw new ApiError(502,'준비된 현장 자료가 없습니다.');
  const path=`/api/scenes/${sceneId}/assets/mesh`;
  const header=await (await upstream(env,path,{headers:{Range:'bytes=0-19'}})).arrayBuffer();
  if(header.byteLength!==20||new DataView(header).getUint32(0,true)!==0x46546c67)throw new ApiError(502,'GLB 형식을 확인하지 못했습니다.');
  const size=new DataView(header).getUint32(12,true);if(size>8*1024*1024)throw new ApiError(413,'GLB 메타데이터가 너무 큽니다.');
  const gltf=await (await upstream(env,path,{headers:{Range:`bytes=20-${19+size}`}})).json() as any;
  const surfaces:number[]=[];
  const visit=(i:number)=>{const n=gltf.nodes[i];if(n.mesh!==undefined)for(const p of gltf.meshes[n.mesh].primitives)surfaces.push(gltf.accessors[p.indices??p.attributes.POSITION].count/3);for(const child of n.children||[])visit(child);};
  for(const i of gltf.scenes[gltf.scene||0].nodes||[])visit(i);
  scene.navigationRevision-=1;
  s.record={scene,manual:{revision:0,hazards:{},reviews:{},navigationRevision:1,corrections:[]},surfaces,createdAt:new Date().toISOString(),history:{}};
  s.sceneId=sceneId;s.assets=[];
  for(const name of ['mesh','video','collision','original',...scene.frames.map(f=>f.id)]){
    const head=await upstream(env,`/api/scenes/${sceneId}/assets/${name}`,{method:'HEAD'});
    const size=Number(head.headers.get('content-length'));if(!Number.isSafeInteger(size)||size<=0)throw new ApiError(502,'자료 크기를 확인하지 못했습니다.');s.assets.push({name,size,parts:[]});
  }
  s.status='running';s.phase='Sites 자료 저장 준비';await store(env,s);
}
async function copyNext(env:SiteEnv,s:ImportState){
  const a=s.assets!.find(a=>!a.done);
  if(!a){
    const exists=await env.DB.prepare('SELECT id FROM scenes WHERE id=?').bind(s.sceneId).first();
    if(!exists)await env.DB.prepare('INSERT INTO scenes(id,title,created_at,data,version) VALUES(?,?,?,?,0)').bind(s.sceneId,s.record!.scene.title,s.record!.createdAt,JSON.stringify(s.record)).run();
    s.status='completed';s.phase='현장 준비 완료';delete s.record;delete s.assets;await store(env,s);return;
  }
  const assetKey=`${s.sceneId}/${a.name}`;const existing=await env.BUCKET.head(assetKey);
  if(existing?.size===a.size){a.done=true;await store(env,s);return;}
  if(!a.uploadId){const u=await env.BUCKET.createMultipartUpload(assetKey,{httpMetadata:{contentType:a.name==='video'?'video/mp4':a.name.startsWith('frame-')?'image/jpeg':'model/gltf-binary'}});a.uploadId=u.uploadId;await store(env,s);}
  const offset=a.parts.length*CHUNK;
  if(offset<a.size){
    const end=Math.min(a.size-1,offset+CHUNK-1),response=await upstream(env,`/api/scenes/${s.sceneId}/assets/${a.name}`,{headers:{Range:`bytes=${offset}-${end}`}});
    if(response.status!==206||response.headers.get('content-range')!==`bytes ${offset}-${end}/${a.size}`)throw new ApiError(502,'자료 구간을 확인하지 못했습니다.');
    const bytes=await response.arrayBuffer();if(bytes.byteLength!==end-offset+1)throw new ApiError(502,'자료 전송이 중단됐습니다. 다시 시도해 주세요.');
    a.parts.push(await env.BUCKET.resumeMultipartUpload(assetKey,a.uploadId).uploadPart(a.parts.length+1,bytes));await store(env,s);
  }
  if(a.parts.length*CHUNK>=a.size){const done=await env.BUCKET.resumeMultipartUpload(assetKey,a.uploadId).complete(a.parts);if(done.size!==a.size)throw new ApiError(502,'저장한 자료 크기가 다릅니다.');a.done=true;}
  const total=s.assets!.reduce((n,x)=>n+x.size,0),received=s.assets!.reduce((n,x)=>n+(x.done?x.size:Math.min(x.parts.length*CHUNK,x.size)),0);
  s.phase=`Sites 자료 저장 ${Math.round(received/total*100)}%`;await store(env,s);
}
export async function handleImport(request:Request,env:SiteEnv,parts:string[],_ctx?:unknown){
  const url=new URL(request.url),method=request.method;
  if(parts[0]==='uploads'&&parts.length===1&&method==='POST'){
    const response=await upstream(env,'/api/uploads',{method:'POST',headers:{'Content-Type':'application/json'},body:await request.text()});const result=await response.json() as {id:string;chunkSize:number};validId(result.id);
    await store(env,{id:result.id,status:'uploading',phase:'원본 업로드 중'});return json(result,201);
  }
  const id=validId(parts[1]),s=await read(env,id);
  if(parts[0]==='uploads'&&method==='PUT'&&['mesh','video','frames'].includes(parts[2])){
    if(s.status!=='uploading')throw new ApiError(409,'이미 준비를 시작한 업로드입니다.');
    const offset=z.coerce.number().int().nonnegative().parse(url.searchParams.get('offset'));
    const bytes=await request.arrayBuffer();if(bytes.byteLength>4*1024*1024)throw new ApiError(413,'전송 조각이 너무 큽니다.');
    return json(await (await upstream(env,`/api/uploads/${id}/${parts[2]}?offset=${offset}`,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:bytes})).json());
  }
  if(parts[0]==='uploads'&&parts[2]==='complete'&&method==='POST'){
    if(s.status==='uploading'){const job=await (await upstream(env,`/api/uploads/${id}/complete`,{method:'POST'})).json() as ImportState;s.status=job.status;s.phase=job.phase;await store(env,s);}return json(publicState(s),202);
  }
  if(parts[0]==='imports'&&parts.length===2&&method==='GET'){
    if(s.status==='completed'||s.status==='failed')return json(publicState(s));
    if(!s.record){const job=await (await upstream(env,`/api/imports/${id}`)).json() as ImportState;if(job.status!=='completed'){s.status=job.status;s.phase=job.phase;s.error=job.error;await store(env,s);return json(publicState(s));}await prepare(env,s,job.sceneId!);}
    await copyNext(env,s);return json(publicState(s));
  }
  throw new ApiError(404,'없는 가져오기 요청입니다.');
}
