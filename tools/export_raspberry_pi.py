"""Export the Raspberry Pi application without Git history or runtime data."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[1]
MODULES = ('common', 'dashboard', 'docs', 'requirements', 'robot', 'scripts', 'tests', 'tools', 'vision', 'voice')
ENTRYPOINTS = ('README.md', '.gitignore', '.gitattributes', 'config.sh', 'requirements.txt',
              'install.sh', 'start_all.sh', 'stop_all.sh', 'start_robot_debug.sh', 'stop_robot_debug.sh',
              'reset_database.sh')


def export(destination: Path) -> None:
    destination = destination.expanduser().resolve()
    if destination == ROOT or ROOT in destination.parents:
        raise ValueError('Export outside the source directory to avoid recursive copies')
    if destination.exists():
        raise FileExistsError(f'Destination already exists; use a new directory: {destination}')
    sources = [ROOT / name for name in ENTRYPOINTS]
    for module in MODULES:
        sources.extend(path for path in (ROOT / module).rglob('*') if path.is_file())
    sources = [path for path in sources if not any(
        part in {'__pycache__', '.DS_Store', 'node_modules', '.venv', '.pytest_cache'}
        or part == '.env' or part.startswith('.env.') for part in path.relative_to(ROOT).parts)
        and path.suffix not in {'.pyc', '.pyo', '.log', '.pid', '.lock'}]
    for path in sources:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'Expected a regular source file: {path.relative_to(ROOT)}')
    destination.mkdir(parents=True)
    entries = []
    for source in sorted(sources):
        relative = source.relative_to(ROOT)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        transformed = False
        if relative.as_posix() == 'config.sh':
            original = target.read_text(encoding='utf-8')
            cleaned = re.sub(r'^export DEEPSEEK_API_KEY=.*$',
                             'export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY:-}"', original, flags=re.MULTILINE)
            target.write_text(cleaned, encoding='utf-8')
            transformed = cleaned != original
        entries.append({'path': relative.as_posix(), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'credential_assignment_removed': transformed})
    (destination / 'export_manifest.json').write_text(json.dumps({
        'component': 'raspberry_pi', 'files': entries,
        'excluded': ['.git', '.venv', 'runtime', 'cache', 'local environment files'],
        'deployment_note': 'Calibrated runtime/robot/servo_params.json and external databases must be migrated separately.'
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Exported {len(entries)} files to {destination}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path, help='New destination directory, conventionally named raspberry_pi')
    args = parser.parse_args()
    try:
        export(args.destination)
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
