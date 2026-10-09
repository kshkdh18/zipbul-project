import {test} from 'node:test';
import assert from 'node:assert/strict';
import {projectDepth,validBox,classification,canFocus} from '../lib/contracts';
test('sensor optical depth converts top-left image coordinates to ARKit camera -Z and row-array world transform',()=>{
  const k=[[100,0,50],[0,100,50],[0,0,1]],camera=[[1,0,0,3],[0,1,0,2],[0,0,1,-1],[0,0,0,1]];
  assert.deepEqual(projectDepth([50,50],2,k,camera),[3,2,-3]);
  assert.deepEqual(projectDepth([100,0],2,k,camera),[4,3,-3]);
});
test('evidence boxes must fit within original frame',()=>{assert(validBox([.2,.3,.4,.4]));assert(!validBox([.8,.5,.4,.2]));assert(!validBox([0,0,0,.2]));});
test('corrected routes remain simulation, including when any segment is unverified',()=>{assert.deepEqual(classification([{valid:true,correctionIds:[],sourceSupport:'supported'},{valid:false,correctionIds:['floor-patch'],sourceSupport:'partial'}]),{valid:false,kind:'simulation'});});
test('unplaced, proposed, stale or changed-asset anchors never auto focus',()=>{assert(!canFocus(undefined,'r1'));for(const status of ['proposed','stale'])assert(!canFocus({status,assetRevision:'r1'},'r1'));assert(!canFocus({status:'verified',assetRevision:'r0'},'r1'));assert(canFocus({status:'verified',assetRevision:'r1'},'r1'));});
