"""Apply or verify the narrow HeiXia mirror patch against dsh-pet 0.4.5."""
import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path, default=HERE.parent / 'runtime')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    spec = json.loads((HERE / 'mirror_patch_spec.json').read_text())
    package = json.loads((runtime / 'package.json').read_text())
    if (package['name'], package['version']) != (spec['package'], spec['version']):
        raise SystemExit('Unsupported package: expected dsh-pet 0.4.5')
    prepared, evidence = [], []
    # Validate every target before mutating either file.
    for relative, patch in spec['files'].items():
        path = runtime / relative
        before = path.read_bytes()
        actual = digest(before)
        if actual == patch['after_sha256']:
            evidence.append({'file': relative, 'status': 'already-patched', **{k: patch[k] for k in ('before_sha256', 'after_sha256')}})
            continue
        if args.check or actual != patch['before_sha256']:
            raise SystemExit(f'Unexpected target SHA; no changes applied: {path}')
        after = before.decode('utf-8')
        for old, new in patch['replacements']:
            if after.count(old) != 1:
                raise SystemExit(f'Expected exactly one patch site; no changes applied: {relative}')
            after = after.replace(old, new)
        encoded = after.encode('utf-8')
        if digest(encoded) != patch['after_sha256']:
            raise SystemExit(f'Patched SHA mismatch; no changes applied: {relative}')
        prepared.append((path, before, encoded, relative))
        evidence.append({'file': relative, 'status': 'patched', **{k: patch[k] for k in ('before_sha256', 'after_sha256')}})
    if not args.check:
        backups = HERE / 'backups'
        backups.mkdir(exist_ok=True)
        for path, before, after, relative in prepared:
            backup = backups / (digest(before) + '-' + Path(relative).name)
            if not backup.exists():
                backup.write_bytes(before)
            temporary = path.with_suffix(path.suffix + '.mirror-tmp')
            temporary.write_bytes(after)
            temporary.replace(path)
        report = {'patched_at': datetime.now(ZoneInfo('Asia/Singapore')).isoformat(),
                  'runtime': str(runtime), 'upstream': spec['upstream'], 'version': spec['version'],
                  'source_commit': spec['source_commit'], 'scope': spec['scope'], 'files': evidence,
                  'license': 'Upstream MIT retained; this patch does not use agent-pet or Mewmate.'}
        (HERE / 'mirror_patch_provenance.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'passed': True, 'check_only': args.check, 'files': evidence}, ensure_ascii=False))


if __name__ == '__main__':
    main()
