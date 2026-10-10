import test from 'node:test';
import assert from 'node:assert/strict';
import {translate,DEFAULT_LOCALE} from '../lib/locale';
import {guideSteps,readGuideState} from '../lib/onboarding';
test('English is default and Korean source observations remain available verbatim',()=>{
  assert.equal(DEFAULT_LOCALE,'en');
  assert.equal(translate('현장 추가'),'Import site');
  const source='자전거 받침대의 낮은 돌출부 확인';
  assert.equal(translate(source),'Check the bicycle stand\'s low protrusion');assert.equal(translate(source,'ko'),source);
  assert.equal(translate('대상 · {0}','en','위치 연결됨'),'Object · Location linked');
  assert.equal(translate('근거 검증 12/41 프레임'),'Checking evidence 12/41 frames');
  assert.equal(translate('Untranslated user content'),'Untranslated user content');
});
test('guide progress accepts known steps only and tolerates invalid local storage',()=>{
  assert.deepEqual(readGuideState('broken'),{checked:[],dismissed:false});
  assert.deepEqual(readGuideState('{"checked":["site","malicious",3],"dismissed":true}'),{checked:['site'],dismissed:true});
  assert.equal(new Set(guideSteps.map(s=>s.id)).size,guideSteps.length);
});
