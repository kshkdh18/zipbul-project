import {test,after} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import type {Hazard,LocalScene,Run} from '../lib/types';
const temp=fs.mkdtempSync(path.join(os.tmpdir(),'zipbul-test-'));process.env.ZIPBUL_DATA_DIR=temp;
const db=await import('../server/store');after(()=>fs.rmSync(temp,{recursive:true,force:true}));
test('human mapping and review survive new analysis publication; source replacement makes it stale',()=>{
  const id='scene-test';const scene={id,assetRevision:'r1',files:{},sourceDirectory:'unused',createdAt:'test',hazards:[],runs:[],corrections:[]} as unknown as LocalScene;
  db.write(path.join(db.sceneDir(id),'scene.json'),scene);
  const h:Hazard={id:'hazard-1',entityId:'entity-1',title:'Cable',observation:'Visible',hypothesis:'Check',priority:'medium',reason:'In path',check:'Review',evidence:[{id:'evidence-1',frameId:'frame-1',bbox:[.1,.1,.2,.2],observation:'Visible'}],review:'unreviewed',origin:'astra'};
  const m=db.manual(id);m.hazards[h.id]={...h,anchor:{position:[1,0,1],cameraPosition:[0,1,0],cameraTarget:[1,0,1],status:'verified',method:'manual',assetRevision:'r1'}};m.reviews[h.id]={status:'confirmed',at:'test'};m.revision=1;db.saveManual(id,m);
  db.write(path.join(db.sceneDir(id),'runs.json'),[{id:'run-1',status:'running'} as Run]);
  db.publish(id,'run-1',[{...h,title:'Updated analysis',anchor:undefined}]);const s=db.snapshot(id);
  assert.equal(s.hazards[0].title,'Updated analysis');assert.equal(s.hazards[0].anchor?.method,'manual');assert.equal(s.hazards[0].review,'confirmed');assert.equal(s.manualRevision,1);
  db.write(path.join(db.sceneDir(id),'scene.json'),{...scene,assetRevision:'r2'});assert.equal(db.snapshot(id).hazards[0].anchor?.status,'stale');assert.equal(db.manual(id).hazards[h.id].anchor?.assetRevision,'r1');
});
test('late provider results after cancellation are not published',()=>{
  const id='scene-test';db.updateRun(id,'run-1',r=>r.status='canceled');const before=db.snapshot(id).hazards.length;
  db.publish(id,'run-1',[{id:'hazard-late'} as Hazard]);assert.equal(db.snapshot(id).hazards.length,before);
});
