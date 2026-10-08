import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'MIGRATION_MANIFEST.json'


def inventory():
    entries = {}
    for path in sorted(ROOT.rglob('*')):
        if path == MANIFEST:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink():
            entries[relative] = {'type': 'symlink', 'target': str(path.readlink())}
        elif path.is_file():
            before = path.stat()
            digest = hashlib.sha256()
            with path.open('rb') as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b''):
                    digest.update(chunk)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise RuntimeError(f'文件正在变化，请结束任务后重试：{relative}')
            entries[relative] = {'type': 'file', 'size': after.st_size, 'sha256': digest.hexdigest()}
        elif path.is_dir():
            entries[relative] = {'type': 'directory'}
        else:
            raise RuntimeError(f'不支持的文件类型：{relative}')
    return entries


def main():
    parser = argparse.ArgumentParser(description='完整迁移文件清单：包含隐藏文件、配置、报告与图片。')
    parser.add_argument('action', choices=('create', 'verify'))
    args = parser.parse_args()
    if args.action == 'create':
        entries = inventory()
        payload = {'version': 1, 'createdAt': datetime.now(timezone.utc).isoformat(), 'entries': entries}
        MANIFEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        links = sum(entry['type'] == 'symlink' for entry in entries.values())
        print(f'已生成 {MANIFEST.name}：{len(entries)} 个条目，{links} 个符号链接。')
        return
    payload = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if payload.get('version') != 1 or not isinstance(payload.get('entries'), dict):
        raise ValueError('清单格式无效')
    expected = payload['entries']
    actual = inventory()
    missing = sorted(expected.keys() - actual.keys())
    extra = sorted(actual.keys() - expected.keys())
    changed = sorted(key for key in expected.keys() & actual.keys() if expected[key] != actual[key])
    for label, paths in (('缺失', missing), ('多余', extra), ('变化', changed)):
        if paths:
            print(f'{label} {len(paths)} 个：')
            for path in paths[:30]:
                print(path)
    if missing or extra or changed:
        raise SystemExit(1)
    print(f'校验通过：{len(expected)} 个条目内容一致。')


if __name__ == '__main__':
    main()
