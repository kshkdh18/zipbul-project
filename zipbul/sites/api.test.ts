import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {handleApi,type SiteEnv} from './api';
import {advance} from './analysis';

function fixture(){
  const sql=new DatabaseSync(':memory:');sql.exec('CREATE TABLE scenes(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,data TEXT,version INTEGER DEFAULT 0)');
  const seed=JSON.parse(fs.readFileSync('output/sites-transfer.json','utf8')).record;seed.manual={revision:0,hazards:{},reviews:{},navigationRevision:1,corrections:[]};seed.scene.runs=[];
  sql.prepare('INSERT INTO scenes VALUES(?,?,?,?,0)').run(seed.scene.id,seed.scene.title,seed.createdAt,JSON.stringify(seed));
  const objects=new Map<string,Uint8Array>([[`${seed.scene.id}/video`,new Uint8Array([1,2,3,4,5])],...seed.scene.frames.map((f:any)=>[`${seed.scene.id}/${f.id}`,new Uint8Array([255,216,255,217])])]);
  const env={DB:{prepare(statement:string){let values:unknown[]=[];const prepared={bind(...v:unknown[]){values=v;return prepared;},async first(){return sql.prepare(statement).get(...values as any[])||null;},async all(){return {results:sql.prepare(statement).all(...values as any[])};},async run(){return {meta:{changes:Number(sql.prepare(statement).run(...values as any[]).changes)}};}};return prepared;}},BUCKET:{async head(key:string){const bytes=objects.get(key);return bytes?{size:bytes.length,httpEtag:'"test"',httpMetadata:{contentType:'video/mp4'}}:null;},async get(key:string,options:any){const bytes=objects.get(key);if(!bytes)return null;const range=options?.range,b=range?bytes.slice(range.offset,range.offset+range.length):bytes;return {body:new Response(b).body,arrayBuffer:async()=>b.buffer};}},OPENAI_API_KEY:'test-key-never-sent'} as unknown as SiteEnv;
  const request=(path='',method='GET',data?:unknown,headers?:Record<string,string>)=>handleApi(new Request(`https://zipbul.test/api/scenes/${seed.scene.id}${path}`,{method,headers:{...(data?{'Content-Type':'application/json'}:{}),...headers},body:data?JSON.stringify(data):undefined}),env);
  return {sql,env,seed,request};
}
test('cloud review rejects stale writes, persists manual mapping, and invalidates paths',async()=>{
  const {sql,seed,request}=fixture();try{
    const h=seed.scene.hazards[0],position=seed.scene.bounds.min.map((x:number,i:number)=>(x+seed.scene.bounds.max[i])/2);
    const map={manualRevision:0,assetRevision:seed.scene.assetRevision,hazardId:h.id,position,cameraPosition:position,cameraTarget:position,surface:{mesh:'world/primitive-0',face:0,normal:[0,1,0]}};
    assert.equal((await request('/mappings','POST',{...map,surface:{...map.surface,face:999999999}})).status,400);
    assert.equal((await request('/mappings','POST',map)).status,200);
    assert.equal((await request(`/hazards/${h.id}/review`,'PATCH',{status:'confirmed',manualRevision:0})).status,409);
    const updated=await (await request(`/hazards/${h.id}/review`,'PATCH',{status:'confirmed',manualRevision:1})).json() as any;
    assert.equal(updated.hazards[0].anchor.status,'verified');assert.equal(updated.hazards[0].review,'confirmed');assert.equal(updated.manualRevision,2);
    assert.equal((await request('/corrections','POST',{center:position,halfExtents:[.5,.04,.5],manualRevision:2})).status,200);
    const after=await (await request()).json() as any;assert.equal(after.navigationRevision,updated.navigationRevision+1);
    assert.equal((await request('/navigation-checks','POST',{points:[],segments:[],correctionIds:[],valid:false,reason:'test',assetRevision:seed.scene.assetRevision,navigationRevision:updated.navigationRevision})).status,409);
    assert.equal((await request('/corrections','POST',{}, {Origin:'https://evil.example'})).status,403);
  }finally{sql.close();}
});
test('video assets honor byte ranges and reject invalid ranges',async()=>{const {sql,request}=fixture();try{
  const r=await request('/assets/video','GET',undefined,{Range:'bytes=1-3'});assert.equal(r.status,206);assert.equal(r.headers.get('content-range'),'bytes 1-3/5');assert.deepEqual([...new Uint8Array(await r.arrayBuffer())],[2,3,4]);
  assert.equal((await request('/assets/video','GET',undefined,{Range:'bytes=50-60'})).status,416);
  const suffix=await request('/assets/video','GET',undefined,{Range:'bytes=-2'});assert.deepEqual([...new Uint8Array(await suffix.arrayBuffer())],[4,5]);
}finally{sql.close();}});
test('background analysis persists its response, merges results and preserves a concurrent review',async()=>{
  const {sql,env,seed,request}=fixture(),original=globalThis.fetch;let creates=0,retrieves=0;const h=seed.scene.hazards[0],frameId=seed.scene.frames[0].id;
  globalThis.fetch=async(_url:any,init:any)=>{assert.equal(init.headers.Authorization,'Bearer test-key-never-sent');if(init.method==='POST'){creates++;const body=JSON.parse(init.body);assert.equal(body.model,'gpt-6-astra');assert.equal(body.background,true);return Response.json({id:'resp-test',status:'queued'});}retrieves++;return Response.json({status:'completed',usage:{input_tokens:20,output_tokens:30},output:[{type:'message',content:[{type:'output_text',text:JSON.stringify({summary:'test',hazards:[{existingId:h.id,title:h.title,observation:'재분석 관찰',hypothesis:'추가 확인 필요',priority:'medium',reason:'표본',check:'확인',evidence:[{frameId,bbox:[0,0,.2,.2],observation:'표본 근거'}]}]})}]}]});};
  try{
    assert.equal((await request('/analyses','POST',{frameIds:[frameId]})).status,202);await advance(env,seed.scene.id);
    assert.equal(creates,1);let scene=await (await request()).json() as any;assert.deepEqual(scene.runs[0].providerIds,['resp-test']);
    await request(`/hazards/${h.id}/review`,'PATCH',{status:'confirmed',manualRevision:0});await advance(env,seed.scene.id);
    scene=await (await request()).json() as any;assert.equal(scene.runs[0].status,'completed');assert.equal(scene.hazards.find((x:any)=>x.id===h.id).review,'confirmed');assert.equal(scene.hazards.find((x:any)=>x.id===h.id).observation,'재분석 관찰');assert.equal(creates,1);assert.equal(retrieves,1);
  }finally{globalThis.fetch=original;sql.close();}
});
