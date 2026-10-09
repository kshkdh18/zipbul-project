import fs from 'node:fs';
import {createHash} from 'node:crypto';

async function input(){
  process.stdin.setRawMode?.(true);process.stdin.resume();process.stdout.write('Ready for hidden upload credentials on stdin.\n');
  return await new Promise((resolve,reject)=>{
    let text='';
    process.stdin.on('data',chunk=>{
      text+=chunk.toString();
      if(text.includes('\n')||text.includes('\r')){
        process.stdin.setRawMode?.(false);process.stdin.pause();
        try{resolve(JSON.parse(text.trim()));}catch{reject(new Error('Invalid upload configuration'));}
      }
    });
  });
}
const {url,token,bypass}=await input();
const manifest=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));const headers={'X-Zipbul-Upload':token,...(bypass?{'OAI-Sites-Authorization':`Bearer ${bypass}`}:{})};
async function request(route,body,raw=false){
  const response=await fetch(new URL(`/api/transfer/${route}`,url),{method:'POST',headers:{...headers,'Content-Type':raw?'application/octet-stream':'application/json'},body:raw?body:JSON.stringify(body),redirect:'error',signal:AbortSignal.timeout(120000)});
  if(!response.ok)throw new Error(`Upload ${response.status}: ${(await response.text()).slice(0,300)}`);return response.json();
}
async function hash(file){const digest=createHash('sha256');for await(const chunk of fs.createReadStream(file))digest.update(chunk);return digest.digest('hex');}
const chunkSize=8*1024*1024;
for(const asset of manifest.assets){
  const sha256=await hash(asset.file),begin=await request('begin',{...asset,file:undefined,sha256});
  if(begin.complete){console.log(`Already uploaded: ${asset.key}`);continue;}
  const fd=fs.openSync(asset.file,'r'),parts=[];
  try{for(let offset=0,part=1;offset<asset.size;offset+=chunkSize,part++){
    const bytes=Buffer.alloc(Math.min(chunkSize,asset.size-offset));fs.readSync(fd,bytes,0,bytes.length,offset);
    const route=`part?${new URLSearchParams({key:asset.key,uploadId:begin.uploadId,part:String(part)})}`;
    let uploaded;for(let attempt=0;attempt<3;attempt++){try{uploaded=await request(route,bytes,true);break;}catch(e){if(attempt===2)throw e;await new Promise(r=>setTimeout(r,1000*(attempt+1)));}}
    parts.push(uploaded);if(part%4===0||offset+bytes.length===asset.size)console.log(`Uploading ${asset.key}: ${Math.round((offset+bytes.length)/asset.size*100)}%`);
  }}finally{fs.closeSync(fd);}
  const done=await request('complete',{key:asset.key,uploadId:begin.uploadId,parts});if(done.size!==asset.size)throw new Error('Uploaded size mismatch');
}
console.log(JSON.stringify({seed:await request('seed',manifest.record)}));
