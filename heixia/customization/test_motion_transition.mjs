/** Exercise the actual prepared Web and Electron playback code. */
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from 'node:test';
import vm from 'node:vm';

const runtime = process.env.HEIXIA_MOTION_RUNTIME ?? fileURLToPath(new URL('../runtime', import.meta.url));
const animations = { idle: ['待机'], turn: [], drag: [], clicks: [], categories: [], events: {} };
const noop = () => {};

function video() {
  const classes = new Set();
  const listeners = new Map();
  return {
    src: '', style: {}, readyState: 0, effects: [], pauses: 0,
    classList: { add: value => classes.add(value), remove: value => classes.delete(value),
      contains: value => classes.has(value) },
    addEventListener(event, handler) {
      if (!listeners.has(event)) listeners.set(event, new Set());
      listeners.get(event).add(handler);
    },
    removeEventListener(event, handler) { listeners.get(event)?.delete(handler); },
    load() { this.readyState = 0; },
    ready() {
      this.readyState = 2;
      for (const handler of [...listeners.get('loadeddata') ?? []]) handler();
    },
    play() { return Promise.resolve(); },
    pause() { this.pauses += 1; },
    animate(frames, options) {
      const effect = { frames, options, cancelled: false, cancel() { this.cancelled = true; } };
      this.effects.push(effect);
      return effect;
    },
  };
}

function harness(surface, { assetRoot = 'heixia', reducedMotion = false } = {}) {
  const a = video();
  const b = video();
  const reports = [];
  const report = (...values) => reports.push(values);
  const ctx = vm.createContext({ window: {
    __ModuleLoader__: { load: noop }, matchMedia: () => ({ matches: reducedMotion }),
    setTimeout: () => 1, clearTimeout: noop,
  }, BASE: 'http://localhost/dsh-pet-7340',
  navigator: { userAgent: 'Chromium', platform: 'MacIntel' }, URL, AbortController,
  console: { log: noop, warn: noop, error: noop } });
  const run = (source) => vm.runInContext(source, ctx);
  const read = (...parts) => readFileSync(resolve(runtime, ...parts), 'utf8');
  let player;
  if (surface === 'web') {
    const marker = 'window.__ModuleLoader__.load({';
    run(read('lib/client.js').replace(marker, `globalThis.createPlayer = createOwnAnimation;\n${marker}`));
    const animation = ctx.createPlayer({
      videoA: () => a, videoB: () => b, cfg: () => ({ id: 'pet', assetRoot, animations }),
      currentAnim: () => '待机', workStatus: () => null, facing: () => 'left',
      report, clearCuePlayback: noop, onFrontReady: noop, onEnded: noop,
      isDragging: () => false, initiallyFrozen: false,
      loader: { load(url, handlers) { handlers.onObjectUrl(url); }, release: noop, abortAll: noop },
    });
    player = { switchTo: animation.switchTo, front: animation.frontVideo,
      freeze: () => animation.setFrozen(true), dispose: animation.dispose };
  } else {
    run(read('runtime/electron-helper', 'shared-core.js'));
    run('globalThis.S = PetShared;');
    run(read('runtime/electron-helper', 'sprite.js'));
    run(read('runtime/electron-helper', 'sprite/playback.js'));
    const sprite = run('Object.create(PetSprite.prototype)');
    Object.assign(sprite, {
      assetRoot, pet: { id: 'pet' }, _facing: 'left', animations, gen: 0, pending: null,
      front: 0, videoA: a, videoB: b, assetBase: '/assets/', reportPlayback: report,
      frozen: false, workTimer: null, whisperTimer: null, bubbleTimer: null, chatMount: null,
      ac: { abort: noop }, inputRegionMutation: { disconnect: noop },
      inputRegionResize: { disconnect: noop }, inputRegionElements: new Set(), el: { remove: noop },
      stopMove: noop, renderBubble: noop, closeMenu: noop, stopThrow: noop, stopDragFollow: noop, stopSquash: noop,
    });
    player = { switchTo: sprite.switchTo.bind(sprite), front: () => sprite.front === 0 ? a : b,
      freeze: () => sprite.applyFreeze(true), dispose: () => sprite.dispose() };
  }
  return { ...player, a, b, reports };
}

for (const surface of ['web', 'desktop']) {
  test(`${surface}: only a ready distinct action blends, with immediate playback receipts`, async () => {
    const p = harness(surface);
    p.switchTo('待机', true, 'first'); p.b.ready();
    await Promise.resolve();
    assert.equal(p.b.effects.length, 0);
    p.switchTo('思考', true, 'second');
    assert.equal(p.front(), p.b);
    p.a.ready();
    await Promise.resolve();
    assert.equal(p.front(), p.a);
    assert.equal(p.b.pauses, 1);
    assert.equal(p.b.onended, null);
    assert.equal(p.b.effects[0].options.duration, 72);
    assert.equal(p.a.effects[0].options.duration, 96);
    assert.deepEqual(p.reports, [
      ['first', 'playing'], ['first', 'cancelled', 'superseded'], ['second', 'playing'],
    ]);
    p.switchTo('工作', true, 'third');
    assert.ok(p.a.effects[0].cancelled && p.b.effects[0].cancelled);
    p.switchTo('等待', true, 'latest');
    p.b.ready();
    await Promise.resolve();
    assert.equal(p.front(), p.b);
    assert.ok(!p.reports.some(row => row[0] === 'third'));
    p.freeze();
    assert.ok(p.a.effects[1].cancelled && p.b.effects[1].cancelled);
    assert.deepEqual(p.reports.at(-1), ['latest', 'cancelled', 'frozen']);
    p.dispose();
  });

  test(`${surface}: reduced motion and other pets keep their intended opacity behavior`, () => {
    for (const options of [{ reducedMotion: true }, { assetRoot: 'main' }]) {
      const p = harness(surface, options);
      p.switchTo('待机', true, null); p.b.ready();
      p.switchTo('思考', true, null); p.a.ready();
      assert.equal(p.a.effects.length + p.b.effects.length, 0);
      assert.equal(p.a.style.transition, options.reducedMotion ? 'none' : undefined);
      p.dispose();
    }
  });

  test(`${surface}: replaying one source does not blend, and disposal cancels an active blend`, () => {
    const p = harness(surface);
    p.switchTo('待机', true, null); p.b.ready();
    p.switchTo('待机', true, null); p.a.ready();
    assert.equal(p.a.effects.length + p.b.effects.length, 0);
    p.switchTo('思考', true, null); p.b.ready();
    assert.ok(!p.a.effects[0].cancelled && !p.b.effects[0].cancelled);
    p.dispose();
    assert.ok(p.a.effects[0].cancelled && p.b.effects[0].cancelled);
  });

  test(`${surface}: a late frame cannot start a transition after disposal`, () => {
    const p = harness(surface);
    p.switchTo('待机', true, null); p.b.ready();
    p.switchTo('思考', true, null);
    p.dispose();
    p.a.ready();
    assert.equal(p.front(), p.b);
    assert.equal(p.a.effects.length + p.b.effects.length, 0);
  });
}
