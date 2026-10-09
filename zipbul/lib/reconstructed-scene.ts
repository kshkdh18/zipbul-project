import {createParkingScene} from './reconstructed-parking';
import {PARKING_REVISION} from './parking-layout';
import * as T from 'three';
import {RoundedBoxGeometry} from 'three/examples/jsm/geometries/RoundedBoxGeometry.js';
import {mergeGeometries} from 'three/examples/jsm/utils/BufferGeometryUtils.js';
import {desk,chair,lectern} from './furniture';
import {BUILDING_YAW,fittedScene,localPoint,worldPoint,type BuiltAsset} from './scene-layout';
import type {SceneData,Vec3} from './types';
export interface RebuiltCollider {id:string;position:Vec3;half:Vec3;yaw:number;support:boolean}
function mat(color:number,roughness=.75,metalness=0){return new T.MeshStandardMaterial({color,roughness,metalness});}
function cube(g:T.Group,s:Vec3,p:Vec3,m:T.Material,r=.003){const mesh=new T.Mesh(r?new RoundedBoxGeometry(...s,1,r):new T.BoxGeometry(...s),m);mesh.position.set(...p);mesh.castShadow=mesh.receiveShadow=true;g.add(mesh);return mesh;}
function rod(g:T.Group,a:Vec3,b:Vec3,r:number,m:T.Material){const from=new T.Vector3(...a),to=new T.Vector3(...b),d=to.clone().sub(from);const mesh=new T.Mesh(new T.CylinderGeometry(r,r,d.length(),10),m);mesh.position.copy(from).add(to).multiplyScalar(.5);mesh.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),d.normalize());mesh.castShadow=mesh.receiveShadow=true;g.add(mesh);return mesh;}
function circle(g:T.Group,r:number,h:number,p:Vec3,m:T.Material){return rod(g,[p[0],p[1]-h/2,p[2]],[p[0],p[1]+h/2,p[2]],r,m);}
function noiseTexture(kind:'carpet'|'wood'|'ceiling'|'stone'){
 const canvas=document.createElement('canvas');canvas.width=canvas.height=512;const ctx=canvas.getContext('2d')!;let seed=42;const random=()=>{seed=(seed*1664525+1013904223)>>>0;return seed/4294967296;};
 const base=kind==='wood'?[181,160,124]:kind==='stone'?[214,210,201]:kind==='ceiling'?[225,223,213]:[148,144,136];
 const pixels=ctx.createImageData(512,512);for(let y=0;y<512;y++)for(let x=0;x<512;x++){const k=(y*512+x)*4;let n=(random()-.5)*(kind==='carpet'?34:kind==='wood'?10:8);if(kind==='wood')n+=Math.sin(x*.09+Math.sin(y*.008)*2)*6+Math.sin(x*.35)*3;if(kind==='carpet')n+=((x%3===0||y%3===0)?-6:2);for(let c=0;c<3;c++)pixels.data[k+c]=base[c]+n;pixels.data[k+3]=255;}ctx.putImageData(pixels,0,0);
 if(kind==='ceiling'){ctx.fillStyle='#62665f';for(let y=4;y<512;y+=14)for(let x=4;x<512;x+=14){ctx.beginPath();ctx.arc(x,y,1.8,0,Math.PI*2);ctx.fill();}}
 if(kind==='stone'){for(let n=0;n<2200;n++){const x=random()*512,y=random()*512;ctx.fillStyle=['#b7b1a8','#8b8983','#e8e5db','#9fa29b'][n%4];ctx.fillRect(x,y,random()*3+1,random()*5+1);}}
 const texture=new T.CanvasTexture(canvas);texture.colorSpace=T.SRGBColorSpace;texture.wrapS=texture.wrapT=T.RepeatWrapping;texture.anisotropy=8;return texture;
}
function photoRepeat(map:T.Texture,rect:[number,number,number,number],repeat:[number,number],color=0xffffff){
 const m=mat(color,1);m.map=map;const [x,y,w,h]=rect;
 m.onBeforeCompile=shader=>{shader.fragmentShader=shader.fragmentShader.replace('#include <map_fragment>',`#ifdef USE_MAP\nvec2 photoUv=vec2(${x.toFixed(6)},${(1-y-h).toFixed(6)})+abs(fract(vMapUv*vec2(${(repeat[0]*.5).toFixed(4)},${(repeat[1]*.5).toFixed(4)}))*2.0-1.0)*vec2(${w.toFixed(6)},${h.toFixed(6)});\nvec4 sampledDiffuseColor=texture2D(map,photoUv);diffuseColor*=sampledDiffuseColor;\n#endif`);};
 m.customProgramCacheKey=()=>`photo-${rect.join(',')}-${repeat.join(',')}`;return m;
}
function photoPanel(g:T.Group,width:number,height:number,texture:T.Texture,rect:[number,number,number,number],z=.002){const geo=new T.PlaneGeometry(width,height),uv=geo.getAttribute('uv');for(let i=0;i<uv.count;i++){uv.setXY(i,rect[0]+uv.getX(i)*rect[2],1-rect[1]-rect[3]+uv.getY(i)*rect[3]);}const panel=new T.Mesh(geo,new T.MeshBasicMaterial({map:texture,side:T.DoubleSide}));panel.position.z=z;g.add(panel);return panel;}
function wallClock(white:T.Material,dark:T.Material){const g=new T.Group();const rim=new T.Mesh(new T.CylinderGeometry(.17,.17,.034,48),dark);rim.rotation.x=Math.PI/2;g.add(rim);const face=new T.Mesh(new T.CircleGeometry(.162,48),white);face.position.z=.019;g.add(face);
 for(let i=0;i<12;i++){const t=i*Math.PI/6;const tick=cube(g,[.006,i%3===0?.025:.015,.004],[Math.sin(t)*.142,Math.cos(t)*.142,.023],dark,0);tick.rotation.z=-t;}rod(g,[0,0,.03],[-.014,.103,.03],.006,dark);rod(g,[0,0,.032],[.025,.071,.032],.008,dark);return g;}
