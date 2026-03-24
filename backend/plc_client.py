"""Siemens S7 PLC communication via snap7."""

import logging

logger = logging.getLogger(__name__)

try:
    import snap7
    import snap7.util

    SNAP7_AVAILABLE = True
except ImportError:
    SNAP7_AVAILABLE = False


class LifeBit:
    """Toggles a boolean each cycle to signal the PLC that the system is alive."""

    def __init__(self):
        self.state = False

    def toggle(self) -> bool:
        self.state = not self.state
        return self.state


def connect_plc(config: dict):
    """Return a connected snap7 Client, or None on failure."""
    if not SNAP7_AVAILABLE:
        logger.debug("snap7 not installed — PLC disabled")
        return None
    if not config.get("enabled"):
        return None
    try:
        plc = snap7.client.Client()
        plc.connect(config["ip"], config["rack"], config["slot"])
        logger.info("PLC connected: %s", config["ip"])
        return plc
    except Exception as e:
        logger.error("PLC connection error: %s", e)
        return None




def update_plc(
    plc,
    config: dict,
    lifebit_value: bool,
    detection_active: bool,
    camera_states: dict[str, bool] | None = None,
    cameras_cfg: dict[str, dict] | None = None,
):
    """Write lifebit + aggregate detection status + per-camera bits to the PLC.
    Groups writes by (DB, byte index) to prevent bit-overwrite and reduce network calls.
    """
    global_db = config["db_number"]
    plc_id = config.get("id")
    writes = {}  # (db_number, byte_idx) -> bytearray(1)

    def set_bit(db, byte_idx, bit_idx, value):
        key = (db, byte_idx)
        if key not in writes:
            writes[key] = bytearray(1)
        snap7.util.set_bool(writes[key], 0, bit_idx, value)

    # 1. Main signals (global DB)
    set_bit(global_db, config["lifebit_byte"], config["lifebit_bit"], lifebit_value)
    set_bit(global_db, config["detection_byte"], config["detection_bit"], detection_active)

    # 2. Per-camera signals from Camera config (Many-to-Many explicit outputs)
    if cameras_cfg and camera_states:
        for cam_id, cam_data in cameras_cfg.items():
            val = camera_states.get(cam_id, False)
            outputs = cam_data.get("plc_outputs") or []
            for out in outputs:
                if out.get("plc_id") == plc_id:
                    target_db = out.get("db_number") or global_db
                    byte_idx = out.get("byte_idx")
                    bit_idx = out.get("bit_idx")
                    
                    if byte_idx is not None and bit_idx is not None:
                        set_bit(target_db, byte_idx, bit_idx, val)

    # 4. Batch write each modified (DB, byte)
    for (db, byte_idx), data in writes.items():
        plc.db_write(db, byte_idx, data)


def check_connection(config: dict) -> bool:
    """Quick connectivity check — returns True if the PLC is reachable."""
    if not SNAP7_AVAILABLE:
        return False
    try:
        plc = snap7.client.Client()
        plc.connect(config["ip"], config["rack"], config["slot"])
        ok = plc.get_connected()
        plc.disconnect()
        plc.destroy()
        return ok
    except Exception:
        return False
