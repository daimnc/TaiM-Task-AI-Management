import test from 'node:test';
import assert from 'node:assert/strict';
import {seedV2, mockV2Request, MockHttpError} from '../js/api/mockData.js';

const ctx = {todayIso:'2026-11-16'};
const chat = (body, db=seedV2()) => mockV2Request(db,'POST','/ai/chat',body,ctx);

test('AI Assistant mock accepts the consent and bounded history contract', () => {
  const result = chat({message:'What should I work on first?',aiConsent:true,history:[{role:'user',text:'Help me plan'}]});
  assert.equal(typeof result.reply,'string');
  assert.equal(result.source,'mock-client');
  assert.equal(result.mock,true);
  assert.equal(result.aiGenerated,false);
});

test('AI Assistant mock defaults to no consent and validates history roles and bounds', () => {
  assert.equal(chat({message:'Hello'}).source,'mock-client');
  assert.throws(() => chat({message:'Hello',aiConsent:'yes'}), e => e instanceof MockHttpError && e.status===422);
  assert.throws(() => chat({message:'Hello',history:[{role:'system',text:'no'}]}), e => e instanceof MockHttpError && e.status===422);
  assert.throws(() => chat({message:'Hello',history:Array.from({length:7},()=>({role:'user',text:'x'}))}), e => e instanceof MockHttpError && e.status===422);
});
