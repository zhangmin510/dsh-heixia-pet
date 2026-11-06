/** Install the verified pack into one explicitly selected DSH home, retaining replaced files. */
import { copyFile, mkdir, mkdtemp, readFile, rename, rm, stat, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { verifyPack } from './verify-pack.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const option = name => {
  const index = args.indexOf(name);
  if (index < 0) return undefined;
  if (!args[index + 1] || args[index + 1].startsWith('--')) throw new Error(`Missing ${name} value`);
  return args[index + 1];
};
const pluginDir = resolve(option('--plugin-dir') ?? join(here, '../../dsh-pet'));
const packDir = resolve(option('--pack-dir') ?? join(here, '../pet'));
const homeArg = option('--home');
if (!homeArg) throw new Error('Pass --home explicitly, for example --home ~/.dsh');
const home = resolve(homeArg.startsWith('~/') ? join(homedir(), homeArg.slice(2)) : homeArg);
const report = await verifyPack(pluginDir, packDir);
const petDir = join(home, 'dsh-pet/pet');
await mkdir(petDir, { recursive: true });
const stage = await mkdtemp(join(petDir, '.heixia-install-'));
const backup = join(home, 'dsh-pet/backups', new Date().toISOString().replace(/[:.]/g, '-'));
const configName = 'heixia-config.json';
const animationDir = 'heixia-animation';
const replaced = [];
const installed = [];
const exists = async path => {
  try { await stat(path); return true; }
  catch (error) { if (error.code === 'ENOENT') return false; throw error; }
};
try {
  await mkdir(join(stage, animationDir));
  for (const name of report.names) {
    await copyFile(join(packDir, animationDir, name + '.webm'), join(stage, animationDir, name + '.webm'));
  }
  await copyFile(join(packDir, configName), join(stage, configName));
  const avatar = 'heixia-avatar.png';
  if (await exists(join(packDir, avatar))) await copyFile(join(packDir, avatar), join(stage, avatar));
  // Publish the config last so a live scanner never sees references to missing new media.
  const targets = [animationDir, ...(await exists(join(stage, avatar)) ? [avatar] : []), configName];
  for (const name of targets) {
    const target = join(petDir, name);
    if (await exists(target)) {
      await mkdir(backup, { recursive: true });
      await rename(target, join(backup, name));
      replaced.push(name);
    }
    await rename(join(stage, name), target);
    installed.push(name);
  }
  await writeFile(join(petDir, 'heixia-install.json'), JSON.stringify({
    installedAt: new Date().toISOString(), source: 'https://github.com/zhangmin510/dsh-pet',
    home, names: report.names, replaced, backup: replaced.length ? backup : null,
    automaticChat: true, balance: true,
  }, null, 2) + '\n');
} catch (error) {
  for (const name of [...installed].reverse()) await rm(join(petDir, name), { recursive: true, force: true });
  for (const name of [...replaced].reverse()) await rename(join(backup, name), join(petDir, name));
  throw error;
} finally {
  await rm(stage, { recursive: true, force: true });
}
console.log(JSON.stringify({ installed: true, petDir, mediaCount: report.mediaCount,
  automaticChat: true, balance: true, backup: replaced.length ? backup : null }, null, 2));
