'use client';
import {t, useLocale} from './Locale';
import {useEffect,useRef,useState,type PointerEvent} from 'react';
import {ArrowRight,Focus,GitBranch,GripHorizontal,MapPin,Video,X} from 'lucide-react';
import type {Frame,Hazard} from '../lib/types';

export default function FocusContext({hazard,frame,located,onClose,onGraph,onEvidence,onFocus,onCheck}:{hazard:Hazard;frame?:Frame;located:boolean;onClose:()=>void;onGraph:()=>void;onEvidence:()=>void;onFocus:()=>void;onCheck:()=>void}){
  const {locale}=useLocale();
  const panel=useRef<HTMLElement>(null),drag=useRef<{x:number;y:number;left:number;top:number}|null>(null);
  const [position,setPosition]=useState<{left:number;top:number}|null>(null),[dragging,setDragging]=useState(false);
  function move(left:number,top:number){const el=panel.current,parent=el?.parentElement;if(!el||!parent)return;setPosition({left:Math.max(8,Math.min(parent.clientWidth-el.offsetWidth-8,left)),top:Math.max(44,Math.min(parent.clientHeight-el.offsetHeight-35,top))});}
  function start(e:PointerEvent<HTMLDivElement>){if(e.button!==0||(e.target as HTMLElement).closest('button'))return;const el=panel.current!,parent=el.parentElement!.getBoundingClientRect(),rect=el.getBoundingClientRect();e.preventDefault();e.stopPropagation();e.currentTarget.setPointerCapture(e.pointerId);drag.current={x:e.clientX,y:e.clientY,left:rect.left-parent.left,top:rect.top-parent.top};setDragging(true);}
  function finish(){drag.current=null;setDragging(false);}
  useEffect(()=>{const parent=panel.current?.parentElement;if(!parent)return;const observer=new ResizeObserver(()=>setPosition(p=>{const el=panel.current;if(!p||!el)return p;return {left:Math.max(8,Math.min(parent.clientWidth-el.offsetWidth-8,p.left)),top:Math.max(44,Math.min(parent.clientHeight-el.offsetHeight-35,p.top))};}));observer.observe(parent);return()=>observer.disconnect();},[]);
  return <section ref={panel} className={`focus-context ${dragging?'is-dragging':''}`} aria-label={t("선택한 점검의 근거와 관계")} data-hazard-id={hazard.id} style={position?{left:position.left,top:position.top,bottom:'auto'}:undefined}>
    <div className="focus-context-heading" role="group" aria-label={t("근거 박스 이동")} tabIndex={0} title={t("제목줄을 드래그해 이동 · 방향키로 이동 · 더블 클릭으로 위치 복원")} onPointerDown={start} onPointerMove={e=>{if(drag.current){e.stopPropagation();move(drag.current.left+e.clientX-drag.current.x,drag.current.top+e.clientY-drag.current.y);}}} onPointerUp={e=>{finish();if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);}} onPointerCancel={finish} onLostPointerCapture={finish} onDoubleClick={e=>{if(!(e.target as HTMLElement).closest('button'))setPosition(null);}} onKeyDown={e=>{if(e.target!==e.currentTarget||!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(e.key))return;e.preventDefault();e.stopPropagation();const el=panel.current!,parent=el.parentElement!.getBoundingClientRect(),r=el.getBoundingClientRect(),step=e.shiftKey?40:16;move(r.left-parent.left+(e.key==='ArrowRight'?step:e.key==='ArrowLeft'?-step:0),r.top-parent.top+(e.key==='ArrowDown'?step:e.key==='ArrowUp'?-step:0));}}><span><GripHorizontal size={13}/><MapPin size={12}/>{located?t("연결 위치 집중 보기"):frame?.camera.length?t("촬영 시점 · 대상 위치 미확정"):t("영상 근거 · 공간 위치 미확인")}</span><button onClick={onClose} aria-label={t("근거 박스 숨기기")} title={t("카메라 시점을 유지하고 박스만 숨깁니다")}><X size={14}/></button></div>
    <h2>{t(hazard.title)}</h2>
    <div className="focus-chain">
      <button onClick={onEvidence} title={t("연결된 영상 근거 보기")}><span><Video size={12}/>{""}{t("관찰 근거")}{""}</span><p>{t(hazard.evidence.find(e=>e.frameId===frame?.id)?.observation||hazard.observation)}</p><small>{t("영상 {0}개 연결",hazard.evidence.length)}</small></button>
      <ArrowRight size={12} className="focus-chain-arrow"/>
      <button onClick={onFocus} className="focus-chain-risk" title={located?t("연결된 대상 가까이 보기"):t("촬영 시점 보기")}><span><Focus size={12}/>{""}{t("위험 해석")}{""}</span><p>{t(hazard.hypothesis)}</p><small>{""}{t("현장 확인 필요")}{""}</small></button>
      <ArrowRight size={12} className="focus-chain-arrow"/>
      <button onClick={onCheck} title={t("현장 점검 내용 보기")}><span>{""}{t("현장 점검")}{""}</span><p>{t(hazard.check)}</p><small>{""}{t("점검 내용 열기")}{""}</small></button>
    </div>
    <button className="focus-expand" onClick={onGraph}><GitBranch size={12}/>{""}{t("연결 관계 펼치기")}{""}<ArrowRight size={12}/></button>
  </section>;
}
