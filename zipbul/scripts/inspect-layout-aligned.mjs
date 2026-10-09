import fs from 'node:fs';import sharp from 'sharp';import {NodeIO} from '@gltf-transform/core';import {ALL_EXTENSIONS} from '@gltf-transform/extensions';
const id='scene-105bfbad-4a6f-4174-98ea-c10341cda210',s=JSON.parse(fs.readFileSync(`data/scenes/${id}/scene.json`,'utf8'));
const d=await new NodeIO().registerExtensions(ALL_EXTENSIONS).read(s.files.collision);const points=[],angles=new Map(),heights=new Map();
for(const m of d.getRoot().listMeshes())for(const p of m.listPrimitives()){const a=p.getAttribute('POSITION').getArray(),ind=p.getIndices().getArray();for(let n=0;n<ind.length;n+=3){const A=[...a.slice(ind[n]*3,ind[n]*3+3)],B=[...a.slice(ind[n+1]*3,ind[n+1]*3+3)],C=[...a.slice(ind[n+2]*3,ind[n+2]*3+3)];const u=B.map((x,i)=>x-A[i]),v=C.map((x,i)=>x-A[i]),norm=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],area=Math.hypot(...norm)/2,center=A.map((x,i)=>(x+B[i]+C[i])/3);const ny=norm[1]/(area*2);if(Math.abs(ny)<.15){const ang=(Math.atan2(norm[2],norm[0])*180/Math.PI+360)%90,k=Math.round(ang);angles.set(k,(angles.get(k)||0)+area);}if(Math.abs(ny)>.9){const k=Math.round(center[1]*20)/20;heights.set(k,(heights.get(k)||0)+area);}if(n%9===0)points.push(center);}}
console.log('Angles',JSON.stringify([...angles].sort((a,b)=>b[1]-a[1]).slice(0,12)));console.log('Height',JSON.stringify([...heights].sort((a,b)=>b[1]-a[1]).slice(0,18)));
console.log('Cameras',JSON.stringify(s.frames.map(f=>({id:f.id,t:f.timestamp,p:f.camera.slice(0,3).map(r=>r[3]),forward:f.camera.slice(0,3).map(r=>-r[2])}))));
const rotate=p=>[.9510565*p[0]-.309017*p[2],p[1],.309017*p[0]+.9510565*p[2]];for(let i=0;i<points.length;i++)points[i]=rotate(points[i]);
const scale=28,minx=-17,minz=-8,px=x=>(x-minx)*scale+35,py=z=>(z-minz)*scale+35;
let svg='<svg xmlns="http://www.w3.org/2000/svg" width="760" height="1110"><rect width="100%" height="100%" fill="#182129"/>';
for(let x=-16;x<9;x++)svg+=`<line x1="${px(x)}" y1="25" x2="${px(x)}" y2="1080" stroke="#303a42"/><text x="${px(x)}" y="18" fill="white" font-size="9">${x}</text>`;
for(let z=-8;z<29;z++)svg+=`<line x1="25" y1="${py(z)}" x2="740" y2="${py(z)}" stroke="#303a42"/><text x="7" y="${py(z)}" fill="white" font-size="9">${z}</text>`;
for(const p of points){if(p[1]>1.0||p[1]<-1.6)continue;svg+=`<circle cx="${px(p[0])}" cy="${py(p[2])}" r=".65" fill="${p[1]<-1.12?'#5b6268':p[1]<-.4?'#deb671':'#c4d5e0'}"/>`;}
for(const f of s.frames){const p=rotate(f.camera.slice(0,3).map(r=>r[3]));svg+=`<circle cx="${px(p[0])}" cy="${py(p[2])}" r="3" fill="#5cd5ff"/><text x="${px(p[0])+4}" y="${py(p[2])-3}" fill="#61e0ff" font-size="12">${Math.round(f.timestamp)}s</text>`;}
svg+='</svg>';await sharp(Buffer.from(svg)).png().toFile('output/layout-aligned.png');
