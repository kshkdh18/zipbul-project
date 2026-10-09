'use client';
import dynamic from 'next/dynamic';
const Workspace=dynamic(()=>import('../components/Workspace'),{ssr:false,loading:()=> <div className="boot"><span className="brand-mark">Z</span><p>현장 작업 공간 준비 중</p></div>});
export default function Page(){return <Workspace/>;}
