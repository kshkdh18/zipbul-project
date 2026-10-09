import * as THREE from 'three';

/** Spatial chunks retain every source triangle and its original primitive/face ID. */
export function partitionMesh(root:THREE.Object3D,cellSize=3){
  const meshes:THREE.Mesh[]=[];root.traverse(o=>{if(o instanceof THREE.Mesh)meshes.push(o);});
  meshes.forEach((source,primitive)=>{
    const geometry=source.geometry;if(!geometry.attributes.normal)geometry.computeVertexNormals();
    const p=geometry.getAttribute('position');if(!geometry.index)geometry.setIndex(Array.from({length:p.count},(_,i)=>i));const index=geometry.index!;
    const buckets=new Map<string,{indices:number[];faces:number[];box:THREE.Box3}>();
    const v=new THREE.Vector3();
    for(let face=0;face<index.count/3;face++){
      const a=index.getX(face*3),b=index.getX(face*3+1),c=index.getX(face*3+2);
      const key=[0,1,2].map(axis=>Math.floor((p.array[a*3+axis]+p.array[b*3+axis]+p.array[c*3+axis])/3/cellSize)).join(':');
      let group=buckets.get(key);if(!group){group={indices:[],faces:[],box:new THREE.Box3()};buckets.set(key,group);}
      group.indices.push(a,b,c);group.faces.push(face);
      for(const i of [a,b,c])group.box.expandByPoint(v.fromBufferAttribute(p,i));
    }
    const holder=new THREE.Group();holder.position.copy(source.position);holder.quaternion.copy(source.quaternion);holder.scale.copy(source.scale);holder.name=source.name;
    for(const [key,bucket]of buckets){const g=new THREE.BufferGeometry();for(const [name,a]of Object.entries(geometry.attributes))g.setAttribute(name,a);g.setIndex(bucket.indices);g.boundingBox=bucket.box;g.boundingSphere=bucket.box.getBoundingSphere(new THREE.Sphere());const m=new THREE.Mesh(g,source.material);m.name=`${source.name}/${key}`;m.userData={primitiveKey:`world/primitive-${primitive}`,sourceFaces:Uint32Array.from(bucket.faces)};holder.add(m);}
    source.parent?.add(holder);source.removeFromParent();
  });
}
