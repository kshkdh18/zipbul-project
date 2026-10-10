'use client';
import {t, useLocale} from './Locale';
import {useEffect,useRef,useState,type ReactNode,type PointerEvent} from 'react';

export default function ResizablePanel({side,className,children}:{side:'left'|'right';className:string;children:ReactNode}){
  const {locale}=useLocale();
  const panel=useRef<HTMLElement>(null);
  const drag=useRef<{x:number;width:number}|null>(null);
  const [width,setWidth]=useState<number>();
  const [resizing,setResizing]=useState(false);
  const [maximum,setMaximum]=useState(side==='left'?480:640);
  const minimum=side==='left'?180:240;
  const storageKey=`zipbul-panel-${side}`;

  function limit(){
    const parent=panel.current?.parentElement;
    const other=parent?.querySelector<HTMLElement>(side==='left'?'.evidence-panel':'.sidebar');
    const stage=parent?.querySelector<HTMLElement>('.stage');
    const stageMinimum=stage?Math.max(280,parseFloat(getComputedStyle(stage).minWidth)||0):300;
    return Math.max(minimum,Math.min(side==='left'?480:640,(parent?.clientWidth||window.innerWidth)-(other?.getBoundingClientRect().width||0)-stageMinimum-12));
  }
  function resize(next:number){
    const max=limit(),value=Math.round(Math.max(minimum,Math.min(max,next)));
    // Apply immediately so the canvas ResizeObserver follows the drag.
    if(panel.current)panel.current.style.width=`${value}px`;
    setWidth(value);setMaximum(max);
  }
  function save(){try{localStorage.setItem(storageKey,String(panel.current?.getBoundingClientRect().width||minimum));}catch{}}
  function finish(){drag.current=null;setResizing(false);document.body.classList.remove('panel-resizing');}
  useEffect(()=>{
    let saved=0;try{saved=Number(localStorage.getItem(storageKey));}catch{}
    if(Number.isFinite(saved)&&saved>0)resize(saved);
    const observer=new ResizeObserver(()=>{if(panel.current)resize(panel.current.getBoundingClientRect().width);});
    if(panel.current?.parentElement)observer.observe(panel.current.parentElement);
    return()=>{observer.disconnect();document.body.classList.remove('panel-resizing');};
  },[side]);
  function start(e:PointerEvent<HTMLDivElement>){
    if(e.button!==0)return;
    e.preventDefault();e.currentTarget.focus();e.currentTarget.setPointerCapture(e.pointerId);
    drag.current={x:e.clientX,width:panel.current!.getBoundingClientRect().width};
    setResizing(true);document.body.classList.add('panel-resizing');
  }
  const handle=<div className={`panel-resizer ${resizing?'is-resizing':''}`} role="separator" tabIndex={0}
    aria-label={side==='left'?t("좌측 패널 너비 조절"):t("우측 패널 너비 조절")} aria-orientation="vertical"
    aria-controls={`panel-${side}`} aria-valuemin={minimum} aria-valuemax={maximum} aria-valuenow={width??(side==='left'?235:340)}
    title={t("드래그하여 너비 조절 · 더블 클릭으로 초기화")} onPointerDown={start}
    onPointerMove={e=>{if(drag.current)resize(drag.current.width+(e.clientX-drag.current.x)*(side==='left'?1:-1));}}
    onPointerUp={e=>{if(!drag.current)return;save();finish();e.currentTarget.releasePointerCapture(e.pointerId);}}
    onPointerCancel={finish} onLostPointerCapture={finish}
    onDoubleClick={()=>{if(!panel.current)return;panel.current.style.width='';resize(panel.current.getBoundingClientRect().width);try{localStorage.removeItem(storageKey);}catch{}}}
    onKeyDown={e=>{
      if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
      e.preventDefault();e.stopPropagation();
      const current=panel.current?.getBoundingClientRect().width||minimum;
      resize(e.key==='Home'?minimum:e.key==='End'?limit():current+(e.key==='ArrowRight'?1:-1)*(side==='left'?1:-1)*(e.shiftKey?40:16));save();
    }}/ >;
  return <>{side==='right'&&handle}<aside ref={panel} id={`panel-${side}`} className={className} style={{width}}>{children}</aside>{side==='left'&&handle}</>;
}
