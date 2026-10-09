import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// Run only for an intentional update. The Sites source repository lives outside
// the product monorepo so it never creates a nested Git repository.
const source=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const target=process.argv[2];
if(!target||!path.isAbsolute(target)||target.startsWith(source+path.sep))throw new Error('Supply an absolute Sites checkout outside the monorepo.');
if(!fs.existsSync(path.join(target,'build/sites-worker.ts')))throw new Error('Initialize the Sites Vinext starter first.');
for(const name of ['components','lib'])fs.cpSync(path.join(source,name),path.join(target,name),{recursive:true});
for(const name of ['page.tsx','layout.tsx','globals.css'])fs.copyFileSync(path.join(source,'app',name),path.join(target,'app',name));
fs.mkdirSync(path.join(target,'sites'),{recursive:true});
for(const name of ['api.ts','analysis.ts'])fs.copyFileSync(path.join(source,'sites',name),path.join(target,'sites',name));
let worker=fs.readFileSync(path.join(target,'build/sites-worker.ts'),'utf8');
if(!worker.includes('handleApi')){worker='import {handleApi,type SiteEnv} from "../sites/api";\n'+worker;worker=worker.replace('    let binding = ctx.props?.CONNECTORS;','    if(new URL(request.url).pathname.startsWith("/api/"))return handleApi(request,env as SiteEnv,ctx);\n    let binding = ctx.props?.CONNECTORS;');}
fs.writeFileSync(path.join(target,'build/sites-worker.ts'),worker);
let ui=fs.readFileSync(path.join(target,'components/Workspace.tsx'),'utf8').replace('ZIPBUL / LOCAL','ZIPBUL / SITES');
ui=ui.replace('const focused=viewer.current?.focus(h);\n    if(!focused&&f?.camera.length===4)viewer.current?.cameraFromFrame(f,true);','viewer.current?.focus(h);');
fs.writeFileSync(path.join(target,'components/Workspace.tsx'),ui);
const graph=path.join(target,'components/SpatialRelationGraph.tsx');if(fs.existsSync(graph))fs.writeFileSync(graph,fs.readFileSync(graph,'utf8').replace('element.dataset.azimuth','element!.dataset.azimuth'));
fs.copyFileSync(path.join(source,'sites/ImportScene.tsx'),path.join(target,'components/ImportScene.tsx'));
console.log(JSON.stringify({checkout:target,synced:true}));
