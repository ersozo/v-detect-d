"""Configuration persistence for cameras and PLC."""

import json
import logging
import os
import urllib.parse

logger = logging.getLogger(__name__)

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BACKEND_DIR)
# In Docker, we can use /app/data. Locally, it's ./data/
DATA_DIR = os.environ.get("VSAFE_DATA_DIR", os.path.join(ROOT_DIR, "data"))

# Ensure directories exist
os.makedirs(DATA_DIR, exist_ok=True)

MODELS_DIR = os.path.join(DATA_DIR, "models")
os.makedirs(MODELS_DIR, exist_ok=True)

# Path for static files (remains in backend)
BASE_DIR = BACKEND_DIR

CAMERAS_DB_FILE = os.path.join(DATA_DIR, "cameras_db.json")
PLC_CONFIG_FILE = os.path.join(DATA_DIR, "plc_config.json")
PLCS_DB_FILE = os.path.join(DATA_DIR, "plcs_db.json")
CAPTURES_DIR = os.path.join(DATA_DIR, "captures")
EVENTS_DB_PATH = os.path.join(DATA_DIR, "events.db")

DEFAULT_PLC_CONFIG = {
    "enabled": False,
    "ip": "192.168.0.50",
    "rack": 0,
    "slot": 1,
    "db_number": 38,
    "lifebit_byte": 4,
    "lifebit_bit": 0,
    "detection_byte": 6,
    "detection_bit": 0,
    "camera_mappings": {},
}


def _build_rtsp_url(cam_data: dict) -> str:
    username = urllib.parse.quote(cam_data.get("username", ""))
    password = urllib.parse.quote(cam_data.get("password", ""))
    ip = cam_data.get("ip", "")
    port = cam_data.get("port", 554)
    stream_path = cam_data.get("stream_path", "")

    if username and password:
        auth = f"{username}:{password}@"
    elif username:
        auth = f"{username}@"
    else:
        auth = ""

    path = (
        stream_path
        if stream_path.startswith("/")
        else f"/{stream_path}" if stream_path else ""
    )
    return f"rtsp://{auth}{ip}:{port}{path}"


# --- Camera config ---


def load_cameras() -> dict[str, dict]:
    if not os.path.exists(CAMERAS_DB_FILE):
        logger.info("No cameras database found, starting fresh")
        return {}

    try:
        with open(CAMERAS_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        cameras: dict[str, dict] = {}
        for cam_id, cam_data in data.items():
            cam_data["url"] = _build_rtsp_url(cam_data)
            cameras[cam_id] = cam_data

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
    """Loads the multi-PLC database. Migrates from single config if needed."""
    if not os.path.exists(PLCS_DB_FILE):
        return _migrate_from_single_config()

    try:
        with open(PLCS_DB_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.error("Error loading plcs_db.json: %s", e)
        return {"instances": {}, "default_plc_id": None}


def save_plc_config(config: dict) -> dict:
    """Saves the multi-PLC database."""
    try:
        with open(PLCS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("PLC database saved")
    except Exception as e:
        logger.error("Error saving PLC database: %s", e)
    return config


def _migrate_from_single_config() -> dict:
    """Helper to migrate existing single PLC config to the new structure."""
    import uuid

    config_to_migrate = dict(DEFAULT_PLC_CONFIG)
    if os.path.exists(PLC_CONFIG_FILE):
        try:
            with open(PLC_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config_to_migrate = {**DEFAULT_PLC_CONFIG, **saved}
            logger.info("Migrated existing plc_config.json to new multi-PLC format")
        except Exception as e:
            logger.error("Error reading single plc_config.json for migration: %s", e)

    plc_id = "default_" + str(uuid.uuid4())[:8]
    new_db = {
        "instances": {
            plc_id: {
                "id": plc_id,
                "name": "Default PLC",
                **config_to_migrate
            }
        },
        "default_plc_id": plc_id
    }

    save_plc_config(new_db)
    return new_db
