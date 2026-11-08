"""Build the installable HeiXia npm tarball for a GitHub Release."""
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from bundle_default_pet import bundle_default_pet
from prepare_runtime import HEIXIA, REPOSITORY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tarball', type=Path, help='Local copy of the pinned upstream npm release')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='heixia-build-', dir=output) as temporary:
        stage = Path(temporary)
        runtime = stage / 'runtime'
        command = [sys.executable, '-B', str(HEIXIA / 'scripts/prepare_runtime.py'),
                   '--output', str(runtime)]
        if args.tarball is not None:
            command += ['--tarball', str(args.tarball.resolve())]
        subprocess.run(command, check=True)
        bundled = bundle_default_pet(runtime, HEIXIA / 'pet')
        manifest = runtime / 'package.json'
        package = json.loads(manifest.read_text())
        version = package['heixia']['version']
        # The host/client module IDs and profile settings are shared with upstream.
        package['version'] = '0.4.5-heixia.2'
        package['homepage'] = REPOSITORY
        package['repository']['url'] = f'git+{REPOSITORY}.git'
        package['repository']['directory'] = 'dsh-pet'
        package['bugs']['url'] = f'{REPOSITORY}/issues'
        # Use system fonts without redistributing the upstream third-party TTF.
        package['files'].remove('assets/fonts')
        manifest.write_text(json.dumps(package, ensure_ascii=False, indent=2) + '\n')
        default = runtime / 'assets/config.jsonc'
        config = default.read_text()
        if config.count('"family": "candy"') != 1:
            raise SystemExit('Unexpected font default in pinned upstream package')
        default.write_text(config.replace('"family": "candy"', '"family": "system"'))
        readme = runtime / 'README.md'
        upstream_readme = readme.read_text()
        readme.write_text(f'# 黑侠 · DeepSeek Harness 宠物\n\n'
                          f'黑侠 {version}，包含 {bundled["animationCount"]} 个动作与姿态。\n\n'
                          f'[安装说明与版本发布]({REPOSITORY}/releases)\n\n'
                          f'## 上游项目与许可\n\n{upstream_readme}')
        filename = f'dsh-heixia-pet-{version}.tgz'
        asset = output / filename
        checksum = output / f'{filename}.sha256'
        if asset.exists() or checksum.exists():
            raise SystemExit('Release output already exists; choose a new --output directory')
        result = subprocess.check_output(['npm', 'pack', '--ignore-scripts', '--json',
                                          '--cache', str(stage / 'npm-cache'),
                                          '--pack-destination', str(stage)], cwd=runtime, text=True)
        packed, = json.loads(result)
        archive = stage / packed['filename']
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.rename(asset)
        checksum.write_text(f'{digest}  {filename}\n')
        print(json.dumps({'asset': str(asset), 'sha256': digest, 'bytes': packed['size'],
                          'files': packed['entryCount'], 'bundledPet': bundled},
                         ensure_ascii=False))


if __name__ == '__main__':
    main()
