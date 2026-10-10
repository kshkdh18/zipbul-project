'use client';
import {t, useLocale} from './Locale';
import {useState} from 'react';
import {Box,Video,FileJson,Upload,LoaderCircle,X} from 'lucide-react';
import type {SceneData} from '../lib/types';
async function responseBody(r:Response){const b=await r.json().catch(()=>({error:t("서버 응답을 읽지 못했습니다. ({0})", r.status)}));if(!r.ok)throw new Error(b.error||t("요청 실패 ({0})", r.status));return b;}
export default function ImportScene({onClose,onReady}:{onClose:()=>void;onReady:(s:SceneData)=>void}){
  const {locale}=useLocale();
  const [title,setTitle]=useState(''),[mesh,setMesh]=useState<File|null>(null),[video,setVideo]=useState<File|null>(null),[frames,setFrames]=useState<File|null>(null),[phase,setPhase]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  async function submit(){if(!mesh||!video)return;setBusy(true);setError('');setPhase(t("업로드 준비 중"));
    try{const files:{mesh:File;video:File;frames?:File}={mesh,video,...(frames?{frames}:{})};const input={title:title.trim()||mesh.name.replace(/\.glb$/i,''),files:Object.fromEntries(Object.entries(files).map(([key,f])=>[key,{name:f.name,size:f.size}]))};
      const upload=await responseBody(await fetch('/api/uploads',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(input)}));const total=Object.values(files).reduce((n,f)=>n+f.size,0);let sent=0;
      for(const [key,f]of Object.entries(files)){for(let offset=0;offset<f.size;offset+=upload.chunkSize){const chunk=f.slice(offset,offset+upload.chunkSize);await responseBody(await fetch(`/api/uploads/${upload.id}/${key}?offset=${offset}`,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:chunk}));sent+=chunk.size;setPhase(t("원본 업로드 {0}% · {1} / {2} MB", Math.round(sent/total*100), (sent/1048576).toFixed(1), (total/1048576).toFixed(1)));}}
      let job=await responseBody(await fetch(`/api/uploads/${upload.id}/complete`,{method:'POST'}));
      while(job.status==='queued'||job.status==='running'){setPhase(job.phase);await new Promise(r=>setTimeout(r,1500));job=await responseBody(await fetch(`/api/imports/${job.id}`));}
      if(job.status!=='completed')throw new Error(job.error||t("입력 준비 실패"));onReady(await responseBody(await fetch(`/api/scenes/${job.sceneId}`)));
    }catch(e:any){setError(e.message);setBusy(false);}
  }
  return <div className="modal-backdrop"><section className="import-modal"><div className="panel-heading"><strong>{""}{t("새 현장 가져오기")}{""}</strong><button disabled={busy} onClick={onClose} aria-label={t("가져오기 닫기")}><X size={17}/></button></div><div className="import-content"><h2>{""}{t("공간과 원본 영상을 연결합니다.")}{""}</h2><p>{""}{t("같은 공간의 GLB와 영상을 함께 선택하세요. 하나만으로는 현장을 등록할 수 없습니다. 카메라 메타데이터가 없어도 수동 연결로 점검할 수 있습니다.")}{""}</p><label className="import-title">{""}{t("현장 이름")}{""}<input value={title} onChange={e=>setTitle(e.target.value)} maxLength={100} placeholder={t("예: 센터필드 2층")} disabled={busy}/></label>{[{label:t("3D 공간 · GLB · 필수"),icon:Box,accept:'.glb',file:mesh,set:setMesh},{label:t("원본 영상 · 필수"),icon:Video,accept:'.mp4,.mov,.m4v',file:video,set:setVideo},{label:t("frames.jsonl · 선택"),icon:FileJson,accept:'.jsonl',file:frames,set:setFrames}].map(item=><label className="file-picker" key={item.label}><item.icon size={22}/><span><strong>{item.label}</strong><small>{item.file?`${item.file.name} · ${(item.file.size/1048576).toFixed(1)} MB`:t("파일 선택")}</small></span><input type="file" accept={item.accept} disabled={busy} onChange={e=>item.set(e.target.files?.[0]||null)}/></label>)}{error&&<p className="import-error" role="alert">{t(error)}</p>}{busy&&<p className="import-progress"><LoaderCircle size={15} className="spin"/>{t(phase)}</p>}<button className="primary" disabled={!mesh||!video||busy} onClick={submit}><Upload size={15}/>{busy?t("현장 준비 중"):t("가져오기")}</button><small>{""}{t("GLB·영상은 각각 최대 1.5 GB입니다. 준비 완료 후 ‘새 위험 분석’에서 Astra 분석을 시작하세요.")}{""}</small></div></section></div>;
}
