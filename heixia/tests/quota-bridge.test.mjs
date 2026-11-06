/** Public registry integration and normalized quota rendering, using synthetic data only. */
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { test } from 'node:test';
import { apply } from '../src/model-quota-bridge.js';
const upstream = existsSync(new URL('../../dsh-pet/src/', import.meta.url))
  ? new URL('../../dsh-pet/src/', import.meta.url) : new URL('../../src/', import.meta.url);
const { toBalanceState } = await import(new URL('shared/balance/parse.ts', upstream));
const { queryBalance, listBalanceProviders, registerBalanceProvider } = await import(new URL('host/balance/index.ts', upstream));

const builtins = ['opencode-go', 'commandcode', 'deepseek-official', 'deepseek-account'];
const money = (value, unit = 'CNY', label = 'balance') => ({ label, value, unit });
const quota = (value, label = 'weekly') => ({ label, value: String(value), unit: '%', remainingPercent: value });
const ready = (metrics, extra = {}) => ({ provider: 'qwen', name: '测试套餐', status: 'ready', metrics, ...extra });
const snapshot = row => ({ providers: [row], checkedAt: '2026-11-07T00:00:00.000Z' });

function fixture(t, response, config, options = {}) {
  const registered = new Map(); const cleanups = []; const calls = [];
  let currentService = typeof response === 'function' ? { snapshot: response } : { snapshot: async () => response };
  const api = options.api ?? { balance: {
    list: () => ({ builtin: builtins, external: ['already-owned'] }),
    register(def) { assert.ok(!registered.has(def.id)); registered.set(def.id, def); return () => registered.delete(def.id); },
  } };
  const ctx = { petApi7340: api,
    llm: { listProviders: () => [...builtins, 'already-owned', 'qwen', 'other', 'qwen'].map(id => ({ id })) },
    get(name, required) { calls.push([name, required]); assert.equal(name, 'modelQuota'); assert.equal(required, false); return currentService; },
    effect(setup) { const cleanup = setup(); if (typeof cleanup === 'function') cleanups.push(cleanup); },
  };
  Object.defineProperty(ctx, 'credentials', { get() { throw new Error('Bridge must never read credentials'); } });
  apply(ctx, config);
  let disposed = false;
  async function dispose() { if (disposed) return; disposed = true; await Promise.all(cleanups.reverse().map(fn => fn())); }
  t.after(dispose);
  return { registered, calls, dispose, setService: value => { currentService = value; },
    run: provider => registered.get(provider ?? 'qwen').fetch({ provider: provider ?? 'qwen' }) };
}

function textOf(node) { return [node.text ?? '', ...(node.children ?? []).map(textOf)].join('\n'); }

test('registers current non-builtin providers without replacing upstream or other plugins', t => {
  const h = fixture(t, snapshot(ready([money('12.00')])));
  assert.deepEqual([...h.registered.keys()], ['qwen', 'other']);
  assert.deepEqual(h.calls, [], 'registration itself does not query quotas');
});

test('missing optional service stays unsupported and a later service becomes usable', async t => {
  const h = fixture(t, undefined);
  h.setService(undefined);
  const unavailable = await h.run();
  assert.equal(unavailable.reason, 'unsupported');
  h.setService({ snapshot: async () => snapshot(ready([money('0.00')])) });
  const available = await h.run();
  assert.equal(available.ok, true);
  assert.match(textOf(available.data.rows), /0\.00 CNY/);
  assert.deepEqual(h.calls, [['modelQuota', false], ['modelQuota', false]]);
});

test('matches the exact current provider and never substitutes another account', async t => {
  const h = fixture(t, snapshot(ready([money('999')], { provider: 'other' })));
  const result = await h.run();
  assert.equal(result.ok, false); assert.equal(result.reason, 'unsupported');
  assert.ok(!JSON.stringify(result).includes('999'));
});

test('ambiguous duplicate account rows fail instead of being summed', async t => {
  const h = fixture(t, { providers: [ready([money('10')]), ready([money('20')])] });
  const result = await h.run();
  assert.equal(result.reason, 'fetch-error');
  assert.ok(!JSON.stringify(result).includes('30 CNY'));
});

test('preserves CNY/USD and shared key metrics separately with original decimal precision', async t => {
  const h = fixture(t, snapshot(ready([money('12.3400'), money('5.67', 'USD'), money('2.10', 'USD', 'usage')])));
  const result = await h.run();
  assert.equal(result.shape, 'custom');
  const body = textOf(result.data.rows);
  assert.match(body, /12\.3400 CNY/); assert.match(body, /5\.67 USD/); assert.match(body, /Key已用金额/);
  assert.ok(!body.includes('18.01')); assert.equal(result.data.percent, undefined);
  const rendered = toBalanceState(result);
  assert.equal(rendered?.ok, true); assert.equal(rendered?.shape, 'custom');
  assert.match(textOf(rendered.custom.views[0]), /12\.3400 CNY/);
});

test('multiple real remaining windows and reset times are not converted to money or one inferred percentage', async t => {
  const h = fixture(t, snapshot(ready([quota(80, 'fiveHour'), { ...quota(40, 'weekly'), resetAt: '2026-11-08T00:00:00Z' }])));
  const result = await h.run(); const body = textOf(result.data.rows);
  assert.match(body, /5小时剩余/); assert.match(body, /80 %/); assert.match(body, /40 %/);
  assert.match(body, /2026-11-08T00:00:00\.000Z/); assert.equal(result.data.percent, undefined);
  assert.ok(!body.includes('CNY'));
});

