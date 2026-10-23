'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { withRetry, updateDns } = require('../web/router_dns');

test('retry returns immediately on success', async () => {
  let calls = 0;
  const result = await withRetry(async () => { calls++; return {ok:true}; }, {attempts:3,delayMs:1});
  assert.equal(calls, 1);
  assert.deepEqual(result, {ok:true,attempts:1});
});

test('retry succeeds after transient failure', async () => {
  let calls = 0;
  const result = await withRetry(async () => {
    if (++calls < 3) throw new Error('temporary outage');
    return {ok:true};
  }, {attempts:3,delayMs:1});
  assert.equal(calls, 3);
  assert.equal(result.attempts, 3);
});

test('retry stops after configured attempts', async () => {
  let calls = 0;
  await assert.rejects(withRetry(async () => {
    calls++;
    throw new Error('offline');
  }, {attempts:2,delayMs:1}), /offline/);
  assert.equal(calls, 2);
});

test('invalid DNS is rejected before browser startup', async () => {
  await assert.rejects(updateDns({
    url:'https://192.168.0.1', password:'test',
    main:'not-an-ip', secondary:''
  }), /Invalid DNS IPv4/);
});

test('invalid router URL is rejected before browser startup', async () => {
  await assert.rejects(updateDns({
    url:'http://192.168.0.1', password:'test',
    main:'1.1.1.1', secondary:''
  }), /Invalid router URL/);
});
