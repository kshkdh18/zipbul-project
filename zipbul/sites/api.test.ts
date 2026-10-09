import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {handleApi,type SiteEnv,type StoredScene} from './api';
import {advance} from './analysis';

function fixture(){
  const sql=new DatabaseSync(':memory:');sql.exec('CREATE TABLE scenes(id TEXT PRIMARY KEY,title TEXT,created_at TEXT,data TEXT,version INTEGER DEFAULT 0)');
  const id='scene-api-test',asset=(name:string)=>`/api/scenes/${id}/assets/${name}`;
  const seed:StoredScene={
    createdAt:'2026-10-09T00:00:00Z',surfaces:[2],
    manual:{revision:0,hazards:{},reviews:{},navigationRevision:1,corrections:[]},
    scene:{
      id,title:'합성 API 검증 현장',sessionId:'api-test',assetRevision:'test-revision',duration:2,
      videoUrl:asset('video'),meshUrl:asset('mesh'),originalMeshUrl:asset('original'),collisionUrl:asset('collision'),
      frames:[{id:'frame-0',timestamp:0,url:asset('frame-0'),width:640,height:480,camera:[],intrinsics:[],sourceFrameId:0}],
      cameraPath:[],bounds:{min:[-3,0,-3],max:[3,3,3]},spawn:{position:[0,1.65,0],target:[0,1.65,-1]},
      sourceInfo:{vertices:4,triangles:2,textures:0,droppedFrames:0,alignment:'합성 시험'},
      hazards:[{id:'hazard-test',entityId:'entity-test',title:'점검 후보',observation:'영상의 표본',hypothesis:'현장 확인 필요',priority:'medium',reason:'표본 근거',check:'직접 확인',review:'unreviewed',origin:'astra',evidence:[{id:'evidence-test',frameId:'frame-0',bbox:[0,0,.2,.2],observation:'표본 근거'}]}],
      runs:[],manualRevision:0,navigationRevision:1,corrections:[],
    },
  };
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
test('analysis history retains the saved observation after later scene changes',async()=>{
  const {sql,seed,request}=fixture();try{
    const row=sql.prepare('SELECT data FROM scenes WHERE id=?').get(seed.scene.id) as {data:string};const record=JSON.parse(row.data);
    const run={id:'run-history',status:'completed',frameIds:[],completedFrameIds:[],providerIds:[],startedAt:'2026-10-09',phase:'완료',model:'gpt-6-astra',resultCount:1};
    record.scene.runs=[run];record.history={[run.id]:{run,hazards:[{...seed.scene.hazards[0],observation:'당시 관찰'}],savedAt:'2026-10-09'}};
    record.scene.hazards[0].observation='이후 관찰';sql.prepare('UPDATE scenes SET data=? WHERE id=?').run(JSON.stringify(record),seed.scene.id);
    const response=await request('/analyses/run-history');assert.equal(response.status,200);assert.equal((await response.json() as any).hazards[0].observation,'당시 관찰');
    assert.equal((await request('/analyses/missing')).status,404);
  }finally{sql.close();}
});
test('sync preserves cloud reviews and history and rejects a changed GLB',async()=>{
  const {sql,env,seed,request}=fixture();try{
    env.ZIPBUL_SYNC_TOKEN='sync-test';env.BUCKET.head=async()=>({size:1} as any);
    await request(`/hazards/${seed.scene.hazards[0].id}/review`,'PATCH',{status:'confirmed',manualRevision:0});
    const input=structuredClone(seed);input.scene.title='갱신한 현장';input.scene.hazards[0].observation='새 관찰';
    const sync=(record:any,token='sync-test')=>handleApi(new Request('https://zipbul.test/api/transfer/sync',{method:'POST',headers:{'X-Zipbul-Upload':token,'Content-Type':'application/json'},body:JSON.stringify(record)}),env);
    assert.equal((await sync(input,'bad')).status,403);assert.equal((await sync(input)).status,200);
    const scene=await (await request()).json() as any;assert.equal(scene.title,'갱신한 현장');assert.equal(scene.hazards[0].review,'confirmed');assert.equal(scene.hazards[0].observation,'새 관찰');
    input.scene.assetRevision='changed';assert.equal((await sync(input)).status,409);
  }finally{sql.close();}
});
test('cloud import copies bounded source assets into R2 and then serves independently',async()=>{
  const {sql,env,seed}=fixture(),original=globalThis.fetch;const objects=new Map<string,Uint8Array>(),multiparts=new Map<string,Map<number,Uint8Array>>();let workerCalls=0;
  env.ZIPBUL_IMPORT_ORIGIN='https://processor.test';
  const encode=(value:string)=>new TextEncoder().encode(value);
  const gltf=encode(JSON.stringify({nodes:[{mesh:0}],meshes:[{primitives:[{attributes:{POSITION:0}}]}],accessors:[{count:3}],scenes:[{nodes:[0]}]}));const glb=new Uint8Array(20+gltf.length);const view=new DataView(glb.buffer);view.setUint32(0,0x46546c67,true);view.setUint32(12,gltf.length,true);glb.set(gltf,20);
  const data=structuredClone(seed.scene);data.id='scene-import-test';data.frames=data.frames.slice(0,1);data.hazards=[];data.runs=[];
  const body=(b:Uint8Array)=>({body:new Response(b).body,arrayBuffer:async()=>b.buffer,json:async()=>JSON.parse(new TextDecoder().decode(b))});
  env.BUCKET={async put(k:string,b:string){objects.set(k,encode(b));},async get(k:string){const b=objects.get(k);return b?body(b):null;},async head(k:string){const b=objects.get(k);return b?{size:b.length}:null;},async createMultipartUpload(k:string){multiparts.set(k,new Map());return {uploadId:k};},resumeMultipartUpload(k:string){return {async uploadPart(n:number,b:ArrayBuffer){assert.ok(b.byteLength<=8*1024*1024);multiparts.get(k)!.set(n,new Uint8Array(b));return {partNumber:n,etag:String(n)};},async complete(){const b=multiparts.get(k)!.get(1)!;objects.set(k,b);return {size:b.length};}};}} as any;
  globalThis.fetch=async(url:any,init:any)=>{workerCalls++;const u=new URL(url);assert.equal(u.origin,'https://processor.test');assert.equal(init.headers.Origin,u.origin);
    if(u.pathname==='/api/uploads')return Response.json({id:'import-test',chunkSize:4194304});
    if(u.pathname.endsWith('/complete'))return Response.json({status:'queued',phase:'준비'});
    if(u.pathname==='/api/imports/import-test')return Response.json({status:'completed',sceneId:data.id});
    if(u.pathname.endsWith('/export'))return Response.json(data);
    const bytes=u.pathname.endsWith('/mesh')?glb:new Uint8Array([1,2,3]);
    if(init.method==='HEAD')return new Response(null,{headers:{'content-length':String(bytes.length)}});
    const match=/bytes=(\d+)-(\d+)/.exec(init.headers.Range)!;const start=Number(match[1]),end=Number(match[2]);return new Response(bytes.slice(start,end+1),{status:206,headers:{'content-range':`bytes ${start}-${end}/${bytes.length}`}});
  };
  const req=(path:string,method='GET')=>handleApi(new Request('https://zipbul.test/api/'+path,{method,body:method==='POST'?'{}':undefined}),env);
  try{assert.equal((await req('uploads','POST')).status,201);assert.equal((await req('uploads/import-test/complete','POST')).status,202);let result:any;
    for(let i=0;i<10;i++){const r=await req('imports/import-test');assert.equal(r.status,200,await r.clone().text());result=await r.json();if(result.status==='completed')break;}
    assert.equal(result.status,'completed');const before=workerCalls;assert.equal((await req('scenes/'+data.id)).status,200);assert.equal(workerCalls,before);assert.equal(objects.has(data.id+'/video'),true);
  }finally{globalThis.fetch=original;sql.close();}
});
