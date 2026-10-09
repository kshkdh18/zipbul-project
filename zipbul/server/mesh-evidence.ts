import {NodeIO} from '@gltf-transform/core';
import {ALL_EXTENSIONS} from '@gltf-transform/extensions';
import * as T from 'three';
import type {Anchor,Box,Frame,Vec3} from '../lib/types';
import {local} from './store';
const cached=new Map<string,Promise<T.Group>>();
async function meshFor(id:string){const s=local(id),key=`${id}:${s.assetRevision}`;if(!cached.has(key))cached.set(key,(async()=>{const doc=await new NodeIO().registerExtensions(ALL_EXTENSIONS).read(s.files.collision),group=new T.Group(),material=new T.MeshBasicMaterial({side:T.DoubleSide});for(const node of doc.getRoot().listNodes()){const mesh=node.getMesh();if(!mesh)continue;for(const p of mesh.listPrimitives()){const positions=p.getAttribute('POSITION');if(!positions)continue;const geometry=new T.BufferGeometry();geometry.setAttribute('position',new T.Float32BufferAttribute(positions.getArray()!,3));const indices=p.getIndices();if(indices)geometry.setIndex(new T.Uint32BufferAttribute(indices.getArray()!,1));geometry.applyMatrix4(new T.Matrix4().fromArray(node.getWorldMatrix()));geometry.computeBoundingBox();geometry.computeBoundingSphere();const o=new T.Mesh(geometry,material);o.name=node.getName()||`scan-${group.children.length}`;group.add(o);}}group.updateMatrixWorld(true);return group;})());return cached.get(key)!;}
/** Match the observed image ray to the actual GLB-derived surface. This is still a
 * proposed anchor; a hit does not confirm the object identity or any safety claim. */
export async function groundEvidence(id:string,frame:Frame,bbox:Box,depth?:Anchor):Promise<Anchor|undefined>{
 if(frame.camera.length!==4||!frame.intrinsics.length)return depth;
 const s=local(id),origin=new T.Vector3(...frame.camera.slice(0,3).map(r=>r[3]) as Vec3),u=(bbox[0]+bbox[2]/2)*frame.width,v=(bbox[1]+bbox[3]/2)*frame.height;
 const ray=[(u-frame.intrinsics[0][2])/frame.intrinsics[0][0],-(v-frame.intrinsics[1][2])/frame.intrinsics[1][1],-1];const dir=new T.Vector3(...frame.camera.slice(0,3).map(r=>r[0]*ray[0]+r[1]*ray[1]+r[2]*ray[2]) as Vec3).normalize();
 const hits=new T.Raycaster(origin,dir,.15,12).intersectObject(await meshFor(id),true);const expected=depth?new T.Vector3(...depth.position).distanceTo(origin):undefined;
 const hit=expected===undefined?hits[0]:hits.sort((a,b)=>Math.abs(a.distance-expected)-Math.abs(b.distance-expected))[0];
 if(!hit||expected!==undefined&&Math.abs(hit.distance-expected)>.45)return depth;
 const point=hit.point.toArray() as Vec3;return {position:point,cameraPosition:origin.toArray() as Vec3,cameraTarget:point,status:'proposed',method:depth?'depth':'mesh',assetRevision:s.assetRevision,surface:{mesh:hit.object.name,face:hit.faceIndex??-1,normal:(hit.face?.normal.toArray()||[0,1,0]) as Vec3}};
}
