import json
import os
import uuid

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLC_CONFIG_FILE = os.path.join(BASE_DIR, "plc_config.json")
PLCS_DB_FILE = os.path.join(BASE_DIR, "plcs_db.json")

def migrate():
    # Only migrate if the new DB doesn't exist yet
    if os.path.exists(PLCS_DB_FILE):
        print("plcs_db.json already exists. Skipping migration.")
        return

    # default structure in case plc_config.json is missing
    default_single = {
        "enabled": False,
        "ip": "192.168.0.50",
        "rack": 0,
        "slot": 1,
        "db_number": 38,
        "lifebit_byte": 4,
        "lifebit_bit": 0,
        "person_byte": 6,
        "person_bit": 0,
        "camera_mappings": {},
    }

    config_to_migrate = default_single
    if os.path.exists(PLC_CONFIG_FILE):
        try:
            with open(PLC_CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
            config_to_migrate = {**default_single, **saved}
            print("Found existing plc_config.json, migrating...")
        except Exception as e:
            print(f"Error reading plc_config.json: {e}")

    # Create a new multi-PLC structure
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

    try:
        with open(PLCS_DB_FILE, "w", encoding="utf-8") as f:
            json.dump(new_db, f, indent=2, ensure_ascii=False)
        print(f"Migration successful! New PLC ID: {plc_id}")
    except Exception as e:
        print(f"Error saving plcs_db.json: {e}")

if __name__ == "__main__":
    migrate()
