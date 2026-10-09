import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
const $ = id => document.getElementById(id);
const scene = new THREE.Scene(); scene.background = new THREE.Color('#0b1017');
const renderer = new THREE.WebGLRenderer({antialias:true,powerPreference:'high-performance'});
renderer.setPixelRatio(Math.min(devicePixelRatio,1.5));renderer.setSize(innerWidth,innerHeight);
renderer.outputColorSpace = THREE.SRGBColorSpace;renderer.toneMapping=THREE.NoToneMapping;
document.body.appendChild(renderer.domElement);
renderer.domElement.addEventListener("webglcontextlost",()=>{window.zipscanError="WebGL context lost";$("status").textContent="그래픽 메모리가 부족합니다. compact 프로필 결과를 사용해 주세요.";});
const camera=new THREE.PerspectiveCamera(48,innerWidth/innerHeight,.03,1000);
const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.12;
scene.add(new THREE.HemisphereLight(0xd6e8ff,0x515d73,2));const sun=new THREE.DirectionalLight(0xffffff,2);sun.position.set(15,25,10);scene.add(sun);
const gray=new THREE.MeshStandardMaterial({color:0x7693a3,roughness:1,metalness:0,side:THREE.DoubleSide,flatShading:true});
const ceilingPlane=new THREE.Plane(new THREE.Vector3(0,-1,0),100);
renderer.clippingPlanes=[ceilingPlane];
let root,box,center,radius,report,frames;
const setMode=mode=>{if(!root)return;root.traverse(item=>{if(item.isMesh)item.material=mode==='raw'?gray:item.userData.photographicMaterial;});$('raw').classList.toggle('active',mode==='raw');$('textured').classList.toggle('active',mode!=='raw');};
$('details-toggle').onclick=()=>$('details').classList.toggle('collapsed');if(innerWidth<900)$('details').classList.add('collapsed');
$('raw').onclick=()=>setMode('raw');$('textured').onclick=()=>setMode('textured');
function overview(){camera.up.set(0,1,0);camera.fov=48;camera.position.copy(center).add(new THREE.Vector3(radius*.95,radius*.85,radius*1.15));controls.target.copy(center);camera.updateProjectionMatrix();controls.update();}
$('reset').onclick=()=>{if(root)overview();};
$('top').onclick=()=>{if(!root)return;camera.up.set(0,0,-1);camera.position.copy(center).add(new THREE.Vector3(0,radius*1.65,.001));controls.target.copy(center);camera.fov=48;camera.updateProjectionMatrix();controls.update();};
function setClip(value){$('clip').value=value;ceilingPlane.constant=Number(value);}
$('clip').oninput=e=>setClip(e.target.value);
$('no-clip').onclick=()=>setClip(box.max.y+.1);
$('ceiling').onclick=()=>setClip(report.camera_height_median+.7);
function sourceView(index){$('frame').value=index;const frame=frames[index];const matrix=new THREE.Matrix4().set(...frame.camera_transform.flat());camera.position.setFromMatrixPosition(matrix);camera.up.set(0,1,0).transformDirection(matrix);const direction=new THREE.Vector3(0,0,-1).transformDirection(matrix);controls.target.copy(camera.position).addScaledVector(direction,2);camera.fov=THREE.MathUtils.radToDeg(2*Math.atan(frame.image_height/(2*frame.intrinsics[1][1])));camera.updateProjectionMatrix();controls.update();$('frame-label').textContent=`${index+1} / ${frames.length} · ${frame.video_pts.toFixed(1)}초`;}
$('frame').oninput=e=>sourceView(Number(e.target.value));
renderer.domElement.addEventListener('dblclick',event=>{if(!root)return;const pointer=new THREE.Vector2(event.clientX/innerWidth*2-1,1-event.clientY/innerHeight*2);const ray=new THREE.Raycaster();ray.setFromCamera(pointer,camera);const hit=ray.intersectObject(root,true).find(h=>h.point.y<=ceilingPlane.constant);if(hit){const direction=camera.position.clone().sub(controls.target).normalize();controls.target.copy(hit.point);camera.up.set(0,1,0);camera.position.copy(hit.point).addScaledVector(direction,2.5);controls.update();}});
try{
 [report,frames]=await Promise.all([fetch('report.json').then(r=>{if(!r.ok)throw Error('보고서를 읽을 수 없습니다.');return r.json();}),fetch('source-frames.json').then(r=>r.json())]);
 $('coverage').textContent=(report.coverage.area_fraction*100).toFixed(1)+'%';$('stats').innerHTML=`삼각형 ${report.mesh.faces.toLocaleString()}개<br>선택 사진 ${report.keyframes.selected}장<br>원본 좌표 · 미터 단위`;
 $('frame').max=frames.length-1;$('frame-label').textContent=`${frames.length}개 촬영 위치`;
 const gltf=await new GLTFLoader().loadAsync('textured.glb',event=>{$('load-progress').textContent=event.total?`${(event.loaded/event.total*100).toFixed(0)}% · 모델 불러오는 중`:`${(event.loaded/1048576).toFixed(0)} MB 불러오는 중`;});
 root=gltf.scene;root.traverse(item=>{if(item.isMesh){item.userData.photographicMaterial=item.material;item.frustumCulled=true;if(item.material.map){item.material.map.generateMipmaps=false;item.material.map.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());}}});scene.add(root);
 box=new THREE.Box3().setFromObject(root);center=box.getCenter(new THREE.Vector3());radius=box.getSize(new THREE.Vector3()).length()*.5;camera.far=Math.max(100,radius*15);controls.maxDistance=radius*5;controls.minDistance=.15;
 const grid=new THREE.GridHelper(Math.ceil(radius*2),Math.ceil(radius*2),0x334a60,0x1b2d3d);grid.position.set(center.x,box.min.y-.02,center.z);scene.add(grid);
 $('clip').min=box.min.y;$('clip').max=box.max.y+.1;setClip(box.max.y+.1);overview();$('loading').classList.add('hidden');$('status').textContent='불확실한 면은 회색 · 사진 텍스처';window.zipscanReady=true;
 window.zipscanViewer={setMode,overview,sourceView,setClip,renderer,scene,camera,report};
}catch(error){$('load-progress').textContent=error.message;$('status').textContent='불러오기 실패';window.zipscanError=error.stack;console.error(error);}
function animate(){requestAnimationFrame(animate);controls.update();renderer.render(scene,camera);}animate();
addEventListener('resize',()=>{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight);});
