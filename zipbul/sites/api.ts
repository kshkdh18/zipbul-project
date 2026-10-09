import {z} from 'zod';
import {bbox,vector} from '../lib/contracts';
import {fittedScene} from '../lib/scene-layout';
import type {SceneData,Hazard,ManualState,Run} from '../lib/types';
import {start,advance,cancel,chat} from './analysis';

export interface SiteEnv {DB:D1Database;BUCKET:R2Bucket;ZIPBUL_UPLOAD_TOKEN?:string;OPENAI_API_KEY?:string}
export interface StoredScene {scene:SceneData;manual:ManualState;surfaces:number[];createdAt:string;version?:number;analysisState?:unknown}
export class ApiError extends Error {constructor(public status:number,message:string){super(message);}}
export const json=(value:unknown,status=200)=>Response.json(value,{status,headers:{'Cache-Control':'no-store'}});
export async function load(env:SiteEnv,id:string):Promise<StoredScene>{
  if(!/^scene-[\w-]+$/.test(id))throw new ApiError(400,'잘못된 현장 ID입니다.');
  const row=await env.DB.prepare('SELECT data,version FROM scenes WHERE id=?').bind(id).first<{data:string;version:number}>();
  if(!row)throw new ApiError(404,'현장을 찾을 수 없습니다.');
  return {...JSON.parse(row.data),version:row.version};
}
export async function save(env:SiteEnv,data:StoredScene){
  const {version,...record}=data;
  const result=await env.DB.prepare('UPDATE scenes SET data=?,title=?,version=version+1 WHERE id=? AND version=?').bind(JSON.stringify(record),record.scene.title,record.scene.id,version).run();
  if(result.meta.changes!==1)throw new ApiError(409,'다른 변경이 저장됐습니다. 새로 고친 뒤 다시 시도해 주세요.');
  data.version=(version??0)+1;
}
export function snapshot(record:StoredScene):SceneData {
  const {scene:s,manual:m}=record;const byId=new Map(s.hazards.map(h=>[h.id,structuredClone(h)]));
  for(const [id,h]of Object.entries(m.hazards)){const existing=byId.get(id);byId.set(id,existing?{...existing,anchor:h.anchor,evidence:h.origin==='manual'?h.evidence:existing.evidence}:structuredClone(h));}
  for(const h of byId.values()){h.review=m.reviews[h.id]?.status||'unreviewed';if(h.anchor?.assetRevision!==s.assetRevision&&h.anchor)h.anchor.status='stale';}
  const navigationRevision=s.navigationRevision+m.navigationRevision;
  return {...s,hazards:[...byId.values()],manualRevision:m.revision,corrections:m.corrections,navigationRevision,navigationChecks:(s.navigationChecks||[]).map(r=>{const stale=r.assetRevision!==s.assetRevision||r.navigationRevision!==navigationRevision;return {...r,stale,valid:!stale&&r.valid};})};
}
function revision(r:StoredScene,p:{manualRevision:number}){if(p.manualRevision!==r.manual.revision)throw new ApiError(409,'검토 기록이 변경됐습니다. 다시 확인해 주세요.');}
const keySchema=z.string().regex(/^scene-[\w-]+\/(video|mesh|collision|original|frame-\d+)$/);
async function upload(request:Request,env:SiteEnv,action:string){
  if(!env.ZIPBUL_UPLOAD_TOKEN||request.headers.get('X-Zipbul-Upload')!==env.ZIPBUL_UPLOAD_TOKEN)throw new ApiError(403,'자료 전송 권한이 없습니다.');
  const url=new URL(request.url);
  if(action==='part'){
    const key=keySchema.parse(url.searchParams.get('key')),uploadId=z.string().min(1).parse(url.searchParams.get('uploadId')),part=z.coerce.number().int().min(1).max(10000).parse(url.searchParams.get('part'));
    if(Number(request.headers.get('content-length')||0)>10*1024*1024)throw new ApiError(413,'전송 조각이 너무 큽니다.');
    const bytes=await request.arrayBuffer();if(bytes.byteLength>10*1024*1024)throw new ApiError(413,'전송 조각이 너무 큽니다.');
    return json(await env.BUCKET.resumeMultipartUpload(key,uploadId).uploadPart(part,bytes));
  }
  const body=await request.json() as any;
  if(action==='begin'){
    const key=keySchema.parse(body.key);const existing=await env.BUCKET.head(key);
    if(existing&&existing.size===body.size&&existing.customMetadata?.sha256===body.sha256)return json({complete:true,size:existing.size});
    if(existing)throw new ApiError(409,'기존 현장의 원본 자료는 덮어쓸 수 없습니다. 새 현장 ID로 등록해 주세요.');
    const u=await env.BUCKET.createMultipartUpload(key,{httpMetadata:{contentType:z.enum(['video/mp4','model/gltf-binary','image/jpeg']).parse(body.contentType)},customMetadata:{sha256:z.string().regex(/^[a-f0-9]{64}$/).parse(body.sha256)}});
    return json({key,uploadId:u.uploadId});
  }
  if(action==='complete'){
    const key=keySchema.parse(body.key);const parts=z.array(z.object({partNumber:z.number().int().positive(),etag:z.string()})).min(1).parse(body.parts);
    const object=await env.BUCKET.resumeMultipartUpload(key,z.string().parse(body.uploadId)).complete(parts);return json({key,size:object.size});
  }
  if(action==='seed'){
    const record=body as StoredScene;const id=z.string().regex(/^scene-[\w-]+$/).parse(record.scene?.id);
    if(!record.manual||!Array.isArray(record.surfaces)||!Array.isArray(record.scene.frames))throw new ApiError(400,'현장 자료 형식이 잘못됐습니다.');
    for(const asset of ['mesh','video','collision','original',...record.scene.frames.map(f=>f.id)])if(!await env.BUCKET.head(keySchema.parse(`${id}/${asset}`)))throw new ApiError(400,`자료 전송이 완료되지 않았습니다: ${asset}`);
    const existing=await env.DB.prepare('SELECT id FROM scenes WHERE id=?').bind(id).first();if(existing)throw new ApiError(409,'이미 등록된 현장은 덮어쓰지 않습니다.');
    await env.DB.prepare('INSERT INTO scenes(id,title,created_at,data,version) VALUES(?,?,?,?,0)').bind(id,record.scene.title,record.createdAt,JSON.stringify(record)).run();return json({id},201);
  }
  throw new ApiError(404,'없는 전송 작업입니다.');
}
async function asset(request:Request,env:SiteEnv,id:string,name:string){
  const key=keySchema.parse(`${id}/${name}`);const head=await env.BUCKET.head(key);if(!head)throw new ApiError(404,'자료를 찾을 수 없습니다.');
  const headers=new Headers({'Content-Type':head.httpMetadata?.contentType||'application/octet-stream','Accept-Ranges':'bytes','ETag':head.httpEtag,'Cache-Control':'private, max-age=3600','X-Content-Type-Options':'nosniff'});
  let offset=0,end=head.size-1,status=200;const range=request.headers.get('range');
  if(range){const m=/^bytes=(\d*)-(\d*)$/.exec(range);if(!m||(!m[1]&&!m[2]))return new Response(null,{status:416,headers:{'Content-Range':`bytes */${head.size}`}});
    if(m[1]){offset=Number(m[1]);if(m[2])end=Math.min(end,Number(m[2]));}else offset=Math.max(0,head.size-Number(m[2]));
    if(offset>=head.size||offset>end)return new Response(null,{status:416,headers:{'Content-Range':`bytes */${head.size}`}});
    status=206;headers.set('Content-Range',`bytes ${offset}-${end}/${head.size}`);
  }
  headers.set('Content-Length',String(end-offset+1));if(request.method==='HEAD')return new Response(null,{status,headers});
  const object=await env.BUCKET.get(key,status===206?{range:{offset,length:end-offset+1}}:{});if(!object)throw new ApiError(404,'자료를 찾을 수 없습니다.');
  return new Response(object.body as unknown as ReadableStream,{status,headers});
}
export async function handleApi(request:Request,env:SiteEnv,ctx?:{waitUntil:(p:Promise<unknown>)=>void}):Promise<Response>{
 try{
  const url=new URL(request.url),parts=url.pathname.split('/').filter(Boolean).slice(1),method=request.method;
  if(!['GET','HEAD'].includes(method)){const origin=request.headers.get('origin');if(origin&&origin!==url.origin)throw new ApiError(403,'같은 사이트에서 요청해 주세요.');}
  if(parts[0]==='health')return json({ok:true,model:'gpt-6-astra',keyConfigured:!!env.OPENAI_API_KEY,hosting:'sites'});
  if(parts[0]==='transfer'&&method==='POST')return await upload(request,env,parts[1]);
  if(parts[0]!=='scenes')throw new ApiError(404,'요청을 찾을 수 없습니다.');
  if(parts.length===1&&method==='GET'){const rows=await env.DB.prepare('SELECT id,title,created_at AS createdAt FROM scenes ORDER BY created_at DESC').all();return json(rows.results);}
  if(parts[1]==='import')throw new ApiError(422,'새 현장은 로컬 짚불에서 영상과 GLB를 준비한 후 Sites로 전송해 주세요.');
  const id=parts[1],action=parts[2];
  if(action==='assets'&&['GET','HEAD'].includes(method))return await asset(request,env,id,parts[3]);
  const record=await load(env,id),s=snapshot(record),m=record.manual;
  if(!action&&method==='GET'){if(ctx)ctx.waitUntil(advance(env,id).catch(()=>{}));return json(s);}
  if(action==='export'&&method==='GET')return new Response(JSON.stringify(s,null,2),{headers:{'Content-Type':'application/json','Content-Disposition':'attachment; filename="zipbul-review.json"','Cache-Control':'no-store'}});
  if(action==='analyses'&&method==='POST'){
    if(parts[4]==='cancel')return json(await cancel(env,id,parts[3]));
    const run=await start(env,id,await request.json());if(ctx)ctx.waitUntil(advance(env,id).catch(()=>{}));return json(run,202);
  }
  if(action==='chat'&&method==='POST')return json(await chat(env,id,await request.json()));
  const body=await request.json();
  if(action==='mappings'&&method==='POST'){
    const p=z.object({manualRevision:z.number().int(),assetRevision:z.string(),hazardId:z.string(),position:vector,cameraPosition:vector,cameraTarget:vector,surface:z.object({mesh:z.string(),face:z.number().int().min(0),normal:vector})}).parse(body);revision(record,p);
    if(p.assetRevision!==s.assetRevision)throw new ApiError(409,'공간이 변경됐습니다. 다시 확인해 주세요.');
    const h=s.hazards.find(h=>h.id===p.hazardId);if(!h)throw new ApiError(404,'점검 대상이 없습니다.');
    const match=/^world\/primitive-(\d+)$/.exec(p.surface.mesh);
    if(!match||p.surface.face>=(record.surfaces[Number(match[1])]||0))throw new ApiError(400,'원본 GLB에서 확인할 수 없는 면입니다.');
    if(p.position.some((x,i)=>x<s.bounds.min[i]-.2||x>s.bounds.max[i]+.2))throw new ApiError(400,'원본 공간 밖의 위치입니다.');
    m.hazards[h.id]={...h,anchor:{position:p.position,cameraPosition:p.cameraPosition,cameraTarget:p.cameraTarget,surface:p.surface,assetRevision:s.assetRevision,method:'manual',status:'verified'}};m.revision++;
  }else if(action==='hazards'&&method==='POST'){
    const p=z.object({title:z.string().min(1).max(100),observation:z.string().min(1).max(1500),frameId:z.string(),bbox,manualRevision:z.number().int()}).parse(body);revision(record,p);
    if(!s.frames.some(f=>f.id===p.frameId))throw new ApiError(400,'유효한 원본 프레임이 아닙니다.');
    const hid=`hazard-${crypto.randomUUID()}`;m.hazards[hid]={id:hid,entityId:`entity-${crypto.randomUUID()}`,title:p.title,observation:p.observation,hypothesis:'사용자가 추가한 점검 항목입니다. 현장 확인이 필요합니다.',priority:'medium',reason:'사용자 지정 점검',check:'영상 근거와 실제 상태를 확인하세요.',evidence:[{id:`evidence-${crypto.randomUUID()}`,frameId:p.frameId,bbox:p.bbox,observation:p.observation}],review:'unreviewed',origin:'manual'};m.revision++;await save(env,record);return json({scene:snapshot(record),hazardId:hid},201);
  }else if(action==='hazards'&&parts[4]==='review'&&method==='PATCH'){
    const p=z.object({status:z.enum(['unreviewed','confirmed','needs_info','dismissed']),manualRevision:z.number().int()}).parse(body);revision(record,p);const h=s.hazards.find(h=>h.id===parts[3]);if(!h)throw new ApiError(404,'대상을 찾을 수 없습니다.');
    m.reviews[h.id]={status:p.status,at:new Date().toISOString()};m.hazards[h.id]=h;m.revision++;
  }else if(action==='corrections'&&method==='POST'){
    const p=z.object({center:vector,halfExtents:vector,manualRevision:z.number().int()}).parse(body);revision(record,p);
    if(p.halfExtents.some(x=>x<=0||x>2)||p.center.some((x,i)=>x<s.bounds.min[i]-1||x>s.bounds.max[i]+1))throw new ApiError(400,'작은 현장 내부 구역만 보정할 수 있습니다.');
    m.corrections.push({id:`correction-${crypto.randomUUID()}`,center:p.center,halfExtents:p.halfExtents,revision:1,origin:'exploration_correction'});m.navigationRevision++;m.revision++;
  }else if(action==='corrections'&&method==='DELETE'){
    const p=z.object({manualRevision:z.number().int()}).parse(body);revision(record,p);m.corrections=m.corrections.filter(c=>c.id!==parts[3]);m.navigationRevision++;m.revision++;
  }else if(action==='navigation-checks'&&method==='POST'){
    const segment=z.object({from:vector,to:vector,valid:z.boolean(),sourceSupport:z.enum(['supported','partial','unknown']),correctionIds:z.array(z.string()).max(20)});
    const p=z.object({points:z.array(vector).max(500),segments:z.array(segment).max(500),correctionIds:z.array(z.string()).max(50),valid:z.boolean(),reason:z.string().max(300),assetRevision:z.string(),navigationRevision:z.number().int()}).parse(body);
    if(p.assetRevision!==s.assetRevision||p.navigationRevision!==s.navigationRevision)throw new ApiError(409,'충돌 공간이 변경됐습니다. 경로를 다시 확인해 주세요.');
    const allowed=new Set([...s.corrections.map(c=>c.id),...(s.enhancements||[]).map(e=>e.id),...fittedScene(s.assetRevision).map(e=>e.id)]);
    if(p.correctionIds.some(id=>!allowed.has(id))||p.segments.some(x=>x.correctionIds.some(id=>!allowed.has(id)))||(p.valid&&(!p.segments.length||p.segments.some(x=>!x.valid||x.sourceSupport==='unknown'))))throw new ApiError(400,'경로의 지지 근거를 확인할 수 없습니다.');
    const route={...p,id:`route-${crypto.randomUUID()}`,checkedAt:new Date().toISOString(),stale:false,validation:'browser_rapier' as const};record.scene.navigationChecks=[...(record.scene.navigationChecks||[]),route].slice(-30);await save(env,record);return json(route);
  }else throw new ApiError(404,'요청을 찾을 수 없습니다.');
  await save(env,record);return json(snapshot(record));
 }catch(e){const error=e as Error;return json({error:error instanceof z.ZodError?'입력 형식을 확인해 주세요.':String(error.message).replaceAll(env.OPENAI_API_KEY||'__NO_KEY__','[redacted]').replaceAll(env.ZIPBUL_UPLOAD_TOKEN||'__NO_UPLOAD__','[redacted]')},error instanceof ApiError?error.status:error instanceof z.ZodError?400:500);}
}
