#!/usr/bin/env node
'use strict';
// Runs only inside the managed Web LXC. Credentials are read from a root-only file,
// never passed in command-line arguments.
const fs=require('node:fs');
const {updateDns,withRetry}=require('./router_dns');
const path='/etc/proxmox-power-manager/router.json';
async function main(){
 const mode=process.argv[2];
 if(!['test','normal','backup'].includes(mode))throw Error('Unsupported router operation');
 const c=JSON.parse(fs.readFileSync(path,'utf8'));
 if(!c.password)throw Error('Router password is not configured');
 if(mode!=='test'&&!c.enabled)throw Error('Router automation disabled');
 const prefix=mode==='backup'?'backup':'normal';
 const main=c[prefix+'_primary'],secondary=c[prefix+'_secondary']||'';
 if(!main)throw Error('Primary DNS is not configured');
 const result=await withRetry(()=>updateDns({url:c.url,password:c.password,main,secondary,verifyOnly:mode==='test'}),{attempts:mode==='test'?1:2});
 console.log(JSON.stringify({ok:true,mode,connected:true,changed:result.changed,dns:result.dns}));
}
main().catch(e=>{console.error('Router operation failed: '+e.message);process.exitCode=1});
