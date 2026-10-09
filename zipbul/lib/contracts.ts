import { z } from 'zod';
import type { Box, Vec3 } from './types';
export const vector = z.tuple([z.number().finite(),z.number().finite(),z.number().finite()]);
export const bbox = z.tuple([z.number().min(0).max(1),z.number().min(0).max(1),z.number().positive().max(1),z.number().positive().max(1)]).refine(b=>b[0]+b[2]<=1.001&&b[1]+b[3]<=1.001,'영역이 프레임 밖입니다.');
export function projectDepth(pixel:[number,number], depth:number, intrinsics:number[][], camera:number[][]):Vec3 {
  const local=[(pixel[0]-intrinsics[0][2])/intrinsics[0][0]*depth,-(pixel[1]-intrinsics[1][2])/intrinsics[1][1]*depth,-depth,1];
  return camera.slice(0,3).map(row=>row.reduce((s,v,i)=>s+v*local[i],0)) as Vec3;
}
export function validBox(b:Box) {return bbox.safeParse(b).success;}
export function classification(segments:{valid:boolean;correctionIds:string[];sourceSupport:'supported'|'partial'|'unknown'}[]) {
  return {valid:segments.length>0&&segments.every(s=>s.valid),kind:segments.some(s=>s.correctionIds.length)?'simulation':segments.some(s=>s.sourceSupport==='unknown')?'unverified':'observed'};
}
export function canFocus(anchor?:{status:string;assetRevision:string}, revision?:string) {return !!anchor&&anchor.status==='verified'&&anchor.assetRevision===revision;}
