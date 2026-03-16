import time
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QMessageBox, QGroupBox,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt
from desktop.core.app_state import AppState

class PLCFormDialog(QDialog):
    def __init__(self, parent=None, plc_id=None):
        super().__init__(parent)
        self.setWindowTitle("PLC Ayarları")
        self.setMinimumWidth(400)
        self.plc_id = plc_id
        self.is_adding = plc_id is None

        # Load existing
        self.existing_data = {}
        if not self.is_adding and plc_id in AppState.plc_config.get("instances", {}):
            self.existing_data = AppState.plc_config["instances"][plc_id]

        self.setup_ui()
        self.populate()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        # Name & Enable
        self.name_input = QLineEdit()
        self.enabled_check = QCheckBox("Aktif")

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Adı:"))
        name_layout.addWidget(self.name_input)
        name_layout.addWidget(self.enabled_check)
        layout.addLayout(name_layout)

        # Network Group
        net_group = QGroupBox("Bağlantı Ayarları")
        net_layout = QGridLayout(net_group)

        self.ip_input = QLineEdit()
        self.rack_input = QLineEdit()
        self.slot_input = QLineEdit()
        self.db_input = QLineEdit()

        net_layout.addWidget(QLabel("IP Adresi:"), 0, 0)
        net_layout.addWidget(self.ip_input, 0, 1)
        net_layout.addWidget(QLabel("Rack:"), 1, 0)
        net_layout.addWidget(self.rack_input, 1, 1)
        net_layout.addWidget(QLabel("Slot:"), 2, 0)
        net_layout.addWidget(self.slot_input, 2, 1)
        net_layout.addWidget(QLabel("DB Numarası:"), 3, 0)
        net_layout.addWidget(self.db_input, 3, 1)
        layout.addWidget(net_group)

        # Signal Group
        sig_group = QGroupBox("Haberleşme Ayarları")
        sig_layout = QGridLayout(sig_group)

        self.lb_byte_input = QLineEdit()
        self.lb_bit_input = QLineEdit()
        self.person_byte_input = QLineEdit()
        self.person_bit_input = QLineEdit()

        sig_layout.addWidget(QLabel("Lifebit Byte:"), 0, 0)
        sig_layout.addWidget(self.lb_byte_input, 0, 1)
        sig_layout.addWidget(QLabel("Lifebit Bit:"), 0, 2)
        sig_layout.addWidget(self.lb_bit_input, 0, 3)

        sig_layout.addWidget(QLabel("Alarm Byte:"), 1, 0)
        sig_layout.addWidget(self.person_byte_input, 1, 1)
        sig_layout.addWidget(QLabel("Alarm Bit:"), 1, 2)
        sig_layout.addWidget(self.person_bit_input, 1, 3)

        layout.addWidget(sig_group)

        # Camera Mapping Group (Many-to-Many)
        map_group = QGroupBox("Kamera Eşleştirme")
        map_layout = QVBoxLayout(map_group)
        self.cam_list = QListWidget()
        map_layout.addWidget(QLabel("Bu PLC'yi tetikleyecek kameraları seçin:"))
        map_layout.addWidget(self.cam_list)
        layout.addWidget(map_group)

        # Actions
        btn_layout = QHBoxLayout()
        save_btn = QPushButton("Kaydet")
        save_btn.clicked.connect(self.save)
        cancel_btn = QPushButton("İptal")
        cancel_btn.clicked.connect(self.reject)

        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def populate(self):
        d = self.existing_data
        self.name_input.setText(d.get("name", "New PLC"))
        self.enabled_check.setChecked(d.get("enabled", True))
        self.ip_input.setText(d.get("ip", "192.168.0.50"))

        self.rack_input.setText(str(d.get("rack", 0)))
        self.slot_input.setText(str(d.get("slot", 1)))
        self.db_input.setText(str(d.get("db_number", 0)))

        self.lb_byte_input.setText(str(d.get("lifebit_byte", 0)))
        self.lb_bit_input.setText(str(d.get("lifebit_bit", 0)))
        self.person_byte_input.setText(str(d.get("person_byte", 0)))
        self.person_bit_input.setText(str(d.get("person_bit", 0)))

        # Populate camera list
        self.cam_list.clear()
        mappings = d.get("camera_mappings", {})
        for cam_id, cam_cfg in AppState.cameras.items():
            cam_name = cam_cfg.get("name", cam_id)
            item = QListWidgetItem(cam_name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            # Set initial check state
            check_state = Qt.Checked if cam_id in mappings else Qt.Unchecked
            item.setCheckState(check_state)
            item.setData(Qt.UserRole, cam_id)
            self.cam_list.addItem(item)

    def save(self):
        try:
            new_id = self.plc_id or f"plc_{int(time.time())}"
            data = {
                "id": new_id,
                "name": self.name_input.text(),
                "enabled": self.enabled_check.isChecked(),
                "ip": self.ip_input.text(),
                "rack": int(self.rack_input.text() or 0),
                "slot": int(self.slot_input.text() or 0),
                "db_number": int(self.db_input.text() or 0),
                "lifebit_byte": int(self.lb_byte_input.text() or 0),
                "lifebit_bit": int(self.lb_bit_input.text() or 0),
                "person_byte": int(self.person_byte_input.text() or 0),
                "person_bit": int(self.person_bit_input.text() or 0),
                "camera_mappings": {} # Rebuilt below
            }

            # Rebuild mappings from checked items
            for i in range(self.cam_list.count()):
                item = self.cam_list.item(i)
                if item.checkState() == Qt.Checked:
                    cam_id = item.data(Qt.UserRole)
                    data["camera_mappings"][cam_id] = True # Basic mapping

            if "instances" not in AppState.plc_config:
                AppState.plc_config["instances"] = {}

            AppState.plc_config["instances"][new_id] = data

            if not AppState.plc_config.get("default_plc_id"):
                AppState.plc_config["default_plc_id"] = new_id

            from backend.config import save_plc_config
            save_plc_config(AppState.plc_config)
            AppState.plc_mgr.set_config(AppState.plc_config)

            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Invalid input", str(e))