function purifier(white:T.Material,metal:T.Material){const g=new T.Group();const body=new T.Mesh(new T.CylinderGeometry(.165,.16,.67,32),white);body.position.y=.355;body.castShadow=true;g.add(body);circle(g,.151,.015,[0,.70,0],metal);for(let n=0;n<12;n++){const ring=new T.Mesh(new T.TorusGeometry(.163,.0015,3,40),metal);ring.rotation.x=Math.PI/2;ring.position.y=.25+n*.028;g.add(ring);}return g;}
function cafeChair(yellow:T.Material){const g=new T.Group();cube(g,[.43,.036,.43],[0,.44,0],yellow,.035);const back=cube(g,[.43,.34,.028],[0,.64,.185],yellow,.045);back.rotation.x=-.1;for(const x of [-.18,.18])for(const z of [-.17,.17])rod(g,[x*1.12,.025,z*1.15],[x,.43,z],.014,yellow);return g;}
function plant(pot:T.Material,green:T.Material){const g=new T.Group();const container=new T.Mesh(new T.CylinderGeometry(.21,.16,.38,24),pot);container.position.y=.2;container.castShadow=true;g.add(container);circle(g,.195,.025,[0,.395,0],mat(0x423b2d));const stem=mat(0x64533a);for(let i=0;i<7;i++){const angle=i*2.399,end:[number,number,number]=[Math.cos(angle)*.20,.9+(i%3)*.14,Math.sin(angle)*.20];rod(g,[0,.36,0],end,.008,stem);for(let j=0;j<3;j++){const leaf=new T.Mesh(new T.SphereGeometry(1,10,6),green);leaf.scale.set(.065,.009,.19);leaf.position.set(end[0]+Math.cos(angle+j)*.10,end[1]-j*.13,end[2]+Math.sin(angle+j)*.10);leaf.rotation.set(.3,angle+j,.5);leaf.castShadow=true;g.add(leaf);}}return g;}
function cart(metal:T.Material,dark:T.Material){const g=new T.Group();for(const y of [.16,.52,.90]){cube(g,[.83,.032,.46],[0,y,0],metal);for(const z of [-.225,.225])cube(g,[.83,.04,.018],[0,y+.025,z],metal);}for(const x of [-.37,.37])for(const z of [-.19,.19]){rod(g,[x,.09,z],[x,.96,z],.022,metal);const w=circle(g,.056,.025,[x,.055,z],dark);w.rotation.z=Math.PI/2;}
 rod(g,[-.43,.93,-.19],[-.43,.93,.19],.022,metal);for(let i=0;i<4;i++)cube(g,[.15,.12,.20],[-.27+i*.17,.99,.03],mat(i%2?0xd8d4c9:0x969a91),.01);for(let i=0;i<3;i++)cube(g,[.20,.13,.28],[-.24+i*.24,.24,0],mat(i===1?0x9d7994:0xd6d5cb),.01);return g;}
