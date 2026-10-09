import fs from 'node:fs';
import assert from 'node:assert/strict';
import {chromium} from 'playwright';

process.stdin.setRawMode?.(true);process.stdin.resume();process.stdout.write('Ready for hidden verification credentials on stdin.\n');
const config=await new Promise((resolve,reject)=>{let text='';process.stdin.on('data',chunk=>{text+=chunk.toString();if(/[\r\n]/.test(text)){process.stdin.setRawMode?.(false);process.stdin.pause();try{resolve(JSON.parse(text.trim()));}catch{reject(new Error('Invalid verification configuration'));}}});});
const {url,bypass}=config,origin=new URL(url).origin,manifest=JSON.parse(fs.readFileSync('output/sites-transfer.json','utf8')),id=manifest.record.scene.id;
const headers={'OAI-Sites-Authorization':`Bearer ${bypass}`};const results={},errors=[];
async function api(path,method='GET',body){const r=await fetch(new URL(path,origin),{method,headers:{...headers,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined,redirect:'error'});const value=await r.json();if(!r.ok)throw new Error(`API ${r.status}: ${JSON.stringify(value)}`);return value;}
results.health=await api('/api/health');assert.equal(results.health.keyConfigured,true);
results.anonymousStatus=(await fetch(origin,{redirect:'manual'})).status;assert.notEqual(results.anonymousStatus,200);
const scene=await api(`/api/scenes/${id}`);assert.equal(scene.frames.length,19);assert.ok(scene.hazards.length>=4);
for(const asset of manifest.assets){const name=asset.key.split('/')[1];const r=await fetch(new URL(`/api/scenes/${id}/assets/${name}`,origin),{method:'HEAD',headers,redirect:'error'});assert.equal(r.status,200);assert.equal(Number(r.headers.get('content-length')),asset.size);}
results.assetsChecked=manifest.assets.length;
const range=await fetch(new URL(scene.videoUrl,origin),{headers:{...headers,Range:'bytes=0-99'},redirect:'error'});assert.equal(range.status,206);assert.equal((await range.arrayBuffer()).byteLength,100);results.videoRange=true;
let browser;
try{
 browser=await chromium.launch({headless:false,args:['--use-angle=metal']});const page=await browser.newPage({viewport:{width:1440,height:960}});
 await page.route(`${origin}/**`,route=>route.continue({headers:{...route.request().headers(),...headers}}));
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto(origin,{waitUntil:'domcontentloaded',timeout:60000});
 await page.waitForFunction(()=>window.zipbulScene?.getInfo().ready,null,{timeout:180000});
 results.sceneReady=await page.evaluate(()=>window.zipbulScene.getInfo());console.log('Hosted 3D scene loaded.');
 await page.locator('.hazard-card').first().click();await page.screenshot({path:'output/sites-analysis.png'});
 await page.getByRole('button',{name:'원본 영상 재생',exact:true}).click();
 await page.waitForFunction(()=>{const v=document.querySelector('video');return v&&v.readyState>=2;},null,{timeout:60000});
 results.video=await page.evaluate(()=>({duration:document.querySelector('video').duration,readyState:document.querySelector('video').readyState}));
 await page.getByRole('button',{name:'전체 관계도',exact:true}).click();await page.waitForTimeout(1200);results.graphNodes=await page.locator('.spatial-node,.react-flow__node').count();assert.ok(results.graphNodes>=16);await page.screenshot({path:'output/sites-graph.png'});
 await page.getByRole('button',{name:'탐사로 돌아가기',exact:true}).click();
 await page.locator('#walk-mode').click();const begin=page.getByRole('button',{name:/탐사 시작|탐사 계속/,exact:true});await begin.click();await page.waitForTimeout(1000);
 const before=await page.evaluate(()=>window.zipbulScene.getInfo());await page.keyboard.down('KeyW');await page.waitForTimeout(500);await page.keyboard.up('KeyW');const after=await page.evaluate(()=>window.zipbulScene.getInfo());
 results.movement={distance:Math.hypot(...after.player.map((x,i)=>x-before.player[i])),grounded:after.grounded};assert.ok(results.movement.distance>.02);await page.keyboard.press('Escape');await page.screenshot({path:'output/sites-walk.png'});
 assert.deepEqual(errors,[]);results.browserErrors=errors;console.log('Hosted walkthrough, video and graph verified.');
}finally{await browser?.close();}
const h=scene.hazards[0],reviewPath=`/api/scenes/${id}/hazards/${h.id}/review`;let originalReview=h.review;
try{let s=await api(`/api/scenes/${id}`);await api(reviewPath,'PATCH',{status:originalReview==='confirmed'?'needs_info':'confirmed',manualRevision:s.manualRevision});s=await api(`/api/scenes/${id}`);assert.notEqual(s.hazards.find(x=>x.id===h.id).review,originalReview);results.reviewPersisted=true;}finally{const s=await api(`/api/scenes/${id}`);await api(reviewPath,'PATCH',{status:originalReview,manualRevision:s.manualRevision});}
const chat=await api(`/api/scenes/${id}/chat`,'POST',{question:'이 점검 항목에서 영상으로 관찰된 사실과 아직 확인이 필요한 가설을 두 문장으로 구분해 줘.',hazardId:h.id});assert.ok(chat.answer.length>10);results.chat={model:chat.model,answerLength:chat.answer.length};console.log('Hosted Astra chat returned an answer.');
const run=await api(`/api/scenes/${id}/analyses`,'POST',{frameIds:[scene.frames[0].id]});let completed;
for(let i=0;i<90;i++){const s=await api(`/api/scenes/${id}`);completed=s.runs.find(r=>r.id===run.id);if(!['queued','running'].includes(completed.status))break;if(i%6===0)console.log(`Astra analysis: ${completed.status} / ${completed.phase}`);await new Promise(r=>setTimeout(r,2000));}
assert.equal(completed.status,'completed',JSON.stringify(completed));results.analysis={id:completed.id,status:completed.status,frames:completed.completedFrameIds.length,resultCount:completed.resultCount,model:completed.model};
fs.writeFileSync('output/sites-verification.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
