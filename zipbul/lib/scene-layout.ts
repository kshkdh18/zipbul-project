import {parkingLayout,PARKING_REVISION} from './parking-layout';
import type {Vec3} from './types';
export const RECONSTRUCTION_VERSION=5;
export const BUILDING_YAW=Math.PI/10;
export type AssetKind='floor'|'wall'|'ceiling'|'window'|'desk'|'chair'|'lectern'|'whiteboard'|'door'|'light'|'projector'|'clock'|'purifier'|'cart'|'counter'|'cabinet'|'coffeeStation'|'cafeTable'|'yellowChair'|'stool'|'plant'|'pendant'|'glass'|'sign'|'cable'|'rack'|'bicycle'|'electricBicycle'|'scooter'|'panel'|'step'|'railing'|'shrub';
export interface BuiltAsset {id:string;kind:AssetKind;label:string;position:Vec3;size:Vec3;yaw:number;zone:string;photo?:{frameId:string;rect:[number,number,number,number]};points?:Vec3[];}
export function worldPoint(p:Vec3):Vec3{const c=Math.cos(BUILDING_YAW),s=Math.sin(BUILDING_YAW);return [c*p[0]+s*p[2],p[1],-s*p[0]+c*p[2]];}
export function localPoint(p:Vec3):Vec3{const c=Math.cos(BUILDING_YAW),s=Math.sin(BUILDING_YAW);return [c*p[0]-s*p[2],p[1],s*p[0]+c*p[2]];}
/** Bounds and desk positions fitted to GLB planar surfaces; details checked in source frames.
 * All reconstructed support is a simulation proxy, never a surveyed safe surface. */
