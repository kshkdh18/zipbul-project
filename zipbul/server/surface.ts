import fs from 'node:fs';
const cache=new Map<string,{mtime:number;faces:number[]}>();
/** Enumerates the GLB's default scene in node order, matching the displayed primitive IDs. */
export function validSurface(file:string,surface:{mesh:string;face:number}){
  const mtime=fs.statSync(file).mtimeMs;let record=cache.get(file);
  if(!record||record.mtime!==mtime){
    const fd=fs.openSync(file,'r');let json:any;
    try{const head=Buffer.alloc(20);fs.readSync(fd,head,0,20,0);const bytes=Buffer.alloc(head.readUInt32LE(12));fs.readSync(fd,bytes,0,bytes.length,20);json=JSON.parse(bytes.toString());}finally{fs.closeSync(fd);}
    const faces:number[]=[];const visit=(index:number)=>{const node=json.nodes[index];if(node.mesh!==undefined)for(const p of json.meshes[node.mesh].primitives)faces.push(json.accessors[p.indices??p.attributes.POSITION].count/3);for(const child of node.children||[])visit(child);};
    for(const n of json.scenes[json.scene||0].nodes||[])visit(n);record={mtime,faces};cache.set(file,record);
  }
  const match=/^world\/primitive-(\d+)$/.exec(surface.mesh);return !!match&&surface.face>=0&&surface.face<(record.faces[Number(match[1])]||0);
}