function mergeStatic(root:T.Group){root.updateMatrixWorld(true);const groups=new Map<T.Material,T.BufferGeometry[]>();const meshes:T.Mesh[]=[];root.traverse(o=>{if(o instanceof T.Mesh&&o.material instanceof T.Material){meshes.push(o);const g=o.geometry.clone().applyMatrix4(o.matrixWorld);if(!g.attributes.normal)g.computeVertexNormals();if(!g.attributes.uv)g.setAttribute('uv',new T.BufferAttribute(new Float32Array(g.attributes.position.count*2),2));const geo=g;if(!groups.has(o.material))groups.set(o.material,[]);groups.get(o.material)!.push(geo.index?geo.toNonIndexed():geo);}});
 root.clear();root.position.set(0,0,0);root.rotation.set(0,0,0);root.scale.set(1,1,1);
 for(const [material,geometries]of groups){const geo=mergeGeometries(geometries,false);if(geo){geo.computeBoundingSphere();const mesh=new T.Mesh(geo,material);mesh.castShadow=!(material instanceof T.MeshBasicMaterial)&&!material.transparent;mesh.receiveShadow=true;root.add(mesh);}for(const g of geometries)g.dispose();}
 for(const m of meshes)m.geometry.dispose();
}
export async function createReconstructedScene(source:SceneData){
 if(source.assetRevision===PARKING_REVISION)return createParkingScene(source);
 const records=fittedScene(source.assetRevision),group=new T.Group(),ceilingGroup=new T.Group(),colliders:RebuiltCollider[]=[];group.name='영상과 GLB 기반 공간 재구성';if(!records.length)return {group,ceilingGroup,records,colliders};
 group.rotation.y=BUILDING_YAW;ceilingGroup.rotation.y=BUILDING_YAW;
 const textureLoader=new T.TextureLoader();const photos=new Map<string,T.Texture>();
 await Promise.all(['frame-2701','frame-6300','frame-5401','frame-7200','frame-4951','frame-901','frame-1801'].map(async id=>{const f=source.frames.find(f=>f.id===id);if(!f)return;const t=await textureLoader.loadAsync(f.url);t.colorSpace=T.SRGBColorSpace;t.anisotropy=8;photos.set(id,t);}));
 const white=mat(0xe6e4dc,.68),wall=mat(0xb2afa2,.94),trim=mat(0x757b7b,.5,.2),dark=mat(0x25272a,.72),black=mat(0x131619,.64),steel=mat(0x969c9d,.32,.65),yellow=mat(0xc1c733,.6),green=mat(0x50783a,.86),pot=mat(0xc9c6b7,.91);
 const carpet=new T.MeshStandardMaterial({map:noiseTexture('carpet'),roughness:1}),stone=new T.MeshStandardMaterial({map:noiseTexture('stone'),roughness:.78}),wood=new T.MeshStandardMaterial({map:noiseTexture('wood'),roughness:.7});
 const ceilingMat=new T.MeshStandardMaterial({map:noiseTexture('ceiling'),roughness:1}),blackCeiling=mat(0x292d2b,.98);
 const glass=new T.MeshPhysicalMaterial({color:0xc1d5d8,roughness:.15,metalness:.08,transparent:true,opacity:.20,side:T.DoubleSide});const frosted=new T.MeshPhysicalMaterial({color:0xc5d5d4,roughness:.7,metalness:0,transparent:true,opacity:.85,side:T.DoubleSide});
 const luminous=new T.MeshStandardMaterial({color:0xfff9e9,emissive:0xfff8e5,emissiveIntensity:2,roughness:.4});
 function collider(r:BuiltAsset,p:Vec3,half:Vec3,yaw=r.yaw,support=false){colliders.push({id:r.id,position:worldPoint(p),half,yaw:yaw+BUILDING_YAW,support});}
 for(const r of records){const g=new T.Group();g.position.set(...r.position);g.rotation.y=r.yaw;g.name=r.id;g.userData={assetId:r.id,provenance:'video_glb_reconstruction',zone:r.zone};const [w,h,d]=r.size;
 if(r.kind==='floor'){
   const isStone=r.zone==='lounge';let material:T.Material=(isStone?stone:carpet).clone();const photo=photos.get('frame-6300');if(photo)material=photoRepeat(photo,isStone?[.40,.38,.20,.28]:[.03,.83,.43,.15],[w*.85,d*.85],isStone?0xe8e5df:0xf2f3ee);
   const plane=new T.Mesh(new T.PlaneGeometry(w,d),material);plane.rotation.x=-Math.PI/2;plane.position.y=h/2;plane.receiveShadow=true;g.add(plane);collider(r,r.position,[w/2,h/2,d/2],0,true);
   if(!isStone)for(let u=-w/2+.5;u<w/2;u+=.5)cube(g,[.001,.0006,d],[u,h/2+.001,0],mat(0x6c6b65,.99),0);
 }else if(r.kind==='wall'){
   cube(g,r.size,[0,0,0],r.zone==='cafe'?wood:wall,0);const along=w>d;cube(g,along?[w,.065,.025]:[.025,.065,d],along?[0,-h/2+.035,d/2+.006]:[w/2+.006,-h/2+.035,0],trim,0);collider(r,r.position,[w/2,h/2,d/2]);
   if(r.zone==='classroom')for(let y=-h/2+.6;y<h/2;y+=.6)cube(g,along?[w,.002,.002]:[.002,.002,d],along?[0,y,d/2+.002]:[w/2+.002,y,0],mat(0x92938b),0);
 }else if(r.kind==='ceiling'){
   const m=(r.zone==='cafe'||r.zone==='lounge'?blackCeiling:ceilingMat).clone();if(m.map){m.map=m.map.clone();m.map.repeat.set(w/.6,d/.6);}cube(g,r.size,[0,0,0],m,0);
   if(r.zone==='lounge'||r.zone==='cafe'){for(let v=-d/2+.35;v<d/2;v+=1.1)cube(g,[w,.16,.12],[0,-.12,v],blackCeiling,0);}
 }else if(r.kind==='window'){
   cube(g,[.08,h,d],[0,0,0],glass,0);for(const z of [-d/2,d/2])cube(g,[.09,h,.045],[0,0,z],trim,0);for(const y of [-h/2,h/2])cube(g,[.20,.055,d],[0,y,0],trim,0);cube(g,[.08,.65,d-.06],[.025,h/2-.35,0],white,0);cube(g,[.22,.05,d],[.055,-h/2+.65,0],trim,0);cube(g,[.12,.62,d],[0,-h/2+.31,0],wall,0);
   // Photo-backed glazing uses the observed exterior strip without people.
   if(photos.has('frame-4951')){const pane=new T.Group();pane.rotation.y=Math.PI/2;pane.position.x=-.055;photoPanel(pane,d-.04,h-.72,photos.get('frame-4951')!,[.50,.04,.10,.26]);g.add(pane);}collider(r,r.position,[.05,h/2,d/2]);
 }else if(r.kind==='desk'){g.add(desk());collider(r,[r.position[0],r.position[1]+.38,r.position[2]],[.9,.38,.29]);
 }else if(r.kind==='chair'){g.add(chair());collider(r,[r.position[0],r.position[1]+.4,r.position[2]],[.24,.4,.24]);
 }else if(r.kind==='lectern'){g.add(lectern());collider(r,[r.position[0],r.position[1]+.56,r.position[2]],[.44,.56,.57]);
 }else if(r.kind==='whiteboard'){
   const board=new T.MeshPhysicalMaterial({color:0xe6eeec,roughness:.18,metalness:.03,clearcoat:1});cube(g,r.size,[0,0,0],board,.015);cube(g,[w+.012,.012,.048],[0,-h/2,0],steel,0);for(const x of [-w/2+.11,w/2-.11]){cube(g,[.12,.16,.025],[x,-h/2+.1,.04],dark);for(let i=0;i<3;i++)rod(g,[x-.03+i*.026,-h/2+.06,.055],[x-.03+i*.026,-h/2+.18,.055],.006,i===1?mat(0x50759a):black);}
 }else if(r.kind==='door'){cube(g,r.size,[0,0,0],dark);cube(g,[.075,2.5,.05],[0,0,-d/2],black,0);rod(g,[.05,-.20,d/2-.2],[.05,-.20,d/2-.08],.014,steel);collider(r,r.position,[w/2,h/2,d/2]);
 }else if(r.kind==='light'){cube(g,r.size,[0,0,0],luminous,0);cube(g,[w+.04,h+.015,d+.015],[0,.016,0],trim,0);
 }else if(r.kind==='projector'){cube(g,r.size,[0,0,0],white,.02);rod(g,[0,.09,0],[0,.43,0],.018,steel);const lens=circle(g,.045,.025,[.10,-.008,.174],black);lens.rotation.x=Math.PI/2;for(let i=0;i<8;i++)cube(g,[.09,.005,.002],[-.08,-.045+i*.012,.17],trim,0);
 }else if(r.kind==='clock')g.add(wallClock(white,black));
 else if(r.kind==='purifier'){g.add(purifier(white,trim));collider(r,[r.position[0],r.position[1]+.35,r.position[2]],[.17,.35,.17]);}
 else if(r.kind==='cart'){g.add(cart(trim,dark));collider(r,[r.position[0],r.position[1]+.49,r.position[2]],[w/2,.49,d/2]);}
 else if(r.kind==='counter'){
   for(const x of [-w/2+.07,w/2-.07])for(const z of [-d/2+.07,d/2-.07])cube(g,[.065,h-.06,.065],[x,(h-.06)/2,z],wood,.004);cube(g,[w+.06,.065,d+.07],[0,h-.03,0],white,.01);cube(g,[w,.30,.035],[0,.30,-d/2],dark,0);for(const x of [-w/2+.09,w/2-.09])for(let z=-d/2+.06;z<d/2;z+=.075)rod(g,[x,.16,z],[x,.86,z],.0035,dark);for(let i=0;i<5;i++){cube(g,[.40,.025,.32],[-w/2+.4+i*.38,h+.01,0],dark,.004);for(let j=0;j<3;j++)cube(g,[.35,.035,.27],[-w/2+.4+i*.38,h+.04+j*.045,0],mat(0x363b37,.28,.1),.005);}collider(r,[r.position[0],r.position[1]+h/2,r.position[2]],[w/2,h/2,d/2]);
 }else if(r.kind==='cabinet'){
   cube(g,r.size,[0,h/2,0],r.zone==='lounge'?white:wood,.003);if(r.zone==='lounge'){for(const y of [.78,1.35]){cube(g,[w-.12,.40,.03],[0,y,d/2+.015],dark,.012);cube(g,[w-.24,.29,.012],[-.04,y,d/2+.034],black,.008);rod(g,[w/2-.14,y-.13,d/2+.055],[w/2-.14,y+.13,d/2+.055],.013,steel);}}if(r.zone==='cafe'){cube(g,[w+.01,.007,d*.5],[.007,h*.60,0],trim,0);}else{for(const y of [.65,1.3])cube(g,[w,.01,d+.02],[0,y,0],trim,0);cube(g,[.008,h,d+.02],[0,h/2,0],trim,0);}collider(r,[r.position[0],r.position[1]+h/2,r.position[2]],[w/2,h/2,d/2]);
 }else if(r.kind==='coffeeStation'){cube(g,[w,h-.07,d],[0,(h-.07)/2,0],white);cube(g,[w+.04,.065,d+.04],[0,h-.03,0],wood);cube(g,[.47,.55,.36],[-.5,h+.275,0],dark,.025);cube(g,[.33,.19,.018],[-.5,h+.34,.192],black,.012);cube(g,[.36,.025,.18],[-.5,h+.07,.18],steel);rod(g,[-.58,h+.3,.20],[-.58,h+.20,.20],.012,steel);for(let i=0;i<4;i++)circle(g,.038,.10,[.1+i*.13,h+.055,.13],white);collider(r,[r.position[0],r.position[1]+h/2,r.position[2]],[w/2,h/2,d/2]);
 }else if(r.kind==='cafeTable'){
   cube(g,[w,.035,d],[0,.735,0],wood,.012);rod(g,[0,.05,0],[0,.72,0],.035,dark);for(const x of [-.24,.24])for(const z of [-.24,.24])rod(g,[0,.09,0],[x,.025,z],.02,dark);collider(r,[r.position[0],r.position[1]+.38,r.position[2]],[w/2,.38,d/2]);
 }else if(r.kind==='yellowChair'){g.add(cafeChair(yellow));collider(r,[r.position[0],r.position[1]+.4,r.position[2]],[.24,.4,.24]);}
 else if(r.kind==='stool'){cube(g,[.36,.045,.36],[0,.76,0],dark,.015);for(const x of [-.14,.14])for(const z of [-.14,.14])rod(g,[x*1.3,.03,z*1.3],[x,.74,z],.021,wood);for(const z of [-.16,.16])rod(g,[-.18,.30,z],[.18,.30,z],.014,wood);collider(r,[r.position[0],r.position[1]+.38,r.position[2]],[.2,.38,.2]);}
 else if(r.kind==='plant'){g.add(plant(pot,green));collider(r,[r.position[0],r.position[1]+.25,r.position[2]],[.22,.25,.22]);}
 else if(r.kind==='pendant'){
  const dome=new T.Mesh(new T.SphereGeometry(.20,24,12,0,Math.PI*2,0,Math.PI/2),new T.MeshStandardMaterial({color:0x665048,metalness:.68,roughness:.28,side:T.DoubleSide}));dome.castShadow=true;g.add(dome);circle(g,.17,.015,[0,.003,0],luminous);rod(g,[0,.2,0],[0,.95,0],.008,black);
 }else if(r.kind==='glass'){cube(g,r.size,[0,0,0],glass,0);cube(g,[w,1.35,d+.005],[0,-.05,0],frosted,0);for(let x=-w/2;x<w/2+.1;x+=1.3)cube(g,[.03,h,.06],[x,0,0],trim,0);collider(r,r.position,[w/2,h/2,d/2]);}
 else if(r.kind==='sign'){cube(g,[w+.08,h+.08,.055],[0,0,0],wood,0);if(r.photo&&photos.has(r.photo.frameId))photoPanel(g,w,h,photos.get(r.photo.frameId)!,r.photo.rect,.03);}
 (r.kind==='ceiling'?ceilingGroup:group).add(g);
 }
 // Photo-backed source evidence on its calibrated floor plane, not duplicated into decorative hazards.
 for(const hazard of source.hazards.slice(0,1)){const e=hazard.evidence[0],f=source.frames.find(f=>f.id===e.frameId),texture=photos.get(e.frameId);if(!f?.camera.length||!texture)continue;const [bx,y0,bw,h0]=e.bbox;const by=y0+h0*.30,bh=h0*.70;const geometry=new T.BufferGeometry(),pos:number[]=[],uv:number[]=[],ix:number[]=[];const n=14;let valid=true;
  for(let y=0;y<=n;y++)for(let x=0;x<=n;x++){const u=bx+bw*x/n,v=by+bh*y/n,local=[(u*f.width-f.intrinsics[0][2])/f.intrinsics[0][0],-(v*f.height-f.intrinsics[1][2])/f.intrinsics[1][1],-1];const dir=f.camera.slice(0,3).map(r=>r[0]*local[0]+r[1]*local[1]+r[2]*local[2]),origin=f.camera.slice(0,3).map(r=>r[3]),t=(-1.374-origin[1])/dir[1];if(t<=0||t>8){valid=false;break;}const p=localPoint(origin.map((a,i)=>a+dir[i]*t) as Vec3);pos.push(...p);uv.push(u,1-v);}
  if(!valid)continue;for(let y=0;y<n;y++)for(let x=0;x<n;x++){const i=y*(n+1)+x;ix.push(i,i+n+1,i+1,i+1,i+n+1,i+n+2);}geometry.setAttribute('position',new T.Float32BufferAttribute(pos,3));geometry.setAttribute('uv',new T.Float32BufferAttribute(uv,2));geometry.setIndex(ix);geometry.computeVertexNormals();const m=new T.MeshBasicMaterial({map:texture,side:T.DoubleSide,polygonOffset:true,polygonOffsetFactor:-2,polygonOffsetUnits:-2});const patch=new T.Mesh(geometry,m);patch.name=`photo-evidence-${e.id}`;group.add(patch);
 }
 mergeStatic(group);mergeStatic(ceilingGroup);group.add(ceilingGroup);group.visible=false;return {group,ceilingGroup,records,colliders};
}
