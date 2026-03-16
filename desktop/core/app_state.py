import os
import sys

# Add root folder to sys.path so we can natively import `backend` modules
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, base_dir)
sys.path.insert(1, os.path.join(base_dir, "backend"))

from backend.process_manager import ProcessManager
from backend.plc_manager import PLCManager
from backend.event_store import EventStore
from backend.config import load_cameras, load_plc_config, CAPTURES_DIR, EVENTS_DB_PATH

class AppState:
    process_mgr = ProcessManager(img_path=CAPTURES_DIR)
    plc_mgr = PLCManager()
    event_store = EventStore(EVENTS_DB_PATH)
    cameras = load_cameras()
    plc_config = load_plc_config()
    
    @classmethod
    def init(cls):
        cls.plc_mgr.set_config(cls.plc_config)
        cls.plc_mgr.set_cameras(cls.cameras)
        cls.plc_mgr.set_event_store(cls.event_store)
