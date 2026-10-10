import assert from 'node:assert/strict';
import fs from 'node:fs';
import {chromium} from 'playwright';
const base=process.env.ZIPBUL_TEST_URL||'http://127.0.0.1:3000';
const site1='scene-105bfbad-4a6f-4174-98ea-c10341cda210',site2='scene-33a46c91-0ba7-44f8-99dc-bfe3588c539a';
const read=id=>JSON.parse(fs.readFileSync(`data/scenes/${id}/manual.json`,'utf8'));
const before=[read(site1),read(site2)],errors=[],writes=[],assets=[];
const browser=await chromium.launch({headless:false,args:['--use-angle=metal']});
fs.mkdirSync('output/improvements',{recursive:true});
try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.url().includes('/api/')&&!['GET','HEAD'].includes(r.method()))writes.push(r.url());});
 page.on('response',r=>{if(r.url().includes('/assets/meshOptimized'))assets.push({url:r.url(),status:r.status()});});
 await page.goto(`${base}/?scene=${site1}`);
 await page.waitForFunction(()=>window.zipbulScene?.getInfo().ready,null,{timeout:120000});
 const dialog=page.getByRole('dialog',{name:'Getting started guide'});
 await dialog.waitFor();assert.equal(await page.locator('html').getAttribute('lang'),'en');
 await page.screenshot({path:'output/improvements/guide-english.png'});
 for(let i=0;i<9;i++){
  await dialog.getByRole('heading').waitFor();
  await page.waitForTimeout(250);
  assert.equal(await page.locator('.tour-missing').count(),0,`Missing highlight at step ${i+1}`);
  const card=await dialog.boundingBox();assert.ok(card&&card.x>=0&&card.y>=0&&card.x+card.width<=1441&&card.y+card.height<=961,`Offscreen card ${i+1}`);
  await dialog.getByRole('checkbox').check();
  assert.ok((await dialog.locator('footer').innerText()).includes(`${i+1}/9`));
  if(i===7){assert.ok((await page.locator('.network-node').count())>10);await page.screenshot({path:'output/improvements/guide-graph.png'});}
  if(i===8)await dialog.getByRole('button',{name:'Finish',exact:true}).click();
  else await dialog.getByRole('button',{name:'Next',exact:true}).click();
 }
 assert.deepEqual(writes,[],'Tutorial must not start AI calls or edit inspection data');
 assert.equal((await page.evaluate(()=>JSON.parse(localStorage.getItem('zipbul-guide-v1')))).checked.length,9);
 await page.getByRole('button',{name:'Open getting started guide'}).click();
 await dialog.getByRole('button',{name:'Close guide'}).click();
 await page.getByRole('combobox',{name:'Language / 언어'}).selectOption('ko');
 assert.ok((await page.locator('.projectbar').innerText()).includes('센터필드'));
 await page.reload();await page.waitForFunction(()=>window.zipbulScene?.getInfo().ready,null,{timeout:120000});
 assert.equal(await page.locator('html').getAttribute('lang'),'ko');assert.equal(await page.locator('.tour-card').count(),0);
 await page.getByRole('button',{name:'사용 가이드 열기'}).click();
 await page.waitForFunction(()=>document.querySelector('.tour-card footer')?.textContent.includes('9/9')); 
 await page.screenshot({path:'output/improvements/guide-korean.png'});
 await page.getByRole('button',{name:'가이드 닫기'}).click();
 await page.getByRole('combobox',{name:'Language / 언어'}).selectOption('en');
 await page.getByRole('combobox',{name:'Select site',exact:true}).selectOption(site2);
 await page.waitForFunction(()=>window.zipbulScene?.getInfo().ready&&window.zipbulScene.getInfo().meshTriangles===3572593,null,{timeout:120000});
 await page.locator('.hazard-card').nth(9).click();
 await page.waitForFunction(()=>!JSON.parse(window.render_game_to_text()).focusMoving);
 await page.screenshot({path:'output/improvements/site2-english.png'});
 const text=await page.locator('body').innerText();
 const korean=text.split('\n').filter(s=>/[가-힣]/.test(s)&&s.trim()!=='한국어');
 assert.deepEqual(korean,[],`Untranslated current demo text: ${korean}`);
 await page.getByRole('button',{name:'Show reconstruction',exact:true}).click();await page.waitForTimeout(1300);
 await page.screenshot({path:'output/improvements/site2-reconstructed.png'});
 await page.getByRole('button',{name:'Show original',exact:true}).click();
 assert.deepEqual([read(site1),read(site2)],before);
 assert.deepEqual(errors,[]);assert.ok(assets.some(a=>a.url.includes(site1)&&a.status===200));assert.ok(assets.some(a=>a.url.includes(site2)&&a.status===200));
 const result={defaultEnglish:true,koreanPreferencePersists:true,allNineHighlights:true,checksPersist:true,tourWrites:writes.length,manualRecordsUnchanged:true,bothOptimizedModelsLoaded:true,originalReconstructionToggle:true,errors};
 fs.writeFileSync('output/improvements/guide-results.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));
}finally{await browser.close();}
