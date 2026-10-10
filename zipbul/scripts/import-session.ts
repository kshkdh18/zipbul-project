import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {simplify, weld, prune, getBounds} from '@gltf-transform/functions';
import {MeshoptSimplifier} from 'meshoptimizer';
import {optimizeDisplayGLB,meshIO,DISPLAY_PROFILE} from '../server/optimize-glb';
import type {LocalScene,Frame,Vec3} from '../lib/types';

export async function importSession(sourceDirectory:string, meshPath:string, forcedId?:string) {
  const base=path.resolve(sourceDirectory); meshPath=path.resolve(meshPath);
  const manifest=JSON.parse(await fs.readFile(path.join(base,'manifest.json'),'utf8'));
  const id=forcedId||`scene-${manifest.session_id}`;
  if(!/^scene-[\w-]+$/.test(id)) throw new Error('Invalid scene ID');
  const dir=path.resolve('data/scenes',id); await fs.mkdir(path.join(dir,'frames'),{recursive:true});
  const frameRows=(await fs.readFile(path.join(base,'frames.jsonl'),'utf8')).trim().split('\n').map(l=>JSON.parse(l)).filter(f=>f.video_status==='written');
  if(!frameRows.length||frameRows.some(f=>!Number.isFinite(f.video_pts)||!Array.isArray(f.camera_transform)||!Array.isArray(f.intrinsics)))throw new Error('촬영 메타데이터에 유효한 PTS와 카메라 배열이 필요합니다. 자세가 없으면 빈 배열을 사용하세요.');
  const video=path.join(base,'video.mp4');
  const duration=Number(execFileSync('ffprobe',['-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1',video],{encoding:'utf8'}).trim());
  const bytes=await fs.readFile(meshPath);if(bytes.length<28||bytes.readUInt32LE(0)!==0x46546c67||bytes.readUInt32LE(4)!==2||bytes.readUInt32LE(8)!==bytes.length)throw new Error('유효한 GLB 2.0 파일이 아닙니다.');
  const j=JSON.parse(bytes.subarray(20,20+bytes.readUInt32LE(12)).toString());
  if([...(j.buffers||[]),...(j.images||[])].some(a=>a.uri&&!a.uri.startsWith('data:')))throw new Error('외부 파일 참조가 없는 내장형 GLB가 필요합니다.');
  const positions=j.meshes.flatMap((m:any)=>m.primitives.map((p:any)=>j.accessors[p.attributes.POSITION]));
  const io=meshIO(),doc=await io.readBinary(bytes);
  const rootScene=doc.getRoot().getDefaultScene()||doc.getRoot().listScenes()[0];if(!rootScene||!positions.length)throw new Error('표시 가능한 메시 장면이 없습니다.');
  if(j.meshes.some((m:any)=>m.primitives.some((p:any)=>p.mode!==undefined&&p.mode!==4)))throw new Error('삼각형 메시 GLB를 내보내 주세요.');
  const bounds=getBounds(rootScene);if([...bounds.min,...bounds.max].some(v=>!Number.isFinite(v)))throw new Error('유효한 공간 범위를 읽지 못했습니다.');
  const revision=crypto.createHash('sha256').update(bytes).digest('hex').slice(0,16);
  const frames:Frame[]=[]; const files:Record<string,string>={video,original:meshPath};
  // Each image is paired with the nearest actual written sample's PTS and camera, including the dropped-frame gap.
  for(let t=0;t<duration;t+=15){
    const f=frameRows.reduce((a:any,b:any)=>Math.abs(b.video_pts-t)<Math.abs(a.video_pts-t)?b:a);
    const fid=`frame-${f.frame_id}`; const out=path.join(dir,'frames',`${fid}.jpg`);
    execFileSync('ffmpeg',['-v','error','-ss',String(f.video_pts),'-i',video,'-frames:v','1','-vf','scale=1280:-2','-q:v','2','-y',out]);
    files[fid]=out;frames.push({id:fid,timestamp:f.video_pts,url:`/api/scenes/${id}/assets/${fid}`,width:f.image_width,height:f.image_height,camera:f.camera_transform,intrinsics:f.intrinsics,sourceFrameId:f.frame_id});
  }
  console.log(`Prepared ${frames.length} source frames. Preparing textures / collision geometry…`);
  const optimized=path.join(dir,'render.glb');const collision=path.join(dir,'collision.glb');
  const previous=await fs.readFile(path.join(dir,'scene.json'),'utf8').then(JSON.parse).catch(()=>null);
  let displayOptimization=previous?.sourceInfo?.displayOptimization;
  if(previous?.assetRevision!==revision||previous?.optimizedMeshUrl||displayOptimization?.profile!==DISPLAY_PROFILE||!await fs.stat(optimized).catch(()=>null)){
    const report=await optimizeDisplayGLB(meshPath,optimized);
    displayOptimization={profile:DISPLAY_PROFILE,bytes:report.outputBytes,textureMaxSize:3072,geometryPreserved:true};
  }
  if(previous?.assetRevision!==revision||!await fs.stat(collision).catch(()=>null)){
    await MeshoptSimplifier.ready;
    for(const mesh of doc.getRoot().listMeshes())for(const p of mesh.listPrimitives()){p.setMaterial(null); for(const s of p.listSemantics())if(s!=='POSITION')p.setAttribute(s,null);}
    await doc.transform(weld(),simplify({simplifier:MeshoptSimplifier,ratio:.12,error:.015}),prune());
    await io.write(collision,doc);
  }
  files.mesh=optimized;files.collision=collision;
  const camPath=frameRows.filter((f:any,i:number)=>i%30===0&&f.camera_transform?.length===4).map((f:any)=>f.camera_transform.slice(0,3).map((r:number[])=>r[3]) as Vec3);
  const first=frames[0].camera;const hasPose=first.length===4;
  const center=bounds.min.map((x,i)=>(x+bounds.max[i])/2) as Vec3;
  const pos=hasPose?first.slice(0,3).map(r=>r[3]) as Vec3:[center[0],bounds.min[1]+1.65,center[2]] as Vec3;
  const target=hasPose?first.slice(0,3).map((r,i)=>pos[i]-r[2]*3) as Vec3:[center[0],pos[1],center[2]-3] as Vec3;
  const scene:LocalScene={id,title:previous?.title||manifest.title||`새 현장 · ${manifest.session_id.slice(0,8)}`,sessionId:manifest.session_id,assetRevision:revision,createdAt:new Date().toISOString(),sourceDirectory:base,files,duration,
    videoUrl:`/api/scenes/${id}/assets/video`,meshUrl:`/api/scenes/${id}/assets/mesh`,originalMeshUrl:`/api/scenes/${id}/assets/original`,collisionUrl:`/api/scenes/${id}/assets/collision`,frames,cameraPath:camPath,bounds,spawn:{position:pos,target},
    sourceInfo:{displayOptimization,vertices:positions.reduce((s:number,a:any)=>s+a.count,0),triangles:j.meshes.reduce((s:number,m:any)=>s+m.primitives.reduce((n:number,p:any)=>n+j.accessors[p.indices??p.attributes.POSITION].count/3,0),0),textures:j.textures?.length||0,droppedFrames:manifest.summary?.video_dropped||0,alignment:hasPose?'카메라 좌표 제공 · 영상/공간 대조 필요':'촬영 자세 미제공 · 수동 연결'},
    hazards:[],runs:[],manualRevision:0,navigationRevision:1,corrections:[]};
  await fs.writeFile(path.join(dir,'scene.json'),JSON.stringify(scene,null,2));
  console.log(JSON.stringify({id,frames:frames.length,duration,renderMiB:Math.round((await fs.stat(optimized)).size/1048576),collisionMiB:Math.round((await fs.stat(collision)).size/1048576),bounds}));
  return scene;
}
if(process.argv[1]?.endsWith('import-session.ts')){
  const [directory,glb]=process.argv.slice(2);if(!directory||!glb)throw new Error('Usage: npm run import -- session-directory textured.glb');
  await importSession(directory,glb);
}