export function fittedScene(revision:string):BuiltAsset[]{
 if(revision===PARKING_REVISION)return parkingLayout();
 if(revision!=='b97059120e5e80f4')return [];
 const a:BuiltAsset[]=[],counts:Record<string,number>={};
 const add=(kind:AssetKind,position:Vec3,size:Vec3,yaw=0,zone='classroom',extra:Partial<BuiltAsset>={})=>{const id=`rebuilt-${kind}-${counts[kind]=(counts[kind]||0)+1}`;a.push({id,kind,label:kind,position,size,yaw,zone,...extra});return a.at(-1)!;};
 const floor=(u0:number,u1:number,v0:number,v1:number,zone:string)=>add('floor',[(u0+u1)/2,-1.415,(v0+v1)/2],[u1-u0,.07,v1-v0],0,zone);
 floor(-11.5,-1.75,-3.55,6.05,'classroom');floor(-8.6,-1.75,-4.86,-3.55,'classroom');floor(-12.25,-11.5,-3.55,-1.2,'classroom');
 floor(-1.75,.35,-6.0,8.0,'corridor');floor(-11.5,.35,6.05,12.3,'lounge');floor(-10.8,-7.25,12.3,21.6,'cafe');floor(-10.8,-1.25,21.6,24.05,'corridor');
 const wallU=(u:number,v0:number,v1:number,zone='classroom')=>add('wall',[u,.11,(v0+v1)/2],[.10,3.02,v1-v0],0,zone);
 const wallV=(v:number,u0:number,u1:number,zone='classroom')=>add('wall',[(u0+u1)/2,.11,v],[u1-u0,3.02,.10],0,zone);
 wallV(-4.86,-8.6,-2.75);wallV(-3.55,-12.25,-8.6);wallU(-8.6,-4.86,-3.55);wallU(-12.25,-3.55,-1.2);
 wallV(6.05,-9.70,-1.75);wallU(-1.75,-4.86,4.30);wallU(-1.75,5.65,6.05);
 // Doors remain open at observed openings; wall headers preserve their openings.
 add('wall',[-1.75,1.25,4.975],[.11,.7,1.35]);add('wall',[-2.25,1.25,-4.86],[1.0,.7,.11]);
 add('door',[-2.25,-.18,5.62],[.065,2.4,.95],Math.PI/2);add('door',[-2.05,-.18,-4.48],[.065,2.4,.95],.10);
 for(let v=-1.05;v<6;v+=1.25)add('window',[-11.5,.12,v],[.10,3.02,1.25],0,'classroom');
 wallV(12.3,-7.25,.35,'lounge');wallU(.35,7.8,12.3,'lounge');wallU(.35,-6,6.75,'corridor');
 wallV(6.45,-10.15,-1.75,'lounge');wallV(7.8,-10.15,-1.75,'lounge');wallU(-10.15,6.45,7.8,'lounge');wallU(-1.75,6.45,7.8,'lounge');
 for(let v=6.2;v<12.2;v+=1.2)add('window',[-11.5,.52,v],[.1,3.82,1.2],0,'lounge');
 wallU(-7.25,12.3,21.6,'cafe');wallV(24.05,-10.8,-1.25,'corridor');
 for(let v=12.4;v<21.6;v+=1.2)add('window',[-10.8,.52,v],[.1,3.82,1.2],0,'cafe');
 for(const f of a.filter(x=>x.kind==='floor'))add('ceiling',[f.position[0],f.zone==='lounge'||f.zone==='cafe'?2.6:1.64,f.position[2]],[f.size[0],.06,f.size[2]],0,f.zone);
 // 4 rows of mobile training desks, long edges verified in the tabletop point cloud.
 for(const u of [-3.40,-5.30,-7.10,-9.0])for(const v of [-3.10,-1.25,1.90,3.75]){
   if(u===-9.0&&v===-3.10)continue;
   add('desk',[u,-1.38,v],[1.8,.75,.58],Math.PI/2);
   for(const dv of [-.46,.46])add('chair',[u-.55,-1.38,v+dv],[.46,.91,.46],-Math.PI/2);
 }
 add('lectern',[-2.77,-1.38,1.1],[.87,1.25,1.14],-.16);
 for(const v of [-4.795,5.985])add('whiteboard',[v<0?-5.35:-5.15,.04,v],[v<0?5.1:5.8,1.15,.035],v<0?0:Math.PI);
 add('clock',[-8.545,.88,-4.1],[.32,.32,.05],Math.PI/2);
 for(const p of [[-8.08,-4.45],[-10.98,4.9]])add('purifier',[p[0],-1.38,p[1]],[.34,.72,.34]);
 for(const u of [-3.3,-5.8,-8.3])for(const v of [-2.6,2.5])add('light',[u,1.585,v],[.045,.025,3.1]);
 for(const v of [-1.76,3.55])add('projector',[-7.03,1.36,v],[.38,.18,.33]);
 // Utility cart and hospitality island visible in the lounge section.
 add('cart',[-10.5,-1.38,8.76],[.85,.98,.48],0,'lounge');
 add('counter',[-5.50,-1.38,9.8],[4.6,1.05,1.05],0,'lounge');
 for(const u of [-7.4,-6.5,-5.6,-4.7,-3.8])add('stool',[u,-1.38,10.72],[.36,.78,.36],0,'lounge');
 add('cabinet',[-8.2,-1.38,8.1],[1.10,2.15,.6],0,'lounge');add('coffeeStation',[-6.5,-1.38,8.1],[2.15,1.04,.60],0,'lounge');
 add('sign',[.29,.04,9.30],[2.8,1.5,.035],-Math.PI/2,'lounge',{photo:{frameId:'frame-5401',rect:[.50,0,.49,.53]}});
 for(const v of [14.65,16.35,18.1,19.9]){
  add('cafeTable',[-9.65,-1.38,v],[.75,.74,.75],0,'cafe');
  add('yellowChair',[-9.04,-1.38,v],[.48,.83,.48],Math.PI/2,'cafe');
  add('yellowChair',[-10.36,-1.38,v],[.48,.83,.48],-Math.PI/2,'cafe');
  add('pendant',[-9.76,1.36,v],[.36,.22,.36],0,'cafe');
 }
 for(const p of [[-10.3,11.7],[-10.3,15.0],[-10.3,19.2],[-9.9,22.9]])add('plant',[p[0],-1.38,p[1]],[.45,1.45,.45],0,p[1]<12.3?'lounge':'cafe');
 for(let v=12.5;v<21.5;v+=.75)add('cabinet',[-7.30,-.66,v],[.08,1.45,.72],0,'cafe');
 add('glass',[-4.25,.12,21.60],[6.0,3.02,.04],0,'corridor');
 return a;
}
