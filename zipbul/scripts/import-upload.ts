import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {importSession} from './import-session';
const id=process.argv[2];if(!/^import-[\w-]+$/.test(id))throw new Error('잘못된 가져오기 ID');
const dir=path.resolve('data/imports',id),jobFile=path.join(dir,'job.json');
const save=(data:unknown)=>{fs.writeFileSync(jobFile+'.tmp',JSON.stringify(data));fs.renameSync(jobFile+'.tmp',jobFile);};
const job=JSON.parse(fs.readFileSync(jobFile,'utf8'));
try{
  save({...job,status:'running',phase:'원본 검사·표본 프레임 준비'});
  const video=path.join(dir,'video.mp4');
  const meta=JSON.parse(execFileSync('ffprobe',['-v','error','-select_streams','v:0','-show_entries','stream=width,height,start_time:frame=best_effort_timestamp_time','-of','json',video],{encoding:'utf8',maxBuffer:40*1024*1024}));
  const stream=meta.streams[0];if(!stream||!meta.frames?.length)throw new Error('영상을 읽을 수 없습니다.');
  if(!fs.existsSync(path.join(dir,'frames.jsonl'))){const rows=meta.frames.map((f:any,i:number)=>({frame_id:i+1,video_status:'written',video_pts:Number(f.best_effort_timestamp_time)-(Number(stream.start_time)||0),camera_transform:[],intrinsics:[],image_width:stream.width,image_height:stream.height}));fs.writeFileSync(path.join(dir,'frames.jsonl'),rows.map((r:any)=>JSON.stringify(r)).join('\n'));}
  fs.writeFileSync(path.join(dir,'manifest.json'),JSON.stringify({session_id:id.slice(7),summary:{video_dropped:0},source:'browser-upload',title:job.title||'새 현장'}));
  const scene=await importSession(dir,path.join(dir,'scene.glb'));
  save({...job,status:'completed',phase:'현장 준비 완료',sceneId:scene.id});
}catch(e:any){save({...job,status:'failed',phase:'가져오기 실패',error:String(e.message).slice(0,800)});process.exitCode=1;}
