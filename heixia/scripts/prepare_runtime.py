"""Prepare a reproducible HeiXia runtime from the verified dsh-pet npm release."""
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

HEIXIA = Path(__file__).resolve().parents[1]
REPOSITORY = 'https://github.com/zhangmin510/dsh-heixia-pet'
HEIXIA_VERSION = '1.2.0'
INTEGRITY = 'sha512-oQ/TI5WpRQC27MaaFFP0LSilm+SvXLtav7aD7D9m489myQZzPki/Vxvd07jxP7MH1AnBQ9JPkY1VFhEdYxpIEQ=='


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tarball', type=Path)
    parser.add_argument('--output', type=Path, default=HEIXIA / 'runtime')
    parser.add_argument('--install-deps', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit('Output already exists; choose a new --output to retain the current runtime')
    with tempfile.TemporaryDirectory(prefix='heixia-release-') as temporary:
        tarball = args.tarball
        if tarball is None:
            subprocess.run(['npm', 'pack', 'dsh-pet@0.4.5', '--ignore-scripts',
                            '--pack-destination', temporary, '--silent'], check=True)
            tarball = Path(temporary) / 'dsh-pet-0.4.5.tgz'
        data = tarball.read_bytes()
        actual = 'sha512-' + base64.b64encode(hashlib.sha512(data).digest()).decode()
        if actual != INTEGRITY:
            raise SystemExit('Unexpected npm release integrity; no runtime created')
        with tarfile.open(tarball) as archive:
            for entry in archive:
                relative = Path(entry.name).relative_to('package')
                if '..' in relative.parts or entry.issym() or entry.islnk():
                    raise SystemExit('Unexpected archive path or link')
                if entry.isfile():
                    target = output / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(archive.extractfile(entry).read())
    subprocess.run(['python3', '-B', str(HEIXIA / 'customization/apply_mirror_patch.py'),
                    '--runtime', str(output)], check=True)
    subprocess.run(['python3', '-B', str(HEIXIA / 'customization/apply_motion_transition.py'),
                    '--runtime', str(output)], check=True)
    default = output / 'assets/config.jsonc'
    text = default.read_text()
    for before, after in [('"whisperEnabled": true,', '"whisperEnabled": false,'),
                          ('"balanceEnabled": true,', '"balanceEnabled": false,'),
                          ('"display": "both",', '"display": "none",'),
                          ('"clickSoundEnabled": true,', '"clickSoundEnabled": false,'),
                          ('"notificationsEnabled": true,', '"notificationsEnabled": false,')]:
        if before not in text:
            raise SystemExit('Unexpected default configuration; inspect this release before using it')
        text = text.replace(before, after, 1)
    default.write_text(text)
    bridge = output / 'heixia/src/model-quota-bridge.js'
    bridge.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(HEIXIA / 'src/model-quota-bridge.js', bridge)
    package_path = output / 'package.json'
    package = json.loads(package_path.read_text())
    package['exports']['./heixia-quota-bridge'] = './heixia/src/model-quota-bridge.js'
    package['files'] = list(dict.fromkeys(package['files'] + ['heixia', 'assets/logo.svg']))
    package['icon'] = 'assets/logo.svg'
    package['description'] = '黑侠：基于 PC2005-cloud/dsh-pet 的真实黑白猫宠物，支持会话动作、自动聊天及模型余量桥接。'
    package['heixia'] = {'version': HEIXIA_VERSION, 'fork': REPOSITORY,
                        'upstreamVersion': '0.4.5', 'releaseIntegrity': INTEGRITY}
    # The frozen npm artifact has already been built; installing this local directory must not re-run its source prepack.
    package['scripts'] = {key: value for key, value in package.get('scripts', {}).items()
                          if key not in ('prepack', 'prepare', 'postinstall')}
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n')
    patch = output / 'cordis.patch.yml'
    patch.write_text(patch.read_text() + "\n- insert:\n    - id: heixia-model-quota\n      name: 'dsh-pet/heixia-quota-bridge'\n")
    for name in ['logo.png', 'main-character.png']:
        shutil.copyfile(HEIXIA / 'pet/heixia-avatar.png', output / 'assets' / name)
    shutil.copyfile(HEIXIA / 'pet/heixia-icon.svg', output / 'assets/logo.svg')
    if args.install_deps:
        subprocess.run(['npm', 'install', '--omit=dev', '--ignore-scripts', '--legacy-peer-deps',
                        '--no-audit', '--no-fund', '--package-lock=false'], cwd=output, check=True)
    print(json.dumps({'prepared': str(output), 'upstream': 'PC2005-cloud/dsh-pet@0.4.5',
                      'integrityVerified': True, 'mirrorPatch': True, 'quotaBridge': True}, ensure_ascii=False))


if __name__ == '__main__':
    main()
