const fs = require('fs');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const {spawn} = require('child_process');
const out = process.argv[2];
const candidate = process.argv[3];
const chromePath = 'C:/Users/Administrator/AppData/Local/ms-playwright/chromium-1234/chrome-win64/chrome.exe';
const report = {startedAt:new Date().toISOString(),tool:'native Chromium CDP; fresh temporary profile',candidate,checks:[],errors:[],screenshots:[]};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
let child,ws,server;
const pending=new Map(); let sequence=0;
function check(name,passed,details){report.checks.push({name,passed,details});console.log(JSON.stringify({name,passed,details}));}
async function until(fn,timeout=10000){const deadline=Date.now()+timeout;let last;while(Date.now()<deadline){try{last=await fn();if(last)return last;}catch(e){last=e.message;}await pause(100);}throw new Error('wait timeout: '+JSON.stringify(last));}
function send(method,params={}){return new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(new Error(method+' timed out'));},10000);pending.set(id,{resolve:v=>{clearTimeout(timer);resolve(v);},reject:e=>{clearTimeout(timer);reject(e);}});ws.send(JSON.stringify({id,method,params}));});}
async function evaluate(expression){const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw new Error(JSON.stringify(r.exceptionDetails));return r.result.value;}
async function screenshot(name){const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});const filename=path.join(out,name);fs.writeFileSync(filename,Buffer.from(r.data,'base64'));report.screenshots.push(filename);}
async function click(selector){const p=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()`);if(!p)throw new Error('No control: '+selector);await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...p});await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...p});}
(async()=>{
 const profile=fs.mkdtempSync(path.join(require('os').tmpdir(),'daedalus-demo01-browser-'));
 child=spawn(chromePath,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'],{windowsHide:true,stdio:'ignore'});
 const active=path.join(profile,'DevToolsActivePort');await until(()=>fs.existsSync(active));
 const port=fs.readFileSync(active,'utf8').split(/\r?\n/)[0];
 const target=await (await fetch('http://127.0.0.1:'+port+'/json/new?about:blank',{method:'PUT'})).json();
 ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
 ws.onmessage=event=>{const msg=JSON.parse(event.data);if(msg.id){const p=pending.get(msg.id);if(p){pending.delete(msg.id);msg.error?p.reject(new Error(JSON.stringify(msg.error))):p.resolve(msg.result);}}else if(msg.method==='Runtime.exceptionThrown')report.errors.push(msg.params.exceptionDetails);};
 await send('Page.enable');await send('Runtime.enable');await send('Emulation.setDeviceMetricsOverride',{width:1280,height:800,deviceScaleFactor:1,mobile:false});
 const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.json':'application/json; charset=utf-8'};
 const root=path.resolve(candidate);server=http.createServer((req,res)=>{const requestPath=decodeURIComponent(req.url.split('?')[0]);const file=path.resolve(root,'.'+(requestPath==='/'?'/index.html':requestPath));if(!file.startsWith(root+path.sep)){res.writeHead(403);return res.end();}try{const bytes=fs.readFileSync(file);res.setHeader('Content-Type',mime[path.extname(file)]||'application/octet-stream');res.end(bytes);}catch{res.writeHead(404);res.end('Not found');}});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const url='http://127.0.0.1:'+server.address().port+'/';report.isolatedCandidateUrl=url;
 report.sourceHashes=Object.fromEntries(['index.html','app.js','styles.css','daedalus-candidate.json'].map(name=>[name,crypto.createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest('hex')]));
 await send('Page.navigate',{url});await until(()=>evaluate('document.readyState === "complete" && document.URL === '+JSON.stringify(url)));

 async function fill(selector,text){await click(selector);await send('Input.dispatchKeyEvent',{type:'keyDown',key:'a',code:'KeyA',windowsVirtualKeyCode:65,modifiers:2});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'a',code:'KeyA',windowsVirtualKeyCode:65});await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Backspace',code:'Backspace',windowsVirtualKeyCode:8});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Backspace',code:'Backspace',windowsVirtualKeyCode:8});if(text)await send('Input.insertText',{text});}
 async function enter(){await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',text:'\r',unmodifiedText:'\r',windowsVirtualKeyCode:13});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13});}
 async function reload(){const previous=await evaluate('performance.timeOrigin');await send('Page.reload');await until(()=>evaluate('document.readyState === "complete" && performance.timeOrigin !== '+previous));}
 async function items(){return evaluate('Array.from(document.querySelectorAll("#item-list li"),e=>({name:e.dataset.name,quantity:Number(e.dataset.quantity),completed:e.classList.contains("completed"),checked:e.querySelector("input[type=checkbox]").checked,text:e.querySelector(".item-text").textContent}))');}
 function digest(){const names=[];const skips=new Set(['.git','node_modules','dist','build','__pycache__','.venv','venv','.mypy_cache','.pytest_cache','.ruff_cache','target','.next','.nuxt','coverage','.tox','runs','.daedalus_worktrees','.idea','.vscode','vendor','site-packages']);function walk(dir){for(const e of fs.readdirSync(dir,{withFileTypes:true})){if(skips.has(e.name))continue;const p=path.join(dir,e.name);if(e.isDirectory())walk(p);else if(e.isFile())names.push(path.relative(root,p).split(path.sep).join('/'));else throw new Error('Unexpected source entry');}}walk(root);names.sort();const h=crypto.createHash('sha256');for(const name of names)h.update(Buffer.from(name+'\0','utf8')).update(crypto.createHash('sha256').update(fs.readFileSync(path.join(root,name))).digest());return {sha256:h.digest('hex'),files:names.length};}
 const beforeDigest=digest();report.sourceTreeBefore=beforeDigest;check('frozen_source_identity',beforeDigest.sha256==='2b4d1ecc57cf098f57ae15f32a508f73a6bb209925110849ccb4b214f425c8b4' && beforeDigest.files===8,beforeDigest);
 check('fresh_storage',await evaluate('localStorage.length === 0'),await evaluate('Object.keys(localStorage)'));
 check('initial_default_quantity_one',await evaluate('document.querySelector("#quantity-input").value === "1"'),await evaluate('document.querySelector("#quantity-input").value'));
 check('initial_list_empty',(await items()).length===0,await items());
 await fill('#item-input','CDP Test Apples');await fill('#quantity-input','3');await click('#add-item-btn');await until(async()=>((await items()).length===1));
 let current=await items();check('add_button_positive_integer',current[0].name==='CDP Test Apples' && current[0].quantity===3,current);
 check('default_one_after_add',await evaluate('document.querySelector("#quantity-input").value === "1"'),await evaluate('document.querySelector("#quantity-input").value'));
 await fill('#item-input','CDP Test Bread');await enter();await until(async()=>((await items()).length===2));current=await items();check('add_enter_default_one',current[1].name==='CDP Test Bread'&&current[1].quantity===1,current);
 for(const name of ['','   ']){await fill('#item-input',name);await fill('#quantity-input','1');await click('#add-item-btn');check('reject_'+(name?'whitespace_label':'blank_label'),(await items()).length===2 && await evaluate('!document.querySelector("#item-input").checkValidity()'),{items:await items(),message:await evaluate('document.querySelector("#item-input").validationMessage')});}
 for(const quantity of ['', '0', '-1', '1.5']){await fill('#item-input','CDP Invalid Quantity');await fill('#quantity-input',quantity);await click('#add-item-btn');check('reject_quantity_'+(quantity||'blank'),(await items()).length===2 && await evaluate('!document.querySelector("#quantity-input").checkValidity()'),{quantity,items:await items(),message:await evaluate('document.querySelector("#quantity-input").validationMessage')});}
 await fill('#item-input','CDP Test Oranges');await fill('#quantity-input','2');await click('#add-item-btn');await until(async()=>((await items()).length===3));check('recovery_after_invalid_input',(await items())[2].quantity===2,await items());
 await click('#item-list li:first-child input[type=checkbox]');current=await items();check('checkbox_marks_complete',current[0].completed&&current[0].checked,current);
 await click('#item-list li:first-child .item-text');current=await items();check('label_toggles_once',!current[0].completed&&!current[0].checked,current);
 await click('#item-list li:first-child input[type=checkbox]');current=await items();check('checkbox_marks_complete_again',current[0].completed&&current[0].checked,current);
 await click('#item-list li:nth-child(2) .delete-item');current=await items();check('delete_only_selected_item',current.length===2 && current[0].name==='CDP Test Apples' && current[0].completed && current[1].name==='CDP Test Oranges',current);
 await reload();current=await items();check('reload_persists_names_quantities_completion_and_deletion',current.length===2&&current[0].name==='CDP Test Apples'&&current[0].quantity===3&&current[0].completed&&current[0].checked&&current[1].name==='CDP Test Oranges'&&current[1].quantity===2&&!current[1].completed,current);
 await screenshot('accepted-desktop.png');
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:false});check('mobile_390_no_horizontal_overflow',await evaluate('document.documentElement.scrollWidth<=innerWidth'),await evaluate('({width:innerWidth,scrollWidth:document.documentElement.scrollWidth})'));await screenshot('accepted-mobile-390.png');
 await click('#clear-list-btn');current=await items();check('clear_list',current.length===0&&await evaluate('localStorage.getItem("shopping-list")==="[]"'),current);
 await reload();check('clear_list_persists_after_reload',(await items()).length===0&&await evaluate('localStorage.getItem("shopping-list")==="[]"'),await evaluate('localStorage.getItem("shopping-list")'));
 check('no_javascript_exceptions',report.errors.length===0,report.errors);
 const afterDigest=digest();report.sourceTreeAfter=afterDigest;check('source_unchanged',JSON.stringify(afterDigest)===JSON.stringify(beforeDigest),afterDigest);
 report.accepted=report.checks.every(c=>c.passed===true);report.packet='G1-IKARUS-KITCHEN-DEMO-01';report.classification='EXPERIMENT';report.original_candidate_recovered=false;
 if(!report.accepted)process.exitCode=1;

})().catch(e=>{report.accepted=false;report.fatalError=e.stack;console.error(e.stack);process.exitCode=1;}).finally(async()=>{
 report.finishedAt=new Date().toISOString();fs.writeFileSync(path.join(out,'browser-report.json'),JSON.stringify(report,null,2));
 if(ws){try{await send('Browser.close');}catch{}ws.close();}
 if(server)await new Promise(r=>server.close(r));
 if(child && child.exitCode===null)child.kill();
 console.log('REPORT='+path.join(out,'browser-report.json'));
});
