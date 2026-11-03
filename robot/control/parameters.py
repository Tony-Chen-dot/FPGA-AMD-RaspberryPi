"""Five-phase presets, validation and atomic parameter persistence."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import time
from common.paths import PROJECT_ROOT, ROBOT_PARAMS_PATH
from .hardware_lock import hardware_operation_lock
from .protocol import integer, POSITION_MIN, POSITION_MAX

POSES = {
    "pickup": [1500, 1223, 1722, 722, 1500],
    "right_transfer": [2033, 1500, 1722, 722, 1500],
    "left_transfer": [967, 1500, 1722, 722, 1500],
    "right_drop": [2033, 1033, 1622, 822, 1500],
    "left_drop": [967, 1033, 1622, 822, 1500],
    "reset": [1500, 1500, 1500, 1500, 1500],
}
LABELS = {"pickup": "吸取姿态 · Phase 0", "right_transfer": "右转移 · Phase 1",
          "left_transfer": "左转移 · Phase 1", "right_drop": "右下降 · Phase 2 / 3",
          "left_drop": "左下降 · Phase 2 / 3", "reset": "复位姿态 · Phase 4"}
DEFAULTS = {"poses": POSES, "manual_ms": 1000,
            "move_ms": [1000, 1000, 500, 500, 1000],
            "wait_ms": [1500, 1000, 500, 500, 1000]}

SETTINGS = ROBOT_PARAMS_PATH
LEGACY_SETTINGS = PROJECT_ROOT / "servo_dashboard" / "data" / "servo_params.json"

def validate(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("poses"), dict):
        raise ValueError("缺少姿态参数")
    result = {"poses": {}, "manual_ms": integer(raw.get("manual_ms"), 0, 9999)}
    for name in POSES:
        values = raw["poses"].get(name)
        if not isinstance(values, list) or len(values) != 5:
            raise ValueError(f"{name} 必须包含五个关节 P 位置")
        result["poses"][name] = [integer(v, POSITION_MIN, POSITION_MAX) for v in values]
    for key, limit in (("move_ms", 9999), ("wait_ms", 60000)):
        values = raw.get(key)
        if not isinstance(values, list) or len(values) != 5:
            raise ValueError(f"{key} 必须包含五个阶段")
        result[key] = [integer(v, 0, limit) for v in values]
    return result


def _write_params(path, params):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(params, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _legacy_angles(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get("poses"), dict):
        return False
    poses = raw["poses"]
    old_names = {"preparation", "forward", "left", "right"}
    if set(poses) != old_names or "manual_ms" in raw or "wait_ms" in raw:
        return False
    return all(isinstance(poses[name], dict) and all(f"s{i}" in poses[name] for i in range(1, 6))
               for name in old_names)


def load_params(path=SETTINGS):
    """Migrate recognized old angle files only; never silently use corrupt data."""
    path = Path(path).expanduser()
    if path.resolve() == SETTINGS.resolve():
        migrate_settings_location(LEGACY_SETTINGS, path)
    if not path.exists():
        return copy.deepcopy(DEFAULTS)
    # The settings lock is distinct from the hardware lock (no nested flock).
    with hardware_operation_lock(str(path) + ".lock"):
        raw_bytes = path.read_bytes()
        try:
            raw = json.loads(raw_bytes)
        except (ValueError, UnicodeError) as exc:
            raise ValueError(f"机械臂参数文件损坏，请检查 {path}: {exc}") from exc
        if _legacy_angles(raw):
            stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{time.time_ns()}"
            backup = path.with_name(path.name + ".legacy-angles-" + stamp + ".bak")
            backup.write_bytes(raw_bytes)
            defaults = copy.deepcopy(DEFAULTS)
            _write_params(path, defaults)
            print(f"[ARM] 旧角度参数已备份到 {backup}；切换为已验证的 FPGA P 值，未换算角度。", flush=True)
            return defaults
        try:
            return validate(raw)
        except ValueError as exc:
            raise ValueError(f"机械臂参数格式无效，请检查 {path}: {exc}") from exc


def migrate_settings_location(source, destination):
    """Copy calibrated UART settings once when upgrading an existing Pi checkout."""
    source, destination = Path(source), Path(destination)
    if destination.exists() or not source.exists():
        return False
    with hardware_operation_lock(str(destination) + ".lock"):
        if destination.exists():
            return False
        # Validate before writing; leave the original file intact for rollback.
        params = validate(json.loads(source.read_text(encoding="utf-8")))
        _write_params(destination, params)
        print(f"[ARM] 已迁移串口调试参数：{source} → {destination}", flush=True)
    return True


