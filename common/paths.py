"""Repository-relative paths shared by services; independent of working directory."""
from pathlib import Path
from common.production_lines import configured_line_id, line_runtime_dir

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "runtime"
ROBOT_PARAMS_PATH = RUNTIME_DIR / "robot" / "servo_params.json"
VISION_RUNTIME_DIR = line_runtime_dir(RUNTIME_DIR / "vision", configured_line_id())
