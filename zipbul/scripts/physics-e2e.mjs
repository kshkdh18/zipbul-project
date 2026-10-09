import './create-test-fixtures.mjs';
import {Document,NodeIO} from '@gltf-transform/core';
import {chromium} from 'playwright';
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {importSession} from './import-session.ts';
const dir='output/physics-fixture',id='scene-physics-e2e';fs.mkdirSync(dir,{recursive:true});
const d=new Document(),buffer=d.createBuffer(),scene=d.createScene(),mat=d.createMaterial().setBaseColorFactor([.5,.5,.5,1]).setDoubleSided(true);
for(const vertices of [[-3,0,-3,3,0,-3,3,0,3,-3,0,3],[-3,0,-1,3,0,-1,3,3,-1,-3,3,-1]]){
const p=d.createAccessor().setType('VEC3').setArray(new Float32Array(vertices)).setBuffer(buffer),i=d.createAccessor().setType('SCALAR').setArray(new Uint16Array([0,2,1,0,3,2])).setBuffer(buffer);
scene.addChild(d.createNode().setMesh(d.createMesh().addPrimitive(d.createPrimitive().setAttribute('POSITION',p).setIndices(i).setMaterial(mat))));}
await new NodeIO().write(`${dir}/room.glb`,d);fs.copyFileSync('output/upload-fixture/video.mp4',`${dir}/video.mp4`);
fs.writeFileSync(`${dir}/manifest.json`,JSON.stringify({session_id:'physics-e2e'}));fs.writeFileSync(`${dir}/frames.jsonl`,JSON.stringify({frame_id:1,video_status:'written',video_pts:0,image_width:640,image_height:480,camera_transform:[],intrinsics:[]}));
await importSession(dir,`${dir}/room.glb`,id);
const file=`data/scenes/${id}/scene.json`,source=JSON.parse(fs.readFileSync(file,'utf8'));source.createdAt='2000';fs.writeFileSync(file,JSON.stringify(source));
let b;const results={};const api=async(url,data,method='POST')=>{const r=await fetch(`http://127.0.0.1:3001/api/scenes/${id}${url}`,{method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});assert.ok(r.ok,await r.clone().text());return r.json();};
try{b=await chromium.launch({headless:false,args:['--use-angle=metal']});const p=await b.newPage();await p.goto(`http://127.0.0.1:3000/?scene=${id}`);await p.waitForFunction(()=>window.zipbulScene?.getInfo().ready);
await p.locator('#walk-mode').click();await p.locator('#walk-start').click();await p.evaluate(()=>window.advanceTime(100));await p.keyboard.down('KeyW');await p.evaluate(()=>window.advanceTime(3000));await p.keyboard.up('KeyW');
let info=await p.evaluate(()=>window.zipbulScene.getInfo());assert.ok(info.player[2]>-.80&&info.player[2]<-.50,JSON.stringify(info.player));assert.ok(info.grounded);results.wallStopsCapsule=info.player;
await p.keyboard.press('Escape');await p.evaluate(()=>window.zipbulScene.reset());
const blocked=await p.evaluate(()=>window.zipbulScene.validatePath([0,1.5,-2]));assert.equal(blocked.valid,false);results.obstructedRouteRejected=true;
let state=await(await fetch(`http://127.0.0.1:3001/api/scenes/${id}`)).json();state=await api('/corrections',{center:[1,.07,0],halfExtents:[.65,.035,.65],manualRevision:state.manualRevision});
await p.waitForFunction(rev=>window.zipbulScene.getInfo().navigationRevision===rev,state.navigationRevision);
const valid=await p.evaluate(()=>window.zipbulScene.validatePath([1.6,1.5,0]));assert.equal(valid.valid,true,valid.reason);assert.ok(valid.correctionIds.length>0);assert.ok(valid.segments.some(s=>s.sourceSupport==='partial'));assert.ok(valid.segments.some(s=>s.sourceSupport==='supported'));await api('/navigation-checks',valid);results.correctedRouteHasSegmentProvenance=true;
await api(`/corrections/${state.corrections[0].id}`,{manualRevision:state.manualRevision},'DELETE');
state=await(await fetch(`http://127.0.0.1:3001/api/scenes/${id}`)).json();assert.equal(state.navigationChecks[0].stale,true);assert.equal(state.navigationChecks[0].valid,false);results.changedFloorInvalidatesAudit=true;
fs.writeFileSync('output/physics-results.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results,null,2));
}finally{await b?.close();fs.rmSync(`data/scenes/${id}`,{recursive:true,force:true});}
