"""Attach the shipped HeiXia pack to the pinned dsh-pet 0.4.5 host."""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path


UPSTREAM_HOST_SHA256 = '19c5587b9508d1da70041f47c49f06c61b94351563c286b49b582d14739ef523'
PACK_PATH = Path('heixia/pet')


def _patch_host(host: bytes) -> bytes:
    if hashlib.sha256(host).hexdigest() != UPSTREAM_HOST_SHA256:
        raise ValueError('Unexpected dsh-pet host bundle. Recheck the pinned release before applying the HeiXia fallback.')
    source = host.decode('utf-8')
    edits = [
        (
            'const PACKAGE_ROOT_ASSETS = join(PACKAGE_ROOT, "assets");',
            'const BUNDLED_HEIXIA_PET_DIR = join(PACKAGE_ROOT, "heixia", "pet");\n'
            'const BUNDLED_HEIXIA_CONFIG = join(BUNDLED_HEIXIA_PET_DIR, "heixia-config.json");\n'
            'const PACKAGE_ROOT_ASSETS = join(PACKAGE_ROOT, "assets");',
        ),
        (
            '\treturn hit ? {\n\t\tpath: hit.path,\n\t\traw: readJsonc(hit.path)\n\t} : void 0;',
            '\tif (hit) return { path: hit.path, raw: readJsonc(hit.path) };\n'
            '\tif (entry !== "heixia") return void 0;\n'
            '\tconst raw = readJsonc(BUNDLED_HEIXIA_CONFIG);\n'
            '\tif (!raw) return void 0;\n'
            '\t// Explicit edits create a user override. The package remains read-only.\n'
            '\treturn { path: join(paths.petDir, "heixia-config.json"), raw, createOnly: true };',
        ),
        (
            '\tfor (const file of scanPetFiles(paths.petDir)) {',
            '\tconst files = scanPetFiles(paths.petDir);\n'
            '\tfor (const file of files) {',
        ),
        (
            '\t\tout[file.prefix] = mergeEntry(filePetBase, parsed, file.prefix + "-config.json", basePets, seenIds);\n'
            '\t}\n\treturn out;',
            '\t\tout[file.prefix] = mergeEntry(filePetBase, parsed, file.prefix + "-config.json", basePets, seenIds);\n'
            '\t}\n'
            '\t// User files and their instance IDs take precedence over the shipped default.\n'
            '\tif (!files.some((file) => file.prefix === "heixia") && !seenIds.has("heixia")) {\n'
            '\t\tconst bundled = readJsonc(BUNDLED_HEIXIA_CONFIG);\n'
            '\t\tif (bundled) out.heixia = mergeEntry(filePetBase, bundled, "bundled heixia-config.json", basePets, seenIds);\n'
            '\t}\n\treturn out;',
        ),
        (
            '\t\t\texisting: file.raw\n',
            '\t\t\texisting: file.raw,\n\t\t\tcreateOnly: file.createOnly === true\n',
        ),
        (
            'const own$1 = petAvatarFile(petConfigDir, assetRoot);',
            'const own$1 = petAvatarFile(petConfigDir, assetRoot)\n'
            '\t\t\t\t?? (assetRoot === "heixia" ? petAvatarFile(BUNDLED_HEIXIA_PET_DIR, assetRoot) : void 0);',
        ),
        (
            '\t\treturn extraAnimDir !== void 0 && existsSync(extraAnimDir) ? resolveExisting(extraAnimDir, name$1)'
            ' : resolveExisting(userRootFor(e), name$1) ?? resolveExisting(assetRootFor(e), name$1);',
            '\t\tif (extraAnimDir !== void 0 && existsSync(extraAnimDir)) return resolveExisting(extraAnimDir, name$1);\n'
            '\t\treturn resolveExisting(userRootFor(e), name$1)\n'
            '\t\t\t?? (petId === "heixia" ? resolveExisting(join(BUNDLED_HEIXIA_PET_DIR, "heixia-animation"), name$1) : void 0)\n'
            '\t\t\t?? resolveExisting(assetRootFor(e), name$1);',
        ),
    ]
    for original, replacement in edits:
        if source.count(original) != 1:
            raise ValueError(f'Unexpected host anchor: {original.splitlines()[0].strip()}')
        source = source.replace(original, replacement, 1)

    write = 'await writeFile(layer.path, JSON.stringify(clean, null, 2), "utf8");'
    if source.count(write) != 2:
        raise ValueError('Expected two pet layer write paths')
    source = source.replace(
        write,
        'await writeFile(layer.path, JSON.stringify(clean, null, 2), '
        'layer.createOnly ? { encoding: "utf8", flag: "wx" } : "utf8");',
    )
    return source.encode('utf-8')


def bundle_default_pet(runtime: Path, pack: Path) -> dict:
    """Add the read-only default to a fresh prepared runtime, before npm packing."""
    runtime, pack = Path(runtime), Path(pack)
    host_path = runtime / 'lib/index.js'
    patched = _patch_host(host_path.read_bytes())
    target = runtime / PACK_PATH
    if target.exists() or target.is_symlink():
        raise ValueError(f'Bundled pet directory already exists: {target}')

    config = pack / 'heixia-config.json'
    avatar = pack / 'heixia-avatar.png'
    manifest_path = pack / 'media_manifest.json'
    config_data = json.loads(config.read_text(encoding='utf-8'))
    if [pet['id'] for pet in config_data['pets']] != ['heixia']:
        raise ValueError('The shipped default must contain one HeiXia instance')
    if not avatar.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('The shipped HeiXia avatar must be a PNG')
    items = json.loads(manifest_path.read_text(encoding='utf-8'))['items']
    animation_dir = pack / 'heixia-animation'
    names = set()
    for item in items:
        name = item['filename']
        if not name.endswith('.webm') or '/' in name or '\\' in name or name in names:
            raise ValueError(f'Invalid or duplicate animation filename: {name!r}')
        data = (animation_dir / name).read_bytes()
        if not data.startswith(b'\x1a\x45\xdf\xa3') or hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError(f'Animation does not match its manifest: {name}')
        names.add(name)
    if not names:
        raise ValueError('The shipped HeiXia pack has no animations')

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.heixia-bundle-', dir=target.parent) as temporary:
        stage = Path(temporary)
        media = stage / 'pet/heixia-animation'
        media.mkdir(parents=True)
        for name in sorted(names):
            shutil.copyfile(animation_dir / name, media / name)
        for source in (config, avatar, manifest_path):
            shutil.copyfile(source, stage / 'pet' / source.name)
        host_stage = stage / 'index.js'
        host_stage.write_bytes(patched)
        (stage / 'pet').rename(target)
        try:
            host_stage.replace(host_path)
        except OSError:
            shutil.rmtree(target)
            raise

    return {
        'petDir': PACK_PATH.as_posix(),
        'animationCount': len(names),
        'upstreamHostSha256': UPSTREAM_HOST_SHA256,
        'patchedHostSha256': hashlib.sha256(patched).hexdigest(),
    }
