const {spawn}=require('child_process');
const fs=require('fs');
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
(async()=>{
  const proc=spawn('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',['--headless=new','--disable-gpu','--no-sandbox','--remote-debugging-port=9395','--user-data-dir='+require('os').tmpdir()+'\kpl-edge-legacy2','--window-size=1440,1800','about:blank'],{stdio:'ignore'});
  let t=null;
  for(let i=0;i<60;i++){await sleep(250);try{const l=await(await fetch('http://127.0.0.1:9395/json/list')).json();t=l.find(x=>x.type==='page'&&x.webSocketDebuggerUrl);if(t)break;}catch(e){}}
  const ws=new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
  let id=0;const p=new Map();const errs=[];
  ws.onmessage=e=>{const m=JSON.parse(e.data);
    if(m.method==='Runtime.exceptionThrown'){const d=m.params.exceptionDetails;errs.push((d.exception&&d.exception.description||d.text).split('\n')[0]);}
    if(m.id&&p.has(m.id)){p.get(m.id)(m);p.delete(m.id);}};
  const send=(me,pa)=>new Promise(r=>{const i2=++id;p.set(i2,r);ws.send(JSON.stringify({id:i2,method:me,params:pa}));});
  const ev=async(x)=>{const r=await send('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true});return r.result?r.result.result:undefined;};
  await send('Page.enable');await send('Runtime.enable');
  await send('Network.enable');await send('Network.setCacheDisabled',{cacheDisabled:true});
  await send('Page.navigate',{url:'http://127.0.0.1:8123/schedule.html?theme=dark'});
  await sleep(5500);
  const years=await ev('(function(){var y=document.querySelectorAll("select option"); var arr=[]; y.forEach(function(o){var t=o.textContent.trim(); if(/年/.test(t)) arr.push(t);}); return arr.slice(0,14);})()');
  console.log('年份选项:', JSON.stringify(years));
  const n=await ev('(function(){var h=document.querySelector(".page-hero p"); return h?h.textContent.slice(0,40):"";})()');
  console.log('hero:', n);
  await send('Page.navigate',{url:'http://127.0.0.1:8123/match.html?id=wp_26177&theme=dark'});
  await sleep(4500);
  const m=await ev('(function(){return { head:(document.querySelector(".mh-score")||{textContent:"N/A"}).textContent.slice(0,26), teams:(document.querySelector(".mh-grid")||{textContent:""}).textContent.slice(0,40) };})()');
  console.log('legacy match:', JSON.stringify(m));
  const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,clip:{x:0,y:0,width:1440,height:760,scale:1}});
  fs.writeFileSync('_shot_legacy.png',Buffer.from(shot.result.data,'base64'));
  console.log('errors:', errs.length?errs.join(' || '):'none');
  proc.kill();
})().catch(e=>{console.error(e);process.exit(1);});
