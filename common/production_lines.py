"""Production-line identity and isolated data locations for one Raspberry Pi host."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import sqlite3

LINE_IDS = (1, 2, 3, 4, 5)


def validate_line_id(value) -> int:
    if isinstance(value, bool) or str(value) not in {str(n) for n in LINE_IDS}:
        raise ValueError('产线编号必须为 1～5 的整数')
    return int(value)


def configured_line_id() -> int:
    return validate_line_id(os.environ.get('PRODUCTION_LINE_ID', '1'))


def data_root() -> Path:
    return Path(os.environ.get('DASHBOARD_DATA_DIR', str(Path.home() / 'Database/vision-dashboard'))).expanduser().resolve()


def line_data_dir(base: Path, line_id: int) -> Path:
    return Path(base) / 'lines' / f'line_{validate_line_id(line_id)}'


def line_runtime_dir(base: Path, line_id: int) -> Path:
    return Path(base) / f'line_{validate_line_id(line_id)}'


@contextmanager
def migration_lock(base: Path):
    base.mkdir(parents=True, exist_ok=True)
    with (base / '.production_lines_migration.lock').open('a+') as handle:
        import fcntl
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def migrate_legacy_data(base: Path, line_id: int) -> None:
    """Copy the old single-line database/images once; retain originals for rollback."""
    marker = base / '.production_lines_migrated.json'
    with migration_lock(base):
        source = base / 'dashboard.sqlite3'
        if marker.exists() or not source.exists():
            return
        destination = line_data_dir(base, line_id)
        target = destination / 'dashboard.sqlite3'
        if target.exists():
            # Never merge historical rows into an already populated line.
            return
        destination.mkdir(parents=True, exist_ok=True)
        temporary = destination / 'migration.sqlite3'
        try:
            with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as old:
                with sqlite3.connect(temporary) as new:
                    old.backup(new)
            for name in ('media', 'archive', 'logs'):
                if (base / name).is_dir():
                    shutil.copytree(base / name, destination / name, dirs_exist_ok=True)
            temporary.replace(target)
            marker.write_text(json.dumps({'line_id': line_id, 'source': str(source)}, ensure_ascii=False))
        finally:
            temporary.unlink(missing_ok=True)


def migrate_legacy_runtime(base: Path, line_id: int) -> None:
    """Assign old camera artifacts to the initial active line only."""
    marker = base / '.production_lines_migrated.json'
    with migration_lock(base):
        if marker.exists():
            return
        destination = line_runtime_dir(base, line_id)
        for name in ('artifacts', 'logs'):
            source = base / name
            if source.is_dir():
                target = destination / name
                if target.exists():
                    raise ValueError(f'旧相机数据与产线数据同时存在，请先整理：{source}、{target}')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(target))
        marker.write_text(json.dumps({'line_id': line_id}, ensure_ascii=False))
