export type Vec3 = [number, number, number];
export type Box = [number, number, number, number];
export type Review = 'unreviewed' | 'confirmed' | 'needs_info' | 'dismissed';
export interface Frame {
  id: string; timestamp: number; url: string; width: number; height: number;
  camera: number[][]; intrinsics: number[][]; sourceFrameId: number;
}
export interface Evidence { id: string; frameId: string; bbox: Box; observation: string }
export interface Anchor {
  position: Vec3; cameraPosition: Vec3; cameraTarget: Vec3;
  status: 'proposed' | 'verified' | 'stale'; method: 'depth' | 'mesh' | 'manual';
  assetRevision: string; surface?: {mesh: string; face: number; normal: Vec3};
}
export interface Hazard {
  id: string; entityId: string; title: string; observation: string; hypothesis: string;
  priority: 'high' | 'medium' | 'low'; reason: string; check: string;
  evidence: Evidence[]; anchor?: Anchor; review: Review; origin: 'astra' | 'manual';
  runId?: string; retained?: boolean;
}
export interface Correction { id: string; center: Vec3; halfExtents: Vec3; revision: number; origin: 'exploration_correction' }
export interface Enhancement {
  id:string; entityId:string; label:string; kind:'lectern'|'desk'|'chair'; position:Vec3; yaw:number;
  bounds:{min:Vec3;max:Vec3}; sourceFrameIds:string[]; provenance:'video_depth_fit';
}
export interface Run {
  id: string; status: 'queued'|'running'|'completed'|'partial'|'failed'|'canceled';
  phase: string; model: string; frameIds: string[]; completedFrameIds: string[];
  providerIds: string[]; startedAt: string; finishedAt?: string; error?: string;
  usage?: {input_tokens: number; output_tokens: number}; resultCount: number;
}
export interface RunDetail {run:Run;hazards:Hazard[];savedAt:string|null}
export interface NavigationSegment {from:Vec3;to:Vec3;valid:boolean;sourceSupport:'supported'|'partial'|'unknown';correctionIds:string[]}
export interface PathCheck {points:Vec3[];segments:NavigationSegment[];correctionIds:string[];valid:boolean;reason:string;assetRevision:string;navigationRevision:number}
export interface RouteRecord extends PathCheck {id:string;checkedAt:string;stale:boolean;validation:'browser_rapier'}
export interface SceneData {
  id: string; title: string; sessionId: string; assetRevision: string;
  duration: number; videoUrl: string; meshUrl: string; originalMeshUrl: string; collisionUrl: string;
  frames: Frame[]; cameraPath: Vec3[]; bounds: {min:Vec3;max:Vec3};
  spawn: {position:Vec3;target:Vec3}; sourceInfo: {vertices:number;triangles:number;textures:number;droppedFrames:number;alignment:string};
  hazards: Hazard[]; runs: Run[]; manualRevision: number; navigationRevision:number; corrections:Correction[]; enhancements?:Enhancement[];reconstruction?:{version:number;assetCount:number;sourceFrameIds:string[]};navigationChecks?:RouteRecord[];
}
export interface LocalScene extends SceneData {
  files: Record<string,string>; sourceDirectory:string; createdAt:string;
}
export interface ManualState { revision:number; hazards: Record<string,Hazard>; reviews:Record<string,{status:Review;at:string}>; navigationRevision:number; corrections:Correction[] }
export interface RuntimeInfo { ready:boolean; progress:string; camera:Vec3; target:Vec3; player:Vec3; grounded:boolean; paused:boolean; fps:number; mode:string; correctionIds:string[]; meshTriangles:number; navigationRevision:number }
export interface SceneHandle {
  overview():void; zoom(factor:number):void; returnToPlayer():void; focus(h:Hazard):boolean;
  cameraFromFrame(frame:Frame,animate?:boolean):void; reset():void; beginWalk():void;
  getInfo():RuntimeInfo; getCamera():{position:Vec3;target:Vec3};
  validatePath(target:Vec3):PathCheck;
}
