"""Configuration persistence for cameras and PLC."""

import json
import logging
import os
import urllib.parse

logger = logging.getLogger(__name__)

import sys

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BACKEND_DIR)

# Production-safe Data Directory strategy
if os.environ.get("VSAFE_DATA_DIR"):
    DATA_DIR = os.environ.get("VSAFE_DATA_DIR")
elif getattr(sys, 'frozen', False):
    # If running as a frozen executable (PyInstaller)
    if os.name == 'nt': # Windows
        DATA_DIR = os.path.join(os.environ.get('APPDATA', 'C:/Temp'), 'VDetect')
    else: # Linux
        DATA_DIR = os.path.expanduser('~/.local/share/v-detect')
else:
    # Development mode: local data/ folder
    DATA_DIR = os.path.join(ROOT_DIR, "data")

os.makedirs(DATA_DIR, exist_ok=True)

MODELS_DIR = os.path.join(DATA_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# Path for bundled models (read-only fallbacks)
BUNDLED_MODELS_DIR = None
if getattr(sys, 'frozen', False):
    # PyInstaller temporary path for bundled assets
    BUNDLED_MODELS_DIR = os.path.join(sys._MEIPASS, "data", "models")

# Path for static files (remains in backend)
BASE_DIR = BACKEND_DIR

CAMERAS_DB_FILE = os.path.join(DATA_DIR, "cameras_db.json")
PLC_CONFIG_FILE = os.path.join(DATA_DIR, "plc_config.json")
PLCS_DB_FILE = os.path.join(DATA_DIR, "plcs_db.json")
CAPTURES_DIR = os.path.join(DATA_DIR, "captures")
EVENTS_DB_PATH = os.path.join(DATA_DIR, "events.db")

# --- Camera config ---
def load_cameras() -> dict[str, dict]:
    from backend.models import CameraConfig
    if not os.path.exists(CAMERAS_DB_FILE):
        logger.info("No cameras database found, starting fresh")
        return {}

    try:
        with open(CAMERAS_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        cameras: dict[str, dict] = {}
        for cam_id, cam_data in data.items():
            # Validate and apply defaults via Pydantic
            cfg = CameraConfig(**cam_data)
            dump = cfg.model_dump()
            dump["url"] = cfg.get_rtsp_url()
            cameras[cam_id] = dump

        logger.info("Loaded %d cameras from database", len(cameras))
        return cameras
    except Exception as e:
        logger.error("Error loading cameras: %s", e)
        return {}


def save_cameras(cameras: dict[str, dict]) -> None:
    try:
        data = {}
        for cam_id, cam_data in cameras.items():
            data[cam_id] = {k: v for k, v in cam_data.items() if k != "url"}

        with open(CAMERAS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Saved %d cameras to database", len(cameras))
    except Exception as e:
        logger.error("Error saving cameras: %s", e)


# --- PLC config (Multi-PLC support) ---
def load_plc_config() -> dict:
    """Loads the multi-PLC database. Validates via PLCConfig model."""
    from backend.models import PLCConfig
    if not os.path.exists(PLCS_DB_FILE):
        return PLCConfig().model_dump()

    try:
        with open(PLCS_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Validate and apply defaults
        return PLCConfig(**data).model_dump()
    except Exception as e:
        logger.error("Error loading plcs_db.json: %s", e)
        return PLCConfig().model_dump()


def save_plc_config(config: dict) -> dict:
    """Saves the multi-PLC database."""
    try:
        with open(PLCS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("PLC database saved")
    except Exception as e:
        logger.error("Error saving PLC database: %s", e)
    return config


