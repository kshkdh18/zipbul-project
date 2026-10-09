'use client';
import {X} from 'lucide-react';
import type {SceneData} from '../lib/types';
export default function ImportScene({onClose}:{onClose:()=>void;onReady:(s:SceneData)=>void}){
  return <div className="modal-backdrop"><section className="import-modal"><div className="panel-heading"><strong>새 현장 준비</strong><button onClick={onClose}><X size={17}/></button></div><div className="import-content"><h2>원본 영상과 GLB 준비가 필요합니다.</h2><p>새 촬영 세션은 로컬 짚불에서 가져온 뒤 이 사이트로 전송합니다. 현재 등록된 현장의 탐사, 재분석, 대화, 검토 저장은 사이트에서 사용할 수 있습니다.</p><button className="primary" onClick={onClose}>확인</button></div></section></div>;
}
