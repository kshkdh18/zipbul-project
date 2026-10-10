'use client';
import {useEffect,useRef,useState} from 'react';
import {ArrowLeft,ArrowRight,Check,CheckCircle2,RotateCcw,X} from 'lucide-react';
import {guideSteps,GUIDE_STORAGE_KEY,readGuideState} from '../lib/onboarding';
import {useLocale} from './Locale';

export default function GuidedTour({index,onStep,onClose,onProgress}:{index:number;onStep:(index:number)=>void;onClose:()=>void;onProgress:(count:number)=>void}) {
  const {locale}=useLocale(),en=locale==='en',step=guideSteps[index];
  const [checked,setChecked]=useState<string[]>([]),[rect,setRect]=useState<DOMRect|null>(null);
  const [viewport,setViewport]=useState({width:1280,height:800});
  const card=useRef<HTMLElement>(null),close=useRef(onClose);close.current=onClose;
  useEffect(()=>{try{setChecked(readGuideState(localStorage.getItem(GUIDE_STORAGE_KEY)).checked);}catch{}},[]);
  useEffect(()=>{
    card.current?.focus({preventScroll:true});
    let frame=0,last='';
    const update=()=>{
      const target=document.querySelector(step.target),r=target?.getBoundingClientRect();
      const valid=r&&r.width>0&&r.height>0?r:null;
      const signature=JSON.stringify(valid?[valid.x,valid.y,valid.width,valid.height,innerWidth,innerHeight]:[innerWidth,innerHeight]);
      if(signature!==last){last=signature;setRect(valid);setViewport({width:innerWidth,height:innerHeight});}
      frame=requestAnimationFrame(update);
    };update();return()=>cancelAnimationFrame(frame);
  },[step]);
  useEffect(()=>{const escape=(event:KeyboardEvent)=>{if(event.key==='Escape'&&!document.pointerLockElement){event.stopImmediatePropagation();event.preventDefault();close.current();}};window.addEventListener('keydown',escape,true);return()=>window.removeEventListener('keydown',escape,true);},[]);
  function save(next:string[]){setChecked(next);onProgress(next.length);try{localStorage.setItem(GUIDE_STORAGE_KEY,JSON.stringify({checked:next,dismissed:true}));}catch{}}
  const width=Math.min(380,viewport.width-24),height=360,margin=16;
  let left=viewport.width-width-margin,top=Math.max(90,(viewport.height-height)/2);
  if(rect){
    if(rect.right+width+margin*2<viewport.width)left=rect.right+margin;
    else if(rect.left>width+margin*2)left=rect.left-width-margin;
    else left=Math.max(margin,Math.min(viewport.width-width-margin,rect.left+rect.width/2-width/2));
    top=rect.bottom+height+margin<viewport.height?rect.bottom+margin:rect.top-height-margin>60?rect.top-height-margin:Math.max(100,Math.min(viewport.height-height-margin,rect.top+48));
  }
  return <div className="tour-layer">
    {rect&&<div className="tour-spotlight" style={{left:Math.max(2,rect.left-5),top:Math.max(2,rect.top-5),width:Math.min(rect.width+10,viewport.width-4),height:Math.min(rect.height+10,viewport.height-4)}}/>}
    <section className="tour-card" ref={card} tabIndex={-1} data-tour-dialog role="dialog" aria-label={en?'Getting started guide':'사용 가이드'} style={{left,top,width,maxHeight:viewport.height-top-12}}>
      <header><span>{en?'QUICK TOUR':'사용 가이드'} <b>{index+1} / {guideSteps.length}</b></span><button onClick={onClose} aria-label={en?'Close guide':'가이드 닫기'}><X size={17}/></button></header>
      <h2>{step[locale][0]}</h2><p>{step[locale][1]}</p>
      {!rect&&<small className="tour-missing">{en?'Select an inspection item to show this control. If the site has no items, start an analysis or add your own observation.':'점검 항목을 선택하면 이 기능이 표시됩니다. 항목이 없다면 분석하거나 관찰 내용을 추가하세요.'}</small>}
      <label className="tour-check"><input type="checkbox" checked={checked.includes(step.id)} onChange={e=>save(e.target.checked?[...checked,step.id]:checked.filter(id=>id!==step.id))}/><CheckCircle2 size={17}/>{en?'I understand this step':'이 단계 사용법을 확인했어요'}</label>
      <div className="tour-dots" aria-label={en?'Guide steps':'가이드 단계'}>{guideSteps.map((s,i)=><button key={s.id} onClick={()=>onStep(i)} className={`${i===index?'current':''} ${checked.includes(s.id)?'checked':''}`} aria-label={`${i+1}. ${s[locale][0]}`} aria-current={i===index?'step':undefined}>{checked.includes(s.id)?<Check size={11}/>:i+1}</button>)}</div>
      <footer><button onClick={()=>onStep(index-1)} disabled={index===0}><ArrowLeft size={14}/>{en?'Back':'이전'}</button><span>{checked.length}/{guideSteps.length} {en?'checked':'확인'}</span>{index===guideSteps.length-1?<button className="primary" onClick={onClose}>{en?'Finish':'마치기'}<Check size={14}/></button>:<button className="primary" onClick={()=>onStep(index+1)}>{en?'Next':'다음'}<ArrowRight size={14}/></button>}</footer>
      {checked.length===guideSteps.length&&<div className="tour-complete"><span>{en?'All steps checked. Reopen the guide anytime.':'모든 단계를 확인했습니다. 언제든 다시 볼 수 있어요.'}</span><button onClick={()=>save([])} aria-label={en?'Reset guide checks':'가이드 체크 초기화'}><RotateCcw size={13}/></button></div>}
    </section>
  </div>;
}
