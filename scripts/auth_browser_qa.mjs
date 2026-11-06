import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import { currentTotpStep, freshTotpStep } from './totp_qa_steps.mjs';
const {chromium,request,expect}=await import(pathToFileURL(process.env.QA_PLAYWRIGHT_PATH).href);
if(process.env.QA_ALLOW_TEST_WRITES!=='1') throw Error('Owned synthetic server required');
const base=new URL(process.env.QA_BASE_URL);
if(!['127.0.0.1','localhost'].includes(base.hostname)) throw Error('Loopback required');
const out=path.resolve(process.env.QA_OUTPUT); await fs.mkdir(out,{recursive:true});
function otp(secret,offset=0,step=currentTotpStep()){
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits=''; for(const char of secret.replace(/=/g,'')) bits+=alphabet.indexOf(char).toString(2).padStart(5,'0');
  const key=Buffer.from((bits.match(/.{8}/g)||[]).map(byte=>parseInt(byte,2)));
  const counter=Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(step+offset));
  const digest=createHmac('sha1',key).update(counter).digest(), pos=digest.at(-1)&15;
  return String((digest.readUInt32BE(pos)&0x7fffffff)%1000000).padStart(6,'0');
}
const api=await request.newContext({baseURL:base.origin});
const result={checks:[],pageErrors:[],cleanup:{twoFactorDisabled:false}};
let secret, headers, browser, context, failure;
let lastSubmittedStep=-1;
async function freshCode(){
  const step=await freshTotpStep(lastSubmittedStep);
  // Reserve before submitting: a UI assertion can fail after server success.
  lastSubmittedStep=step;
  return otp(secret,0,step);
}
async function factorEnabled(){
  const response=await api.get('/api/v1/auth/2fa/status',{headers});
  assert.equal(response.status(),200,'Owned factor status must be available');
  return (await response.json()).enabled;
}
try{
  const login=await api.post('/api/v1/auth/login',{data:{username:'owner',password:process.env.QA_PASSWORD}});
  assert.equal(login.status(),200);
  const token=(await login.json()).access_token;
  headers={Authorization:'Bearer '+token};
  const setup=await api.post('/api/v1/auth/2fa/setup',{headers,data:{}});
  assert.equal(setup.status(),200); secret=(await setup.json()).secret;
  assert.equal((await api.post('/api/v1/auth/2fa/verify',{headers,data:{code:await freshCode()}})).status(),200);
  assert.equal((await api.post('/api/v1/auth/2fa/setup',{headers,data:{}})).status(),409);
  browser=await chromium.launch({headless:true});
  context=await browser.newContext({locale:'de-DE',viewport:{width:1280,height:900}});
  await context.addInitScript(()=>localStorage.setItem('locale','de-DE'));
  const page=await context.newPage(); page.setDefaultTimeout(30000);
  page.on('pageerror',error=>result.pageErrors.push(String(error)));
  await page.goto(base.origin+'/login');
  await page.locator('#login-username').fill('owner');
  await page.locator('#login-password').fill(process.env.QA_PASSWORD);
  await page.getByRole('button',{name:'Anmelden',exact:true}).click();
  const code=page.getByLabel('Zwei-Faktor-Code',{exact:true});
  await expect(code).toBeVisible(); await expect(page.locator('#login-password')).toBeDisabled();
  result.checks.push('Password alone enters second-factor step');
  await page.screenshot({path:path.join(out,'2fa-required.png'),fullPage:true});
  // A code outside the accepted window is certain to be wrong unless it collides.
  let wrong=otp(secret,20);
  while([-1,0,1].some(offset=>otp(secret,offset)===wrong)) wrong=String((Number(wrong)+1)%1000000).padStart(6,'0');
  await code.fill(wrong); await page.getByRole('button',{name:'Anmelden',exact:true}).click();
  await expect(page.getByText('Ungültiger Zwei-Faktor-Code',{exact:true})).toBeVisible();
  await expect(code).toBeVisible(); result.checks.push('Wrong second factor rejected in real browser');
  const loginCode=await freshCode();
  await code.fill(loginCode);
  await page.getByRole('button',{name:'Anmelden',exact:true}).click();
  await expect(page).not.toHaveURL(/\/login/);
  result.checks.push('Correct fresh second factor opens authenticated application');
  if(process.env.QA_AUTH_FAIL_AFTER_LOGIN==='1') throw Error('Controlled QA UI failure after successful login');
  assert.equal((await api.post('/api/v1/auth/2fa/disable',{headers,data:{code:wrong}})).status(),400);
  assert.equal((await api.post('/api/v1/auth/2fa/disable',{headers,data:{code:loginCode}})).status(),400,
    'An already consumed login factor must not disable two-factor authentication');
  result.checks.push('Known consumed second factor is rejected across login and disable');
  assert.equal((await api.post('/api/v1/auth/2fa/disable',{headers,data:{code:await freshCode()}})).status(),200);
  assert.equal(await factorEnabled(),false);
  result.checks.push('Disable requires a fresh real second-factor step');
  assert.deepEqual(result.pageErrors,[]);
} catch(error){
  failure=error;
  result.failure=String(error);
  throw error;
} finally{
  let cleanupFailure;
  try{
    if(secret && headers){
      if(await factorEnabled()){
        assert.equal((await api.post('/api/v1/auth/2fa/disable',{headers,data:{code:await freshCode()}})).status(),200,
          'Owned fixture cleanup must disable two-factor authentication');
      }
      assert.equal(await factorEnabled(),false);
      result.cleanup.twoFactorDisabled=true;
    }
  } catch(error){
    cleanupFailure=error;
    result.cleanup.error=String(error);
  }
  await fs.writeFile(path.join(out,'results.json'),JSON.stringify(result,null,2));
  await context?.close(); await browser?.close(); await api.dispose();
  if(cleanupFailure && !failure) throw cleanupFailure;
}
console.log(JSON.stringify({passed:result.checks.length,errors:result.pageErrors.length,cleanup:result.cleanup}));
