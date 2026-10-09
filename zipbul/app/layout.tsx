import type {Metadata} from 'next';
import './globals.css';
export const metadata:Metadata={title:'짚불 — 현장 탐사',description:'원본 공간과 영상 근거를 연결하는 현장 점검 도구'};
export default function Layout({children}:{children:React.ReactNode}){return <html lang="ko"><body>{children}</body></html>;}
