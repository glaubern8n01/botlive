import {test,expect,chromium} from 'playwright/test';
import {spawn,spawnSync} from 'node:child_process';
import {mkdtempSync,rmSync,mkdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join,resolve} from 'node:path';
const extensionPath=resolve(import.meta.dirname,'..');
const agentPath=resolve(extensionPath,'../local-agent');
const python=process.env.SHOP_LIVE_TEST_PYTHON||join(agentPath,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
test('extensão carregada integra simulador, worker, painel, WebSocket e agente',async()=>{
 const profile=mkdtempSync(join(tmpdir(),'shop-live-chrome-')); const database=join(profile,'e2e.db').replaceAll('\\','/'); const databaseUrl=`sqlite:///${database}`;
 const context=await chromium.launchPersistentContext(profile,{headless:false,executablePath:process.env.SHOP_LIVE_BROWSER_EXECUTABLE||undefined,args:['--window-position=-32000,-32000',`--disable-extensions-except=${extensionPath}`,`--load-extension=${extensionPath}`]});
 const extensionId='phbbbphbmomahkggbabhfcepgnhlajnj';
 const env={...process.env,SHOP_LIVE_DATABASE_URL:databaseUrl,SHOP_LIVE_AUTH_DISABLED:'true',SHOP_LIVE_ALLOWED_EXTENSION_IDS:extensionId};
 expect(spawnSync(python,['-m','alembic','upgrade','head'],{cwd:agentPath,env}).status).toBe(0);
 const agent=spawn(python,['-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8765'],{cwd:agentPath,env,stdio:'inherit'});
 try{
  await expect.poll(async()=>fetch('http://127.0.0.1:8765/shop-live/v1/health').then(r=>r.ok).catch(()=>false),{timeout:15000}).toBe(true);
  const post=(path,body)=>fetch(`http://127.0.0.1:8765${path}`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(body)}).then(r=>r.json());
  const a=await post('/shop-live/v1/products',{name:'Cafeteira autorizada',price:199}); const b=await post('/shop-live/v1/products',{name:'Próximo produto',price:49});
  await post('/shop-live/v1/scripts',{product_id:a.id,kind:'apresentacao',position:0,duration_seconds:45,text:'Apresente a cafeteira e confirme as informações aprovadas.'});
  const session=await post('/shop-live/v1/sessions',{title:'Sessão Playwright',estimated_minutes:30,seed:42,product_ids:[a.id,b.id]});
  const simulator=await context.newPage(); await simulator.goto('http://127.0.0.1:8765/shop-live/simulator-page');
  const panel=await context.newPage(); await panel.goto(`chrome-extension://${extensionId}/sidepanel.html`); await panel.fill('#token','token-e2e'); await panel.fill('#session',session.id); await panel.click('#auth button');
  await expect(panel.locator('#status')).toHaveText('pronto'); await panel.click('[data-command=start]');
  await expect(panel.locator('#product')).toHaveText('Cafeteira autorizada'); await expect(panel.locator('#next')).toContainText('Próximo produto'); await expect(panel.locator('#script')).toContainText('Apresente a cafeteira');
  await expect(panel.locator('#comments')).not.toHaveText('0'); await expect(panel.locator('#alert')).toContainText('simulado');
  mkdirSync(resolve(extensionPath,'test-results'),{recursive:true}); await panel.screenshot({path:resolve(extensionPath,'test-results/sidepanel-operando.png'),fullPage:true});
 }finally{agent.kill();await context.close();rmSync(profile,{recursive:true,force:true})}
});
