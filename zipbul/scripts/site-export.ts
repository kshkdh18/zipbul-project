import fs from 'node:fs';
import path from 'node:path';
import {local,list,manual,snapshot,runDetail} from '../server/store';
const id=process.argv[2]||list()[0]?.id;if(!id)throw new Error('준비된 현장이 없습니다.');
const source=local(id),scene=snapshot(id),m=manual(id);
scene.navigationRevision-=m.navigationRevision;
const fd=fs.openSync(source.files.mesh,'r');let gltf:any;
try{const head=Buffer.alloc(20);fs.readSync(fd,head,0,20,0);const data=Buffer.alloc(head.readUInt32LE(12));fs.readSync(fd,data,0,data.length,20);gltf=JSON.parse(data.toString());}finally{fs.closeSync(fd);}
const surfaces:number[]=[];function visit(i:number){const n=gltf.nodes[i];if(n.mesh!==undefined)for(const p of gltf.meshes[n.mesh].primitives)surfaces.push(gltf.accessors[p.indices??p.attributes.POSITION].count/3);for(const c of n.children||[])visit(c);}
for(const n of gltf.scenes[gltf.scene||0].nodes||[])visit(n);
const record={scene,manual:m,surfaces,createdAt:source.createdAt,history:Object.fromEntries(scene.runs.map(r=>[r.id,runDetail(id,r.id)]))};
const assets=Object.entries(source.files).map(([name,file])=>({key:`${id}/${name}`,file,size:fs.statSync(file).size,contentType:name==='video'?'video/mp4':name.startsWith('frame-')?'image/jpeg':'model/gltf-binary'}));
fs.mkdirSync('output',{recursive:true});const target=path.resolve(process.argv[3]||'output/sites-transfer.json');fs.writeFileSync(target,JSON.stringify({record,assets},null,2));
console.log(JSON.stringify({manifest:target,sceneId:id,assets:assets.length,bytes:assets.reduce((n,a)=>n+a.size,0),hazards:scene.hazards.length}));
