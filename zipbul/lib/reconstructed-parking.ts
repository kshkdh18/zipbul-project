import * as T from 'three';
import {RoundedBoxGeometry} from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import {mergeGeometries} from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import {parkingLayout,parkingWorld,PARKING_YAW} from './parking-layout';
import type {RebuiltCollider} from './reconstructed-scene';
import type {SceneData,Vec3} from './types';
const mat=(color:number,roughness=.65,metalness=0)=>new T.MeshStandardMaterial({color,roughness,metalness});
function box(g:T.Group,size:Vec3,p:Vec3,m:T.Material,r=0){const o=new T.Mesh(r?new RoundedBoxGeometry(...size,1,r):new T.BoxGeometry(...size),m);o.position.set(...p);o.castShadow=o.receiveShadow=true;g.add(o);return o;}
function bar(g:T.Group,a:Vec3,b:Vec3,r:number,m:T.Material){const p=new T.Vector3(...a),q=new T.Vector3(...b),v=q.clone().sub(p),o=new T.Mesh(new T.CylinderGeometry(r,r,v.length(),8),m);o.position.copy(p.add(q).multiplyScalar(.5));o.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),v.normalize());o.castShadow=o.receiveShadow=true;g.add(o);return o;}
function ring(g:T.Group,r:number,t:number,p:Vec3,m:T.Material){const o=new T.Mesh(new T.TorusGeometry(r,t,8,40),m);o.position.set(...p);o.castShadow=true;g.add(o);return o;}
function surface(kind:'epoxy'|'stone'|'concrete'|'rubber'){
 const c=document.createElement('canvas');c.width=c.height=512;const ctx=c.getContext('2d')!,data=ctx.createImageData(512,512);let seed=93;const rand=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};const rgb=kind==='stone'?[147,151,148]:kind==='concrete'?[154,153,143]:kind==='rubber'?[46,49,46]:[202,205,192];
 for(let y=0;y<512;y++)for(let x=0;x<512;x++){const k=(y*512+x)*4,n=(rand()-.5)*(kind==='stone'?125:kind==='rubber'?27:12);for(let j=0;j<3;j++)data.data[k+j]=rgb[j]+n;data.data[k+3]=255;}ctx.putImageData(data,0,0);
 if(kind==='epoxy'){ctx.strokeStyle='rgba(104,108,99,.14)';ctx.lineWidth=1;ctx.strokeRect(.5,.5,511,511);for(let i=0;i<35;i++){const x=rand()*512,y=rand()*512;ctx.strokeStyle='rgba(100,107,97,.035)';ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x+rand()*50,y+rand()*5);ctx.stroke();}}
 const t=new T.CanvasTexture(c);t.colorSpace=T.SRGBColorSpace;t.wrapS=t.wrapT=T.RepeatWrapping;t.anisotropy=8;return t;
}
function merge(root:T.Group){root.updateMatrixWorld(true);const buckets=new Map<T.Material,T.BufferGeometry[]>(),old:T.BufferGeometry[]=[];root.traverse(o=>{if(!(o instanceof T.Mesh)||Array.isArray(o.material))return;old.push(o.geometry);let g=o.geometry.clone().applyMatrix4(o.matrixWorld);if(g.index)g=g.toNonIndexed();if(!g.attributes.uv)g.setAttribute('uv',new T.Float32BufferAttribute(new Float32Array(g.attributes.position.count*2),2));if(!g.attributes.normal)g.computeVertexNormals();if(!buckets.has(o.material))buckets.set(o.material,[]);buckets.get(o.material)!.push(g);});root.clear();root.rotation.set(0,0,0);for(const [m,gs]of buckets){const geo=mergeGeometries(gs,false);if(geo){geo.computeBoundingSphere();const mesh=new T.Mesh(geo,m);mesh.castShadow=!(m instanceof T.MeshBasicMaterial)&&!m.transparent;mesh.receiveShadow=true;root.add(mesh);}gs.forEach(g=>g.dispose());}old.forEach(g=>g.dispose());}
function decal(g:T.Group,w:number,h:number,text:string,color:string,p:Vec3,floor=false){const c=document.createElement('canvas');c.width=1024;c.height=256;const ctx=c.getContext('2d')!;ctx.fillStyle=color;ctx.font='700 152px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';ctx.fillText(text,512,128,990);const t=new T.CanvasTexture(c);t.colorSpace=T.SRGBColorSpace;const m=new T.MeshBasicMaterial({map:t,transparent:true,depthWrite:false,polygonOffset:true,polygonOffsetFactor:-2});const o=new T.Mesh(new T.PlaneGeometry(w,h),m);o.position.set(...p);if(floor)o.rotation.x=-Math.PI/2;g.add(o);}
export async function createParkingScene(source:SceneData){
 const records=parkingLayout(),group=new T.Group(),ceilingGroup=new T.Group(),colliders:RebuiltCollider[]=[];group.rotation.y=ceilingGroup.rotation.y=PARKING_YAW;
 const steel=mat(0x929a9d,.34,.77),frame=mat(0x4e575b,.45,.62),rubber=mat(0x191e21,.94),chrome=mat(0xb9c2c3,.23,.89),white=mat(0xd9dcd4,.81),trim=mat(0x454b49,.76),red=mat(0xae303e,.48),yellow=mat(0xe9b832,.8),green=mat(0x1c7457,.7),concrete=mat(0x999b94,.93),stone=mat(0xb0b3af,.88);stone.map=surface('stone');concrete.map=surface('concrete');const epoxy=mat(0xffffff,.30,.03);epoxy.map=surface('epoxy');const tread=mat(0xffffff,.96);tread.map=surface('rubber');
 const light=new T.MeshStandardMaterial({color:0xf5fff7,emissive:0xeaffed,emissiveIntensity:2.1});
 const colors=new Map<string,T.Material>();for(const [name,color]of Object.entries({silver:0xb7bec1,blue:0x25557d,black:0x252b2d,teal:0x234e46,cream:0xc8c3ad,cargo:0x292f2c}))colors.set(name,mat(color,.33,.55));
 const collider=(id:string,p:Vec3,half:Vec3,yaw=0,support=false)=>colliders.push({id,position:parkingWorld(p),half,yaw:yaw+PARKING_YAW,support});
 function wheel(g:T.Group,x:number,y:number,r:number,fat=false){ring(g,r-(fat?.035:.021),fat?.053:.023,[x,y,0],rubber);ring(g,r-.053,.011,[x,y,0],steel);bar(g,[x,y,-.085],[x,y,.085],.025,chrome);for(let i=0;i<(fat?12:20);i++){const angle=i*Math.PI*2/(fat?12:20);bar(g,[x,y,0],[x+Math.cos(angle)*(r-.055),y+Math.sin(angle)*(r-.055),0],fat?.008:.0024,steel);}ring(g,.07,.004,[x,y,.042],steel);}
 function bicycle(electric:boolean,color:string){const g=new T.Group(),body=colors.get(color)||frame,r=electric?.28:.34,rear:Vec3=[-.59,r,0],front:Vec3=[.59,r,0],bb:Vec3=[-.14,.30,0],seat:Vec3=[-.27,electric?.73:.81,0],head:Vec3=[.43,electric?.85:.88,0];wheel(g,rear[0],r,r,electric);wheel(g,front[0],r,r,electric);
  for(const [a,b]of [[rear,seat],[seat,bb],[bb,rear],[seat,head],[head,bb]] as [Vec3,Vec3][])bar(g,a,b,electric?.03:.019,body);
  for(const z of [-.052,.052]){bar(g,[head[0],head[1],z],[front[0],front[1],z],electric?.025:.014,body);bar(g,[rear[0],rear[1],z],[bb[0],bb[1],z],.011,body);}
  bar(g,seat,[-.28,electric?.84:.96,0],.014,chrome);box(g,electric?[.63,.095,.23]:[.27,.055,.18],electric?[-.35,.86,0]:[-.30,.96,0],rubber,.026);
  if(electric){box(g,[.34,.30,.12],[-.03,.51,0],body,.03);for(let i=0;i<8;i++)box(g,[.012,.008,.23],[-.59+i*.06,.912,0],trim);bar(g,[.42,.87,0],[.37,1.17,0],.026,body);bar(g,[.36,1.16,-.32],[.36,1.16,.32],.018,chrome);for(const z of [-.31,.31]){bar(g,[.34,1.16,z],[.24,1.17,z],.025,rubber);bar(g,[.34,1.15,z],[.31,1.43,z],.008,trim);const mirror=box(g,[.14,.068,.018],[.30,1.43,z],chrome,.018);mirror.rotation.y=z<0?.4:-.4;}const lamp=new T.Mesh(new T.SphereGeometry(.058,12,8),white);lamp.scale.x=.4;lamp.position.set(.55,.91,0);g.add(lamp);
   if(color==='cargo'){box(g,[.49,.45,.49],[.48,.76,0],colors.get('cargo')!,.025);box(g,[.51,.035,.51],[.48,1.00,0],trim,.01);for(const z of [-.22,.22])box(g,[.018,.43,.012],[.735,.76,z],rubber);}
  }else{bar(g,head,[.39,1.04,0],.017,chrome);bar(g,[.39,1.04,-.30],[.39,1.04,.30],.014,frame);for(const z of [-.27,.27])bar(g,[.39,1.04,z-.055],[.39,1.04,z+.055],.021,rubber);const cable=new T.CatmullRomCurve3([new T.Vector3(.4,1.04,.15),new T.Vector3(.60,.89,.13),new T.Vector3(.57,.55,.06)]);g.add(new T.Mesh(new T.TubeGeometry(cable,8,.004,4,false),rubber));}
  ring(g,.083,.008,[bb[0],bb[1],.08],chrome);bar(g,[bb[0],bb[1],.09],[bb[0]+.11,bb[1]-.06,.1],.009,chrome);box(g,[.095,.025,.085],[bb[0]+.12,bb[1]-.06,.14],rubber);bar(g,[-.54,r,.077],[bb[0],bb[1]+.08,.077],.005,trim);bar(g,[-.54,r,.077],[bb[0],bb[1]-.08,.077],.005,trim);bar(g,[-.15,.35,-.045],[-.31,.03,-.19],.009,steel);for(const x of [-.59,.59])box(g,[.03,.075,.012],[x+.15,r+.03,.024],yellow,.005);return g;
 }
 for(const r of records){const g=new T.Group();g.name=r.id;g.position.set(...r.position);g.rotation.y=r.yaw;g.userData={assetId:r.id,provenance:'video_glb_reconstruction',zone:r.zone};const [w,h,d]=r.size;
  if(r.kind==='floor'){
   const m=(r.zone==='outdoor'?stone:epoxy).clone();m.map=m.map!.clone();m.map.repeat.set(w/(r.zone==='outdoor'?.6:1.2),d/(r.zone==='outdoor'?.6:1.2));const p=new T.Mesh(new T.PlaneGeometry(w,d),m);p.rotation.x=-Math.PI/2;p.position.y=h/2;p.receiveShadow=true;g.add(p);collider(r.id,r.position,[w/2,h/2,d/2],r.yaw,true);
  }else if(r.kind==='wall'){
   let wm=r.zone==='louver'?trim:r.zone==='stone'?stone:white;if(r.zone==='stone'){wm=stone.clone();wm.map=stone.map!.clone();wm.map.repeat.set(Math.max(w,d)*2,h*2);}box(g,r.size,[0,0,0],wm);for(const z of [-d/2-.004,d/2+.004])box(g,[w,.11,.025],[0,-h/2+.055,z],trim);
   if(r.zone==='louver')for(let x=-w/2;x<w/2;x+=.052)for(const z of [-.08,.08])box(g,[.022,h,.07],[x,0,z],steel);
   if(r.zone==='stone'){for(let x=-w/2+.6;x<w/2;x+=.6)box(g,[.004,h,.001],[x,0,.061],trim);for(let y=-h/2+.45;y<h/2;y+=.45)box(g,[w,.004,.001],[0,y,.061],trim);}
   collider(r.id,r.position,[w/2,h/2,d/2],r.yaw);
  }else if(r.kind==='ceiling'){
   // The slab casts no directional shadow: overhead ambient and fixtures light the room.
   box(g,r.size,[0,0,0],concrete);if(r.zone!=='entry'&&r.zone!=='exit'){for(let z=-d/2+.3;z<d/2;z+=3.1)box(g,[w,.28,.25],[0,-.2,z],concrete);box(g,[.72,.28,d],[w*.20,-.50,0],steel);for(let z=-d/2;z<d/2;z+=.9)box(g,[.74,.29,.013],[w*.20,-.5,z],chrome);bar(g,[-w*.22,-.26,-d/2],[-w*.22,-.26,d/2],.045,frame);}
  }else if(r.kind==='light'){box(g,[w+.04,h+.03,d+.03],[0,0,0],frame);box(g,[w,.016,d],[0,-h/2-.012,0],light);for(const z of [-d*.3,d*.3])bar(g,[0,.025,z],[0,.43,z],.006,steel);
  }else if(r.kind==='glass'){
   box(g,r.size,[0,0,0],new T.MeshPhysicalMaterial({color:0xb4c8c1,roughness:.48,metalness:.1,transparent:true,opacity:.65}));box(g,[w,2.25,.012],[0,-.18,.061],mat(0xadbeb4,.7));for(const x of [-w/2,w/2])box(g,[.035,h,.09],[x,0,0],trim);box(g,[w,.43,.13],[0,-h/2+.215,0],frame);for(let y=-h/2+.04;y<-h/2+.41;y+=.034)box(g,[w,.014,.02],[0,y,.09],rubber);collider(r.id,r.position,[w/2,h/2,.07],r.yaw);
  }else if(r.kind==='rack'){
   const n=Math.round(d/.72),single=r.zone==='electric',height=single?1.52:1.48;
   for(let z=-d/2+.36;z<d/2;z+=1.44){box(g,[.10,height,.09],[0,height/2,z],frame);box(g,[.32,.018,.25],[0,.018,z],steel);for(const x of [-.105,.105])box(g,[.022,.014,.022],[x,.032,z],trim);}
   box(g,[.13,.14,d],[0,height,0],frame);
   for(let i=0;i<n;i++){const z=-d/2+.36+i*.72;const levels=single?[.045]:[.045,height+.13+(i%2)*.15];for(const y of levels){const upper=y>.5;box(g,[w,.024,.09],[.12,y,z],steel);for(const dz of [-.054,.054])box(g,[w,.05,.017],[.12,y+.02,z+dz],chrome);bar(g,[-w/2+.35,y,z-.10],[-w/2+.35,y+.38,z-.10],.007,steel);bar(g,[-w/2+.35,y+.38,z-.10],[-w/2+.35,y+.38,z+.10],.007,steel);bar(g,[-w/2+.35,y+.38,z+.10],[-w/2+.35,y,z+.10],.007,steel);if(upper){for(const dz of [-.065,.065])bar(g,[-.7,y+.02,z+dz],[w/2+.10,y+.45,z+dz],.012,chrome);bar(g,[w/2+.10,y+.45,z-.18],[w/2+.10,y+.45,z+.18],.025,red);box(g,[w,.16,.07],[.10,y-.11,z-.14],frame);}}
   }
   // Ground-level footprint excludes the adjacent camera-path aisles.
   collider(r.id,[r.position[0],r.position[1]+.90,r.position[2]],[w/2,.90,d/2],r.yaw);
   for(const x of single?[]:[-w/2-.13,w/2+.25])for(let i=0;i<n*2;i++)box(g,[.16,.004,.36],[x,.004,-d/2+.18+i*.36],i%2?rubber:yellow);
  }else if(r.kind==='bicycle'||r.kind==='electricBicycle'){g.add(bicycle(r.kind==='electricBicycle',r.label));collider(r.id,[r.position[0],r.position[1]+.55,r.position[2]],[w/2,.55,d/2],r.yaw);
  }else if(r.kind==='scooter'){box(g,[.68,.06,.17],[0,.14,0],rubber,.02);for(const x of [-.43,.43])wheel(g,x,.10,.10);bar(g,[.35,.15,0],[.25,1.15,0],.025,frame);bar(g,[.25,1.15,-.24],[.25,1.15,.24],.018,rubber);collider(r.id,[r.position[0],r.position[1]+.52,r.position[2]],[.48,.52,.23],r.yaw);
  }else if(r.kind==='panel'){
   box(g,r.size,[0,0,0],mat(0xc7c5b7,.6));const doors=Math.max(2,Math.round(w/.55));for(let i=0;i<doors;i++){const x=-w/2+(i+.5)*w/doors;box(g,[w/doors-.02,h-.04,.02],[x,0,d/2+.015],white);box(g,[.024,.11,.025],[x+w/doors*.30,-.05,d/2+.04],trim);box(g,[.075,.025,.008],[x,h*.31,d/2+.03],rubber);for(let j=0;j<3;j++)box(g,[.018,.025,.009],[x-.04+j*.04,.08,d/2+.04],j===0?red:j===1?green:rubber);}collider(r.id,r.position,[w/2,h/2,d/2],r.yaw);
  }else if(r.kind==='door'){box(g,r.size,[0,0,0],white);for(const x of [-w/2,w/2])box(g,[.04,h+.05,.09],[x,0,0],steel);bar(g,[w*.3,-.14,.06],[w*.12,-.14,.06],.014,chrome);collider(r.id,r.position,[w/2,h/2,d/2],r.yaw);
  }else if(r.kind==='sign'){if(r.label==='EXIT'){box(g,r.size,[0,0,0],green);decal(g,w*.9,h*.9,'EXIT','#efffef',[0,0,.02]);}else if(r.photo){const f=source.frames.find(f=>f.id===r.photo!.frameId);if(f){const texture=await new T.TextureLoader().loadAsync(f.url);texture.colorSpace=T.SRGBColorSpace;const geo=new T.PlaneGeometry(w,h),uv=geo.getAttribute('uv'),[x,y,rw,rh]=r.photo.rect;for(let i=0;i<uv.count;i++)uv.setXY(i,x+uv.getX(i)*rw,1-y-rh+uv.getY(i)*rh);g.add(new T.Mesh(geo,new T.MeshBasicMaterial({map:texture,side:T.DoubleSide})));}}
  }else if(r.kind==='step'){const sm=stone.clone();sm.map=stone.map!.clone();sm.map.repeat.set(2,2);box(g,r.size,[0,0,0],sm);box(g,[.027,.004,d-.025],[-w/2+.016,h/2+.003,0],steel);collider(r.id,r.position,[w/2,h/2,d/2],0,true);
  }else if(r.kind==='railing'){for(let x=0;x<=w;x+=1.15){const y=h*x/w;box(g,[.035,1.04,.035],[x,y+.52,0],steel);box(g,[.10,.016,.1],[x,y,0],steel);}for(const y of [.28,.62,1.05])bar(g,[0,y,0],[w,h+y,0],.018,chrome);collider(r.id,[r.position[0]+w/2,r.position[1]+h/2+.5,r.position[2]],[w/2,h/2+.55,.045]);
  }else if(r.kind==='shrub'){const leaf=mat(0x3d5a31,.95);box(g,[w,.25,d],[0,.125,0],stone);for(let i=0;i<32;i++){const angle=i*2.399,y=.3+(i%8)/8*(h-.25),o=new T.Mesh(new T.IcosahedronGeometry(1,1),leaf);o.scale.set(w*.24,h*.13,d*.30);o.position.set(Math.cos(angle)*w*.28,y,Math.sin(angle)*d*.28);o.castShadow=true;g.add(o);}collider(r.id,[r.position[0],r.position[1]+h/2,r.position[2]],[w/2,h/2,d/2]);}
  (r.kind==='ceiling'||r.kind==='light'?ceilingGroup:group).add(g);
 }
 // Observed green electric-cycle bay legend and yellow-black edge paint.
 const paint=new T.Group();paint.position.set(14.7,-1.393,7.15);decal(paint,6.6,.65,'전기자전거 전용','#18764c',[0,0,0],true);for(const x of [-4.35,4.15])box(paint,[.055,.004,2.6],[x,0,1.25],green);group.add(paint);
 merge(group);merge(ceilingGroup);ceilingGroup.traverse(o=>{if(o instanceof T.Mesh)o.castShadow=false;});group.add(ceilingGroup);group.visible=false;
 return {group,ceilingGroup,records,colliders};
}
