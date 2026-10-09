import type {Enhancement} from './types';
/** Only this exact supplied scan is fitted. Dimensions are estimates, not survey measurements.
 * Frame 901 (30.003s): depth-projected lectern side (-2.325,-.200,2.503),
 * desk surface (-3.120,-.595,2.712), chair seat (-2.977,-.831,2.952).
 * Raw source geometry stays available in analysis and comparison views.
 */
export function representativeEnhancements(assetRevision:string):Enhancement[]{
  if(assetRevision!=='b97059120e5e80f4')return [];
  return [
    {id:'visual-lectern-01',entityId:'entity-lectern-01',label:'연단 · 영상/깊이 기반 형상 보완',kind:'lectern',position:[-2.30,-1.35,1.90],yaw:0.15,bounds:{min:[-2.86,-1.28,1.05],max:[-1.63,.65,2.65]},sourceFrameIds:['frame-901','frame-1351'],provenance:'video_depth_fit'},
    {id:'visual-desk-01',entityId:'entity-desk-01',label:'앞줄 책상 · 영상/깊이 기반 형상 보완',kind:'desk',position:[-3.23,-1.35,3.35],yaw:1.92,bounds:{min:[-3.9,-.79,2.39],max:[-2.53,-.40,4.43]},sourceFrameIds:['frame-901'],provenance:'video_depth_fit'},
    {id:'visual-chair-01',entityId:'entity-chair-01',label:'앞줄 의자 · 영상/깊이 기반 형상 보완',kind:'chair',position:[-3.71,-1.35,3.09],yaw:1.92,bounds:{min:[-4.07,-1.28,2.71],max:[-3.29,-.42,3.55]},sourceFrameIds:['frame-901'],provenance:'video_depth_fit'}
  ];
}
