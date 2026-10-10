import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {NodeIO, type Document} from '@gltf-transform/core';
import {ALL_EXTENSIONS,EXTMeshoptCompression,EXTTextureWebP} from '@gltf-transform/extensions';
import {MeshoptEncoder,MeshoptDecoder} from 'meshoptimizer';
import sharp from 'sharp';

export const DISPLAY_PROFILE = 'lossless-meshopt-webp84-3072-v1';
export function meshIO(){return new NodeIO().registerExtensions(ALL_EXTENSIONS).registerDependencies({'meshopt.encoder':MeshoptEncoder,'meshopt.decoder':MeshoptDecoder});}

/** Verify face identity, orientation, attributes and transforms before publishing.
 * Meshopt may rotate the three indices within a face; it must not reorder faces.
 */
export function verifyGeometry(before:Document,after:Document){
  const a=before.getRoot().listMeshes(),b=after.getRoot().listMeshes();
  if(a.length!==b.length)throw new Error('Mesh count changed during display compression');
  let triangles=0,vertices=0;
  for(let m=0;m<a.length;m++){
    const x=a[m].listPrimitives(),y=b[m].listPrimitives();
    if(x.length!==y.length)throw new Error('Primitive order changed');
    for(let p=0;p<x.length;p++){
      const original=x[p],output=y[p];
      if(original.getMode()!==output.getMode())throw new Error('Primitive mode changed');
      if(original.listSemantics().join()!==output.listSemantics().join())throw new Error('Attributes changed');
      for(const key of original.listSemantics()){
        const left=original.getAttribute(key)!,right=output.getAttribute(key)!;
        const l=left.getArray()!,r=right.getArray()!;
        if(left.getType()!==right.getType()||left.getNormalized()!==right.getNormalized()||l.constructor!==r.constructor||l.length!==r.length)throw new Error(`Attribute format changed: ${key}`);
        if(!Buffer.from(l.buffer,l.byteOffset,l.byteLength).equals(Buffer.from(r.buffer,r.byteOffset,r.byteLength)))throw new Error(`Attribute values changed: ${key}`);
      }
      const l=original.getIndices()?.getArray(),r=output.getIndices()?.getArray();
      if(!!l!==!!r||l?.length!==r?.length)throw new Error('Index count changed');
      if(l&&r)for(let f=0;f<l.length;f+=3){
        if(![0,1,2].some(offset=>l[f]===r[f+offset]&&l[f+1]===r[f+(offset+1)%3]&&l[f+2]===r[f+(offset+2)%3]))throw new Error(`Source face changed: ${m}/${p}/${f/3}`);
      }
      vertices+=original.getAttribute('POSITION')!.getCount();triangles+=(l?.length||original.getAttribute('POSITION')!.getCount())/3;
    }
  }
  const nodes=(d:Document)=>d.getRoot().listNodes().map(n=>({matrix:n.getMatrix(),mesh:d.getRoot().listMeshes().indexOf(n.getMesh()!),children:n.listChildren().map(c=>d.getRoot().listNodes().indexOf(c))}));
  if(JSON.stringify(nodes(before))!==JSON.stringify(nodes(after)))throw new Error('Scene transforms changed');
  return {triangles,vertices,sourceFaceOrderPreserved:true,attributesExact:true};
}

export async function optimizeDisplayGLB(input:string,output:string){
  await Promise.all([MeshoptEncoder.ready,MeshoptDecoder.ready]);
  const io=meshIO(),source=await io.read(input),doc=await io.read(input);
  const textureReport:{source:number[];output:number[];beforeBytes:number;afterBytes:number}[]=[];
  // Process sequentially to bound peak memory for multi-atlas scans.
  for(const texture of doc.getRoot().listTextures()){
    const image=texture.getImage();if(!image)continue;
    const metadata=await sharp(image).metadata();
    const {data,info}=await sharp(image).resize({width:3072,height:3072,fit:'inside',withoutEnlargement:true,kernel:'lanczos3'})
      .webp({quality:84,alphaQuality:100,effort:5,smartSubsample:true}).toBuffer({resolveWithObject:true});
    textureReport.push({source:[metadata.width||0,metadata.height||0],output:[info.width,info.height],beforeBytes:image.byteLength,afterBytes:data.length});
    texture.setImage(data).setMimeType('image/webp').setURI('');
  }
  if(textureReport.length)doc.createExtension(EXTTextureWebP).setRequired(true);
  // Intentionally omit weld/reorder/quantize/simplify: saved surface IDs rely on original faces.
  doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({method:EXTMeshoptCompression.EncoderMethod.QUANTIZE});
  const encoded=await io.writeBinary(doc),decoded=await io.readBinary(encoded);
  const geometry=verifyGeometry(source,decoded);
  const report={profile:DISPLAY_PROFILE,inputBytes:(await fs.stat(input)).size,outputBytes:encoded.length,...geometry,textures:textureReport,sha256:crypto.createHash('sha256').update(encoded).digest('hex')};
  await fs.mkdir(path.dirname(output),{recursive:true});
  const temporary=output+'.tmp';await fs.writeFile(temporary,encoded);await fs.rename(temporary,output);
  return report;
}
