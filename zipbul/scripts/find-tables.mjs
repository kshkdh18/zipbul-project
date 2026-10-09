import fs from 'node:fs';import {NodeIO} from '@gltf-transform/core';import sharp from 'sharp';
const doc=await new NodeIO().read('data/scenes/scene-105bfbad-4a6f-4174-98ea-c10341cda210/collision.glb');const pts=[];
for(const m of doc.getRoot().listMeshes())for(const p of m.listPrimitives()){const a=p.getAttribute('POSITION').getArray(),ix=p.getIndices().getArray();for(let n=0;n<ix.length;n+=3){const A=[...a.slice(ix[n]*3,ix[n]*3+3)],B=[...a.slice(ix[n+1]*3,ix[n+1]*3+3)],C=[...a.slice(ix[n+2]*3,ix[n+2]*3+3)],u=B.map((x,i)=>x-A[i]),v=C.map((x,i)=>x-A[i]),normal=[u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]],cen=A.map((x,i)=>(x+B[i]+C[i])/3);if(cen[1]>-.78&&cen[1]<-.53&&Math.abs(normal[1])/Math.hypot(...normal)>.9)pts.push([cen[0]*.9510565-cen[2]*.309017,cen[0]*.309017+cen[2]*.9510565]);}}
let svg='<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="900"><rect width="100%" height="100%" fill="#1b2025"/>';
const px=x=>(x+13)*70+30,py=z=>(z+6)*55+30;
for(let x=-13;x<=1;x+=.5)svg+=`<line x1="${px(x)}" x2="${px(x)}" y1="20" y2="890" stroke="#3a3e44"/><text x="${px(x)}" y="15" fill="white" font-size="10">${x}</text>`;
for(let z=-6;z<10;z+=.5)svg+=`<line x1="25" x2="995" y1="${py(z)}" y2="${py(z)}" stroke="#3a3e44"/><text x="1" y="${py(z)}" fill="white" font-size="10">${z}</text>`;
for(const p of pts)svg+=`<circle cx="${px(p[0])}" cy="${py(p[1])}" r="1.1" fill="#d4bd91"/>`;svg+='</svg>';await sharp(Buffer.from(svg)).png().toFile('output/table-surfaces.png');
