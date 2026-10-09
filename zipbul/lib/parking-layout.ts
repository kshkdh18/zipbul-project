import type {BuiltAsset,AssetKind} from './scene-layout';
import type {Vec3} from './types';
export const PARKING_REVISION='70dc87f915b3ace9';
export const PARKING_YAW=Math.PI/90;
export function parkingWorld(p:Vec3):Vec3{const c=Math.cos(PARKING_YAW),s=Math.sin(PARKING_YAW);return [c*p[0]+s*p[2],p[1],-s*p[0]+c*p[2]];}
/** Plane bounds from the collision GLB; source camera/depth and video constrain equipment.
 * Geometry is an estimated reconstruction. Every support collider is a simulation surface. */
export function parkingLayout():BuiltAsset[]{
 const a:BuiltAsset[]=[],counts:Record<string,number>={};
 const add=(kind:AssetKind,p:Vec3,size:Vec3,yaw=0,zone='bicycle',extra:Partial<BuiltAsset>={})=>{a.push({id:`parking-${kind}-${counts[kind]=(counts[kind]||0)+1}`,kind,label:kind,position:p,size,yaw,zone,...extra});return a.at(-1)!;};
 const floor=(x0:number,x1:number,z0:number,z1:number,zone='bicycle',top=-1.4)=>add('floor',[(x0+x1)/2,top-.06,(z0+z1)/2],[x1-x0,.12,z1-z0],0,zone);
 const wall=(x0:number,z0:number,x1:number,z1:number,height=3.96,zone='bicycle',bottom=-1.4)=>add('wall',[(x0+x1)/2,bottom+height/2,(z0+z1)/2],[Math.hypot(x1-x0,z1-z0),height,.12],-Math.atan2(z1-z0,x1-x0),zone);
 floor(-.85,.65,-4.25,4.65,'entry');floor(.65,12.55,-4.1,4.55);floor(-1.8,18.5,4.55,6.72,'corridor');floor(10.15,18.6,6.72,9.8,'electric');floor(16.3,19.7,3.95,6.72,'electric');floor(9.85,12.55,-18.45,-4.1,'corridor');floor(-1.8,.52,6.72,11.2,'exit');floor(-1.8,6.35,11.2,13.0,'outdoor');floor(4.1,5.9,13,18.3,'outdoor');
 wall(-.85,-4.25,-.85,4.45,2.72,'louver');wall(.65,-4.25,.65,3.25,2.72,'entry');wall(-.85,-4.25,.65,-4.25,2.72,'entry');
 wall(.65,-4.1,9.85,-4.1);wall(.65,3.25,2.2,3.25);wall(9.85,-4.1,9.85,-5.25);wall(9.85,-5.25,9.25,-5.25);wall(9.25,-5.25,9.25,-12.4);wall(9.25,-12.4,10.05,-12.4);wall(10.05,-12.4,10.05,-13.3);wall(10.05,-13.3,9.25,-13.3);wall(9.25,-13.3,9.25,-18.45);wall(9.25,-18.45,12.55,-18.45);
 wall(-1.8,6.72,10.15,6.72,3.96,'corridor');wall(-1.8,5.75,-.7,4.55,2.72,'louver');wall(-.7,4.55,2.2,4.55,2.72,'louver');
 wall(10.15,6.72,10.15,9.8);wall(10.15,9.8,18.6,9.8);wall(18.6,9.8,18.6,6.72);wall(18.6,6.72,19.7,6.72);wall(19.7,6.72,19.7,3.95);wall(16.3,3.95,19.7,3.95);
 wall(-1.8,6.72,-1.8,11.2,2.72,'stone');wall(.52,6.72,.52,11.2,2.72,'stone');
 for(let z=-18.45;z<4.4;z+=1.25)add('glass',[12.60,.43,z+.625],[1.25,3.66,.10],Math.PI/2,'corridor');
 // Exposed concrete slabs, ducts, linear fixtures — no invented decorative ceiling.
 for(const f of a.filter(x=>x.kind==='floor'&&!['outdoor','exit'].includes(x.zone))){add('ceiling',[f.position[0],f.zone==='entry'?1.3:2.56,f.position[2]],[f.size[0],.12,f.size[2]],0,f.zone);}
 add('ceiling',[-.64,1.28,8.9],[2.3,.10,4.5],0,'exit');
 for(const x of [2.15,6.1,10.3])for(const z of [-2,2.0])add('light',[x,2.05,z],[.075,.045,2.35]);
 for(let z=-17;z<7;z+=3.6)add('light',[11.25,2.06,z],[.075,.045,2.0],0,'corridor');
 for(const x of [1,4.8,8.6,13,16.7])add('light',[x,2.05,5.55],[.075,.045,2],Math.PI/2,'corridor');
 add('light',[15.4,2.05,8.2],[.075,.045,2.3],Math.PI/2,'electric');add('light',[-.1,1.02,-1.1],[.06,.04,1.1],0,'entry');
 for(const x of [3.05,8.05])add('rack',[x,-1.4,-.50],[3.05,2.24,6.15],0,'bicycle');
 // Sparse observed occupancy, leaving the many empty rails visible in the source.
 const bikes:[number,number,number,string][]=[[3.40,2.32,Math.PI,'silver'],[3.40,1.60,Math.PI,'blue'],[3.4,-.56,Math.PI,'silver'],[7.98,-3.02,0,'teal'],[7.98,-2.30,0,'black'],[8.0,.58,0,'silver']];
 for(const [x,z,yaw,color]of bikes)add('bicycle',[x,-1.35,z],[1.82,1.12,.64],yaw,'bicycle',{label:color});
 // Electric cycle bays along the far wall, seen at 375–450s.
 add('rack',[14.4,-1.4,8.55],[2.12,1.85,7.5],Math.PI/2,'electric');
 for(const [i,x]of [11.9,13.05,14.1,15.45,16.2,17.45].entries())add('electricBicycle',[x,-1.35,8.4],[1.7,1.26,.68],Math.PI/2,'electric',{label:i===3||i===4?'cargo':i===2?'cream':'black'});
 add('scooter',[10.7,-1.4,8.8],[1.1,1.2,.50],Math.PI/2,'electric');
 add('panel',[9.36,-.06,-6.33],[1.60,1.55,.14],Math.PI/2,'corridor');add('panel',[2.9,-.02,6.63],[3.15,1.8,.14],Math.PI,'corridor');
 add('door',[-.1,-.22,-4.16],[.87,2.36,.07],0,'entry');add('door',[9.48,-.20,-17.5],[.90,2.40,.07],Math.PI/2,'corridor');
 add('sign',[-.1,1.03,-4.10],[.32,.17,.025],0,'exit',{label:'EXIT'});add('sign',[-.65,1.02,10.98],[.32,.17,.025],Math.PI,'exit',{label:'EXIT'});
 add('sign',[.73,.15,-3.60],[.42,.62,.02],Math.PI/2,'bicycle',{photo:{frameId:'frame-4501',rect:[.075,.03,.31,.51]}});
 // Stair flight is fitted from recorded ascent poses; risers remain below the controller autostep.
 const z=11.65,run=.32,rise=.17;
 floor(6.35,7.75,z-.775,z+.775,'outdoor',-1.5);
 const flight=(start:number,bottom:number,n:number)=>{for(let i=0;i<n;i++)add('step',[start+(i+.5)*run,bottom+(i+1)*rise-.085,z],[run,.17,1.55],0,'outdoor');add('railing',[start,bottom,z+.82],[n*run,n*rise,1],0,'outdoor');};
 flight(7.75,-1.5,12);floor(11.59,12.5,z-.775,z+.775,'outdoor',.54);
 flight(12.5,.54,12);floor(16.34,17.3,z-.775,z+.775,'outdoor',2.58);
 flight(17.3,2.58,9);floor(20.18,21.5,z-.775,z+.775,'outdoor',4.11);
 for(const [x0,x1,y]of [[6.35,7.75,-1.5],[11.59,12.5,.54],[16.34,17.3,2.58],[20.18,21.5,4.11]])add('railing',[x0,y,z+.82],[x1-x0,0,1],0,'outdoor');
 add('railing',[-.9,-1.4,12.9],[7.25,0,1],0,'outdoor');
 wall(.52,10.84,21.5,10.84,7,'stone');
 for(let x=7.75;x<20.2;x+=.8){const y=x<11.59?-1.5+(x-7.75)*rise/run:x<12.5?.54:x<16.34?.54+(x-12.5)*rise/run:x<17.3?2.58:2.58+(x-17.3)*rise/run;wall(x,12.52,x+.8,12.52,1.0,'stone',y);}
 for(const x of [1.0,2.0,3.0,4.0,5.2])add('shrub',[x,-1.35,13.6],[1.05,.80,.9],0,'outdoor');
 for(const x of [7.2,8.6,10,11.4,12.8,14.2,15.6])add('shrub',[x,-1.5+Math.max(0,x-7.75)*.46,13.1],[1.45,2.7,1.05],0,'outdoor');
 return a;
}
