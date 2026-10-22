'use strict';
const { chromium } = require('playwright');
const net = require('node:net');

const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

async function setDnsField(locator, value) {
  if (await locator.inputValue() === value) return;
  await locator.fill('');
  if (value) await locator.fill(value);
  await locator.press('Tab');
  if (await locator.inputValue() !== value) throw new Error('DNS input mismatch');
}

async function waitReady(page) {
  await page.locator('[data-cy="priDnsInput"] input:visible').waitFor({state:'visible'});
  await page.locator('[data-cy="sndDnsInput"] input:visible').waitFor({state:'visible'});
  await page.locator('.page-loading-sd:visible').waitFor({state:'hidden',timeout:15000});
  await page.locator('.global-trans-mask:visible').waitFor({state:'hidden',timeout:15000});
}

async function updateDns({url, password, main, secondary = ''}) {
  if (net.isIP(main) !== 4 || (secondary && net.isIP(secondary) !== 4)) throw new Error('Invalid DNS IPv4');
  const target = new URL(url);
  if (target.protocol !== 'https:' || target.username || target.password || target.pathname !== '/' || target.search || target.hash) throw new Error('Invalid router URL');
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({ignoreHTTPSErrors:true});
    page.setDefaultTimeout(15000);
    await page.goto(target.origin, {waitUntil:'domcontentloaded'});
    await page.locator('input[type="password"]:visible').fill(password);
    await page.locator('#local-login-button').click();
    await page.waitForURL('**/#networkMap', {timeout:15000});
    const open = async () => {
      await page.evaluate(() => {window.location.hash='#dhcpServerAdv';});
      await waitReady(page);
    };
    await open();
    const primary = page.locator('[data-cy="priDnsInput"] input:visible');
    const secondaryInput = page.locator('[data-cy="sndDnsInput"] input:visible');
    const changed = (await primary.inputValue()) !== main || (await secondaryInput.inputValue()) !== secondary;
    if (changed) {
      await setDnsField(primary,main);
      await setDnsField(secondaryInput,secondary);
      await page.locator('#save-data').click();
      await waitReady(page);
      await sleep(1000);
    }
    await page.reload({waitUntil:'domcontentloaded'});
    await open();
    const actual = {main:await primary.inputValue(),secondary:await secondaryInput.inputValue()};
    if (actual.main !== main || actual.secondary !== secondary) throw new Error('DNS verification failed: '+JSON.stringify(actual));
    return {ok:true,changed,dns:actual};
  } finally {await browser.close();}
}

async function withRetry(fn, {attempts=3, delayMs=2000}={}) {
  for (let i=1;i<=attempts;i++) {
    try {return {...await fn(),attempts:i};}
    catch(error) {if(i===attempts) throw error; await sleep(delayMs*Math.pow(2,i-1));}
  }
}
module.exports={updateDns,withRetry};