test('Token Plan window labels retain the source console-account limitation', async t => {
  const h = fixture(t, snapshot(ready([{ ...quota(65, 'rolling'), periodCount: 5, periodUnit: 'Hour' }], { note: 'consoleAccountQuota' })));
  const result = await h.run(); const body = textOf(result.data.rows);
  assert.match(body, /5小时窗口剩余/); assert.match(body, /已登录控制台账户/);
});

for (const [row, reason] of [
  [{ status: 'unsupported' }, 'unsupported'], [{ status: 'noQuota' }, 'unsupported'],
  [{ status: 'missingCredential' }, 'credential-missing'],
  [{ status: 'setupRequired', reason: 'consoleLoginRequired' }, 'credential-missing'],
  [{ status: 'setupRequired', reason: 'cliMissing' }, 'unsupported'],
  [{ status: 'failed', reason: 'timeout', metrics: [money('999')] }, 'fetch-error'],
]) {
  test(`source status ${row.status}/${row.reason ?? ''} is explicit and never displays stale numbers`, async t => {
    const h = fixture(t, snapshot({ provider: 'qwen', ...row })); const result = await h.run();
    assert.equal(result.ok, false); assert.equal(result.reason, reason);
    assert.ok(!JSON.stringify(result).includes('999')); assert.equal(toBalanceState(result)?.ok, false);
  });
}

test('usage-only, missing money and token counts are not reported as remaining balance', async t => {
  for (const metrics of [[money('10', 'USD', 'usage')], [], [{ label: 'tokens', value: '10000', unit: 'tokens' }], [money('', 'CNY', 'unknown')]]) {
    const h = fixture(t, snapshot(ready(metrics))); const result = await h.run();
    assert.equal(result.reason, 'unsupported');
  }
});

test('malformed, inconsistent and duplicated metrics fail without fabricated zero', async t => {
  for (const metrics of [[money(null)], [money('NaN')], [quota(120)], [{ ...quota(20), remainingPercent: 30 }], [money('1'), money('2')]]) {
    const h = fixture(t, snapshot(ready(metrics))); const result = await h.run();
    assert.equal(result.reason, 'fetch-error'); assert.equal(result.data, undefined);
  }
});

test('OpenRouter key limits are not labelled as account balance', async t => {
  const h = fixture(t, snapshot(ready([money('15', 'USD', 'keyRemaining'), money('5', 'USD', 'usage')], { note: 'keyLimitOnly' })));
  const result = await h.run(); const body = textOf(result.data.rows);
  assert.match(body, /Key剩余额度/); assert.match(body, /不代表账户总余额/);
});

test('the maximum bounded metric response is accepted by the actual upstream bubble parser', async t => {
  const metrics = Array.from({ length: 20 }, (_, i) => ({ ...quota(50, 'rolling'), periodCount: i + 1, periodUnit: 'Hour' }));
  const h = fixture(t, snapshot(ready(metrics, { available: false })));
  const result = await h.run();
  assert.equal(toBalanceState(result)?.ok, true);
  assert.match(textOf(result.data.rows), /当前请求不可用/);
});

test('oversized responses fail explicitly instead of dropping money or windows', async t => {
  const h = fixture(t, snapshot(ready(Array.from({ length: 21 }, (_, i) => ({ ...quota(50, 'rolling'), periodCount: i + 1, periodUnit: 'Hour' })))));
  const result = await h.run();
  assert.equal(result.reason, 'fetch-error');
  assert.equal(result.data, undefined);
});

test('upstream error bodies and credentials cannot cross the bridge', async t => {
  const h = fixture(t, async () => { throw new Error('secret=sk-do-not-expose'); });
  const result = await h.run();
  assert.equal(result.reason, 'fetch-error'); assert.ok(!JSON.stringify(result).includes('sk-do-not-expose'));
});

test('deadline aborts the optional service signal and ends waiting even if service ignores it', async t => {
  t.mock.timers.enable({ apis: ['setTimeout'] }); let signal;
  const h = fixture(t, value => { signal = value; return new Promise(() => {}); }, { requestTimeoutMs: 100 });
  const pending = h.run(); await Promise.resolve();
  assert.equal(signal.aborted, false); t.mock.timers.tick(100);
  const result = await pending;
  assert.equal(signal.aborted, true); assert.equal(result.reason, 'fetch-error');
});

test('unload removes owned providers, cancels in-flight service calls and returns no late success', async t => {
  let signal; let finish;
  const h = fixture(t, value => { signal = value; return new Promise(resolve => { finish = resolve; }); });
  const pending = h.run(); await Promise.resolve(); await h.dispose();
  assert.equal(signal.aborted, true); assert.equal(h.registered.size, 0);
  assert.equal((await pending).reason, 'fetch-error');
  finish(snapshot(ready([money('999')]))); await Promise.resolve();
});

test('actual upstream public registry transparently accepts explicit unsupported without resolving a key', async t => {
  let reads = 0;
  const ctx = { petApi7340: { balance: { list: listBalanceProviders, register: registerBalanceProvider } },
    llm: { listProviders: () => [{ id: 'heixia-quota-fixture' }] }, get: () => undefined,
    effect(setup) { const cleanup = setup(); if (cleanup) t.after(cleanup); } };
  apply(ctx);
  const result = await queryBalance('heixia-quota-fixture', async () => { reads += 1; throw new Error('must not resolve'); });
  assert.equal(result.reason, 'unsupported'); assert.equal(reads, 0);
});

test('rejects unsafe timing or response-size configuration before creating effects', () => {
  for (const config of [{ requestTimeoutMs: 0 }, { requestTimeoutMs: 20000 }, { maxMetrics: 30 }, { unexpected: true }]) {
    assert.throws(() => apply({ effect() { throw new Error('not reached'); } }, config), /quota bridge:/);
  }
});
