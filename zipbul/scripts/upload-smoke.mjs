import './create-test-fixtures.mjs';
import {chromium} from 'playwright';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:false,args:['--use-angle=metal']});let sceneId,jobId;
try{const p=await browser.newPage({viewport:{width:1440,height:960}});const errors=[];p.on('pageerror',e=>errors.push(e.message));p.on('response',async r=>{if(/\/api\/uploads\/import-[\w-]+\/complete$/.test(r.url()))jobId=(await r.json()).id;});
 await p.goto('http://127.0.0.1:3000');await p.getByRole('button',{name:'현장 추가',exact:true}).click();
 const files=p.locator('.import-modal input[type=file]');await files.nth(0).setInputFiles('output/upload-fixture/room.glb');await files.nth(1).setInputFiles('output/upload-fixture/video.mp4');
 await p.getByRole('button',{name:'가져오기',exact:true}).click();await p.locator('.import-modal').waitFor({state:'hidden',timeout:60000});
 await p.waitForFunction(()=>window.zipbulScene?.getInfo().ready&&window.zipbulScene.getInfo().meshTriangles===2,null,{timeout:60000});
 const job=await(await fetch(`http://127.0.0.1:3001/api/imports/${jobId}`)).json();sceneId=job.sceneId;
 const scene=await(await fetch(`http://127.0.0.1:3001/api/scenes/${sceneId}`)).json();assert.equal(scene.frames[0].camera.length,0);assert.equal(scene.hazards.length,0);assert.equal(scene.sourceInfo.triangles,2);
 await p.locator('.sidebar-head button').click();const box=await p.locator('.frame-image').boundingBox();await p.mouse.move(box.x+30,box.y+30);await p.mouse.down();await p.mouse.move(box.x+120,box.y+120,{steps:4});await p.mouse.up();
 await p.getByPlaceholder('예: 통로의 케이블').fill('입력 흐름 검증');await p.getByPlaceholder('영상에 보이는 사실을 적어주세요.').fill('합성 회색 프레임의 수동 점검 테스트');await p.getByRole('button',{name:'점검 저장',exact:true}).click();
 await p.waitForFunction(()=>document.querySelector('.location-state')?.textContent.includes('공간 위치 미확인'));
 assert.equal(await p.getByRole('button',{name:'대상 보기',exact:true}).isDisabled(),true);await p.locator('.scene-loading').waitFor({state:'hidden'});await p.waitForTimeout(1000);assert.equal(await p.locator('.scene-loading').count(),0);await p.screenshot({path:'output/upload-smoke.png'});
 assert.deepEqual(errors,[]);console.log(JSON.stringify({browserUpload:true,metadataAbsentManualFlow:true,errors}));
}finally{await browser.close();if(sceneId)fs.rmSync(`data/scenes/${sceneId}`,{recursive:true,force:true});if(jobId)fs.rmSync(`data/imports/${jobId}`,{recursive:true,force:true});}
