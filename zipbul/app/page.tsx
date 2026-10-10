'use client';
import dynamic from 'next/dynamic';
const Workspace=dynamic(()=>import('../components/Workspace'),{ssr:false,loading:()=> <div className="boot"><span className="brand-mark">Z</span><p>Preparing field workspace</p></div>});
export default function Page(){return <Workspace/>;}
