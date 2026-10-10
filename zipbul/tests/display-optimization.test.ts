import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {Document} from '@gltf-transform/core';
import sharp from 'sharp';
import {meshIO,optimizeDisplayGLB,verifyGeometry} from '../server/optimize-glb';

test('display compression preserves face IDs, exact geometry, transforms and alpha textures',async()=>{
  const dir=await fs.mkdtemp(path.join(os.tmpdir(),'zipbul-display-'));
  try{
    const doc=new Document(),buffer=doc.createBuffer();
    const positions=doc.createAccessor().setType('VEC3').setArray(new Float32Array([0,0,0,1,0,0,0,1,0,1,1,0])).setBuffer(buffer);
    const indices=doc.createAccessor().setType('SCALAR').setArray(new Uint16Array([0,1,2,2,1,3])).setBuffer(buffer);
    const image=await sharp({create:{width:64,height:64,channels:4,background:{r:120,g:80,b:30,alpha:.5}}}).png().toBuffer();
    const texture=doc.createTexture().setImage(image).setMimeType('image/png');
    const material=doc.createMaterial().setBaseColorTexture(texture).setAlphaMode('BLEND');
    const mesh=doc.createMesh().addPrimitive(doc.createPrimitive().setAttribute('POSITION',positions).setIndices(indices).setMaterial(material));
    const node=doc.createNode().setMesh(mesh).setTranslation([2,3,4]);doc.createScene().addChild(node);
    const io=meshIO(),input=path.join(dir,'input.glb'),output=path.join(dir,'output.glb');await io.write(input,doc);
    const original=await fs.readFile(input);const report=await optimizeDisplayGLB(input,output);
    assert.equal(report.triangles,2);assert.equal(report.attributesExact,true);assert.deepEqual(await fs.readFile(input),original);
    const decoded=await io.read(output);assert.deepEqual(verifyGeometry(doc,decoded),{triangles:2,vertices:4,sourceFaceOrderPreserved:true,attributesExact:true});
    const metadata=await sharp(decoded.getRoot().listTextures()[0].getImage()!).metadata();assert.equal(metadata.format,'webp');assert.equal(metadata.hasAlpha,true);
    const changed=decoded.getRoot().listMeshes()[0].listPrimitives()[0].getAttribute('POSITION')!;changed.setArray(new Float32Array([.01,0,0,1,0,0,0,1,0,1,1,0]));
    assert.throws(()=>verifyGeometry(doc,decoded),/Attribute values changed/);
  }finally{await fs.rm(dir,{recursive:true,force:true});}
});
