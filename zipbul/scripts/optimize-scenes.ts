import fs from 'node:fs/promises';
import path from 'node:path';
import {optimizeDisplayGLB,DISPLAY_PROFILE} from '../server/optimize-glb';
import type {LocalScene} from '../lib/types';

const root=path.resolve('data/scenes');
const ids=process.argv.slice(2);const scenes=ids.length?ids:await fs.readdir(root);
const reports=[];
for(const id of scenes){
  if(!/^scene-[\w-]+$/.test(id))continue;
  const file=path.join(root,id,'scene.json'),s:LocalScene=JSON.parse(await fs.readFile(file,'utf8'));
  const output=path.join(root,id,'render-optimized.glb'),previousBytes=(await fs.stat(s.files.mesh)).size;
  console.log(`Optimizing ${id}…`);
  const report=await optimizeDisplayGLB(s.files.original,output);
  if(report.outputBytes>=previousBytes&&s.sourceInfo.displayOptimization?.profile!==DISPLAY_PROFILE)throw new Error('Optimized file is larger than the current display file; keeping the current asset.');
  // Keep a restorable metadata snapshot. Neither source revision nor collision asset changes.
  const backup=path.join(root,id,'before-display-optimization.json');
  await fs.writeFile(backup,JSON.stringify(s,null,2),{flag:'wx'}).catch((e:NodeJS.ErrnoException)=>{if(e.code!=='EEXIST')throw e;});
  s.files.meshOptimized=output;s.optimizedMeshUrl=`/api/scenes/${id}/assets/meshOptimized?v=${report.sha256.slice(0,12)}`;
  s.sourceInfo.displayOptimization={profile:DISPLAY_PROFILE,bytes:report.outputBytes,previousBytes,textureMaxSize:3072,geometryPreserved:true};
  const tmp=file+'.tmp';await fs.writeFile(tmp,JSON.stringify(s,null,2));await fs.rename(tmp,file);
  reports.push({id,previousBytes,...report});
  await fs.writeFile(path.join(root,id,'display-optimization.json'),JSON.stringify(reports.at(-1),null,2));
  console.log(JSON.stringify({id,previousMiB:previousBytes/1048576,currentMiB:report.outputBytes/1048576,reduction:1-report.outputBytes/previousBytes,triangles:report.triangles,geometryPreserved:true}));
}
await fs.mkdir('output/improvements',{recursive:true});await fs.writeFile('output/improvements/glb-optimization.json',JSON.stringify(reports,null,2));
