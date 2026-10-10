import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const app=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const source=path.join(app,'demo-assets');
const target=path.resolve(process.env.ZIPBUL_DATA_DIR||path.join(app,'data/scenes'));
for(const id of fs.readdirSync(source).filter(x=>x.startsWith('scene-'))){
  const src=path.join(source,id),dst=path.join(target,id);
  if(fs.existsSync(path.join(dst,'scene.json'))){console.log(`Preserved existing scene: ${id}`);continue;}
  const scene=JSON.parse(fs.readFileSync(path.join(src,'scene.json'),'utf8'));
  for(const relative of Object.values(scene.files)){
    const file=path.join(src,relative);
    if(!fs.existsSync(file))throw new Error(`Missing demo asset: ${file}`);
    if(relative.endsWith('.glb')&&fs.readFileSync(file).subarray(0,4).toString()!=='glTF')throw new Error(`Run git lfs pull before setup: ${file}`);
  }
  fs.cpSync(src,dst,{recursive:true});
  for(const [key,relative] of Object.entries(scene.files))scene.files[key]=path.join(dst,relative);
  scene.sourceDirectory=dst;
  fs.writeFileSync(path.join(dst,'scene.json'),JSON.stringify(scene,null,2)+'\n');
  console.log(`Installed demo: ${id}`);
}
