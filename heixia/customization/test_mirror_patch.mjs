/** Exercise the shipped browser and desktop playback paths without starting Harness or calling models. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { test } from 'node:test';
import vm from 'node:vm';

const runtime = resolve(fileURLToPath(new URL('../runtime/', import.meta.url)));
const animationPool = { idle: ['idle'], turn: [], drag: [], clicks: ['touch'],
  moves: { default: {}, actions: [] }, categories: [], events: { balance: ['idle'] } };

function video() {
  const listeners = new Map();
  const classes = new Set();
  return { src: '', style: {}, readyState: 0, playCalls: 0, loop: false,
    classList: { add: name => classes.add(name), remove: name => classes.delete(name) },
    addEventListener(name, listener) { listeners.set(name, listener); },
    removeEventListener(name, listener) { if (listeners.get(name) === listener) listeners.delete(name); },
    fire(name) { listeners.get(name)?.(); }, load() {}, pause() {},
    play() { this.playCalls += 1; return Promise.resolve(); } };
}

function clock() {
  let now = 0;
  let pending = [];
  let sequence = 0;
  return { performance: { now: () => now },
    requestAnimationFrame(callback) { const id = ++sequence; pending.push({ id, callback }); return id; },
    cancelAnimationFrame(id) { pending = pending.filter(row => row.id !== id); },
    tick(milliseconds) { now += milliseconds; const due = pending; pending = []; for (const row of due) row.callback(); } };
}

function browser() {
  const frames = clock();
  const sandbox = { window: { __ModuleLoader__: { load() {} }, matchMedia: () => ({ matches: false }) },
    navigator: { userAgent: 'Chromium', platform: 'MacIntel' }, performance: frames.performance,
    requestAnimationFrame: frames.requestAnimationFrame, cancelAnimationFrame: frames.cancelAnimationFrame,
    URL, AbortController, console };
  vm.createContext(sandbox);
  const original = readFileSync(resolve(runtime, 'lib/client.js'), 'utf8');
  const marker = 'window.__ModuleLoader__.load({';
  assert.equal(original.split(marker).length - 1, 1);
  // Export internals only in this VM; the shipped file stays unchanged.
  const script = original.replace(marker, 'globalThis.__mirrorTest = {createOwnAnimation, createSquashDriver};\n' + marker);
  vm.runInContext(script, sandbox);
  return { ...sandbox.__mirrorTest, frames };
}

for (const [root, expected] of [['heixia', ''], ['main', 'scaleX(-1)'], ['another-cat', 'scaleX(-1)']]) {
  test(`shipped browser: a right-facing API/menu cue renders ${root} in the intended orientation`, async () => {
    const api = browser();
    const a = video(); const b = video(); const requests = []; const reports = [];
    const animation = api.createOwnAnimation({
      videoA: () => a, videoB: () => b, cfg: () => ({ id: 'instance', assetRoot: root, animations: animationPool }),
      currentAnim: () => 'idle', workStatus: () => null, facing: () => 'right',
      report: (id, state) => reports.push([id, state]), clearCuePlayback() {}, onFrontReady() {}, onEnded() {},
      isDragging: () => false, initiallyFrozen: false,
      loader: { load(url, handlers) { requests.push({ url, handlers }); }, release() {}, abortAll() {} },
    });
    animation.switchTo('touch', true, 'api-cue');
    requests[0].handlers.onObjectUrl('blob:test'); b.fire('loadeddata');
    await Promise.resolve();
    assert.equal(b.style.transform, expected);
    assert.equal(b.playCalls, 1);
    assert.deepEqual(reports, [['api-cue', 'playing']]);
    animation.dispose();
  });
  test(`shipped browser: ${root} click/landing squash does not restore the wrong horizontal transform`, () => {
    const api = browser(); const element = video();
    const driver = api.createSquashDriver({ facing: () => 'right', assetRoot: () => root });
    driver.start(element); api.frames.tick(0);
    assert.equal(element.style.transform.includes('scaleX(-1)'), expected !== '');
    assert.ok(element.style.transform.includes('scaleY('));
    api.frames.tick(10000);
    assert.equal(element.style.transform, expected);
  });
}

function desktop(root) {
  const frames = clock();
  const sandbox = { BASE: 'http://localhost/dsh-pet-7340', config: {}, sprites: [],
    navigator: { userAgent: 'Chromium', platform: 'MacIntel' },
    window: { setTimeout: () => 1, clearTimeout() {}, matchMedia: () => ({ matches: false }) },
    performance: frames.performance, requestAnimationFrame: frames.requestAnimationFrame,
    cancelAnimationFrame: frames.cancelAnimationFrame, console, URL, AbortController };
  vm.createContext(sandbox);
  const helper = resolve(runtime, 'runtime/electron-helper');
  vm.runInContext(readFileSync(resolve(helper, 'shared-core.js'), 'utf8'), sandbox);
  vm.runInContext('globalThis.S = PetShared;', sandbox);
  for (const relative of ['sprite.js', 'sprite/playback.js', 'sprite/menu.js', 'sprite/motion.js', 'events.js']) {
    vm.runInContext(readFileSync(resolve(helper, relative), 'utf8'), sandbox);
  }
  vm.runInContext('globalThis.__Sprite = PetSprite; globalThis.__applyAnimLeaf = applyAnimLeaf;', sandbox);
  const sprite = Object.create(sandbox.__Sprite.prototype);
  Object.assign(sprite, { assetRoot: root, pet: { id: 'test-pet' }, _facing: 'left',
    anim: 'idle', animations: animationPool, gen: 0, pending: null, front: 0,
    videoA: video(), videoB: video(), assetBase: sandbox.BASE + '/thumb/' + root + '/',
    pendingSquash: false, pendingMove: false, squashToken: 0, squashRef: null,
    markPoseDirty() {}, closeMenu() {}, stopMove() {}, reportPlayback() {} });
  sandbox.sprites.push(sprite);
  return { sprite, frames, applyAnimLeaf: sandbox.__applyAnimLeaf };
}

for (const [root, expected] of [['heixia', ''], ['main', 'scaleX(-1)'], ['another-cat', 'scaleX(-1)']]) {
  test(`shipped desktop: an actual explicit-facing API leaf passes through menu dispatch and video playback for ${root}`, async () => {
    const { sprite, applyAnimLeaf } = desktop(root);
    applyAnimLeaf('test-pet', { data: { name: 'touch', facing: 'right', playbackId: 'api-menu' }, seq: 1 });
    sprite.videoB.fire('loadeddata'); await Promise.resolve();
    assert.equal(sprite.videoB.style.transform, expected);
    assert.equal(sprite.videoB.playCalls, 1);
  });
  test(`shipped desktop: an explicit URL-facing cue uses the same protected ${root} playback`, () => {
    const { sprite, applyAnimLeaf } = desktop(root);
    applyAnimLeaf('test-pet', { data: { url: 'https://example.test/clip.webm', facing: 'right' }, seq: 2 });
    sprite.videoB.fire('loadeddata');
    assert.equal(sprite.videoB.style.transform, expected);
    assert.equal(sprite.videoB.src, 'https://example.test/clip.webm');
  });
  test(`shipped desktop: direct menu playback and squash preserve ${root} identity`, () => {
    const { sprite, frames } = desktop(root);
    sprite.facing = 'right';
    // A stale raw state must not bypass HeiXia's source-orientation getter.
    if (root === 'heixia') sprite._facing = 'right';
    sprite.onMenuAction({ anim: 'touch', label: '摸摸' }, true, false);
    sprite.videoB.fire('loadeddata');
    assert.equal(sprite.videoB.style.transform, expected);
    sprite.startSquash(sprite.videoB); frames.tick(0);
    assert.equal(sprite.videoB.style.transform.includes('scaleX(-1)'), expected !== '');
    frames.tick(10000); assert.equal(sprite.videoB.style.transform, expected);
  });
}
