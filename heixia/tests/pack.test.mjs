/** Verify real upstream configuration acceptance and installation preflight behavior. */
import assert from 'node:assert/strict';
import { cp, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';
import { verifyPack } from '../scripts/verify-pack.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const pack = resolve(here, '../pet');
const plugin = resolve(here, '../../dsh-pet');

test('the actual host reader and client projection retain HeiXia and its enabled features', async () => {
  const result = await verifyPack(plugin, pack);
  assert.equal(result.petId, 'heixia');
  assert.equal(result.mediaCount, 11);
  for (const name of ['洗脸', '轻摆尾巴', '仰躺揣爪']) assert.ok(result.names.includes(name));
  assert.ok(result.automaticChat && result.balance);
  assert.equal(result.model.provider, '');
  assert.equal(result.model.model, '');
});

test('a truncated work-status mapping is rejected before installing media', async () => {
  const temporary = await mkdtemp(join(tmpdir(), 'heixia-invalid-'));
  try {
    await cp(pack, temporary, { recursive: true });
    const config = JSON.parse(await readFile(join(temporary, 'heixia-config.json'), 'utf8'));
    config.animations.events.workStatus.pop();
    await writeFile(join(temporary, 'heixia-config.json'), JSON.stringify(config));
    await assert.rejects(verifyPack(plugin, temporary), /5 !== 6/);
  } finally { await rm(temporary, { recursive: true, force: true }); }
});

test('missing media cannot change an existing installed pet', async () => {
  const temporary = await mkdtemp(join(tmpdir(), 'heixia-preflight-'));
  try {
    const badPack = join(temporary, 'bad-pack');
    await cp(pack, badPack, { recursive: true });
    await rm(join(badPack, 'heixia-animation/待机.webm'));
    const home = join(temporary, 'home');
    const target = join(home, 'dsh-pet/pet');
    await cp(pack, target, { recursive: true });
    const original = await readFile(join(target, 'heixia-config.json'));
    const command = spawnSync(process.execPath, [join(here, '../scripts/install-pack.mjs'),
      '--plugin-dir', plugin, '--pack-dir', badPack, '--home', home], { encoding: 'utf8' });
    assert.notEqual(command.status, 0);
    assert.deepEqual(await readFile(join(target, 'heixia-config.json')), original);
    assert.ok((await readFile(join(target, 'heixia-animation/待机.webm'))).length > 1000);
  } finally { await rm(temporary, { recursive: true, force: true }); }
});
