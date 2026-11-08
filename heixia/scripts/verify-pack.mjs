/** Validate HeiXia with dsh-pet's real config reader before installing any files. */
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { pathToFileURL, fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));

/** Return every animation file referenced by an independent pet pack.
 * @param {object} animations - The upstream animations configuration.
 * @returns {string[]} Unique animation names, without extensions.
 */
export function animationNames(animations) {
  return [...new Set([
    ...animations.idle, ...animations.turn, ...animations.drag, ...animations.clicks,
    ...animations.moves.actions.map(item => item.name),
    ...animations.categories.flatMap(item => item.actions),
    ...Object.values(animations.events).flat(2),
    ...(animations.sleep ?? []).flatMap(item => [...item.start, ...item.loop, ...item.end]),
  ])];
}

/** Read through the actual host merge and client flatten functions, rejecting fallback data.
 * @param {string} pluginDir - A source or installed dsh-pet package directory.
 * @param {string} packDir - Directory containing heixia-config.json and heixia-animation/.
 * @returns {Promise<object>} Verified source configuration and media names.
 */
export async function verifyPack(pluginDir, packDir) {
  const source = JSON.parse(await readFile(join(packDir, 'heixia-config.json'), 'utf8'));
  const { readAllConfig } = await import(pathToFileURL(join(pluginDir, 'src/host/config/read.ts')).href);
  const { flattenConfigPets } = await import(pathToFileURL(join(pluginDir, 'src/shared/config.ts')).href);
  const temporary = await mkdtemp(join(tmpdir(), 'heixia-verify-'));
  try {
    const merged = readAllConfig({ defaultFile: join(pluginDir, 'assets/config.jsonc'),
      userFile: join(temporary, 'absent.jsonc'), petDir: packDir });
    assert.ok(merged.heixia, 'The real host reader did not discover the HeiXia pack');
    for (const key of Object.keys(source)) {
      assert.deepEqual(merged.heixia[key], source[key], `Host rejected or changed ${key}`);
    }
    const pet = flattenConfigPets(merged).find(item => item.assetRoot === 'heixia');
    assert.ok(pet, 'The client did not receive the HeiXia pack');
    assert.equal(pet.name, '黑侠');
    assert.equal(pet.whisperEnabled, true);
    assert.equal(pet.balanceEnabled, true);
    assert.equal(pet.workStatusEnabled, true);
    const animations = pet.animations;
    assert.equal(animations.events.workStatus.length, 6);
    assert.equal(new Set(animations.events.workStatus.flat()).size, 6, 'Work states need distinct cues');
    assert.equal(animations.events.balance.length, 6);
    assert.ok(animations.events.whisper.length, 'Missing speech cue');
    for (const key of ['idle', 'turn', 'drag', 'clicks']) {
      assert.ok(animations[key].length, `Missing action pool: ${key}`);
    }
    assert.ok(animations.sleep?.length, 'Missing sleep set');
    for (const { start, loop, end } of animations.sleep) {
      assert.ok(start.length && loop.length && end.length, 'Sleep needs three playable phases');
      const phases = [...start, ...loop, ...end];
      assert.equal(new Set(phases).size, phases.length, 'Sleep phases must be distinct');
    }
    const names = animationNames(source.animations);
    assert.ok(names.length >= 8, 'Expected eight distinct real-media actions');
    for (const name of names) {
      assert.equal(typeof name, 'string');
      assert.ok(name && !/[\\/\0]/.test(name), 'Animation names must be local basenames');
      const media = await stat(join(packDir, 'heixia-animation', name + '.webm'));
      assert.ok(media.isFile() && media.size > 1000, `Missing/empty animation: ${name}`);
    }
    return { passed: true, name: pet.name, petId: pet.id, mediaCount: names.length, names,
      automaticChat: true, balance: true, model: merged.heixia.whisperModel,
      refreshSeconds: merged.heixia.eventsRefreshSec, source };
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const plugin = resolve(process.argv[2] ?? join(here, '../../dsh-pet'));
  const pack = resolve(process.argv[3] ?? join(here, '../pet'));
  const { source, ...report } = await verifyPack(plugin, pack);
  console.log(JSON.stringify(report, null, 2));
}
