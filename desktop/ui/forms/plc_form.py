import time
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QMessageBox, QGroupBox,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt
from desktop.core.app_state import AppState
from backend.models import PLCInstance

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
        self.det_byte_input = QLineEdit()
        self.det_bit_input = QLineEdit()

        sig_layout.addWidget(QLabel("Lifebit Byte:"), 0, 0)
        sig_layout.addWidget(self.lb_byte_input, 0, 1)
        sig_layout.addWidget(QLabel("Lifebit Bit:"), 0, 2)
        sig_layout.addWidget(self.lb_bit_input, 0, 3)

        sig_layout.addWidget(QLabel("Tetik (Detection) Byte:"), 1, 0)
        sig_layout.addWidget(self.det_byte_input, 1, 1)
        sig_layout.addWidget(QLabel("Tetik (Detection) Bit:"), 1, 2)
        sig_layout.addWidget(self.det_bit_input, 1, 3)

        layout.addWidget(sig_group)


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
        # Merge defaults, prioritizing non-None values from existing_data
        default_obj = PLCInstance(id="tmp", name="Yeni PLC")
        d = default_obj.model_dump()
        for k, v in self.existing_data.items():
            if v is not None:
                d[k] = v

        self.name_input.setText(d.get("name") or "")
        self.enabled_check.setChecked(d.get("enabled"))
        self.ip_input.setText(d.get("ip"))

        self.rack_input.setText(str(d.get("rack")))
        self.slot_input.setText(str(d.get("slot")))
        self.db_input.setText(str(d.get("db_number")))

        self.lb_byte_input.setText(str(d.get("lifebit_byte")))
        self.lb_bit_input.setText(str(d.get("lifebit_bit")))
        self.det_byte_input.setText(str(d.get("detection_byte")))
        self.det_bit_input.setText(str(d.get("detection_bit")))


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
                "detection_byte": int(self.det_byte_input.text() or 0),
                "detection_bit": int(self.det_bit_input.text() or 0)
            }

            # Validate with Pydantic model
            plc_obj = PLCInstance(**data)
            
            if "instances" not in AppState.plc_config:
                AppState.plc_config["instances"] = {}

            AppState.plc_config["instances"][new_id] = plc_obj.model_dump()

            if not AppState.plc_config.get("default_plc_id"):
                AppState.plc_config["default_plc_id"] = new_id

            from backend.config import save_plc_config
            save_plc_config(AppState.plc_config)
            AppState.plc_mgr.set_config(AppState.plc_config)

            self.accept()
        except ValueError as e:
            QMessageBox.warning(self, "Hata", f"Geçersiz input: {e}")
        except Exception as e:
            QMessageBox.warning(self, "Hata", str(e))

class PLCManagerDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PLC Yönetimi")
        self.setMinimumWidth(400)
        self.setup_ui()
        self.populate()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        self.plc_list = QListWidget()
        layout.addWidget(QLabel("Kayıtlı PLC'ler:"))
        layout.addWidget(self.plc_list)

        btn_layout = QHBoxLayout()
        add_btn = QPushButton("PLC Ekle")
        add_btn.clicked.connect(self.add_plc)

        edit_btn = QPushButton("Düzenle")
        edit_btn.clicked.connect(self.edit_plc)

        del_btn = QPushButton("Sil")
        # del_btn.setStyleSheet("background-color: #ef4444; color: white;")
        del_btn.clicked.connect(self.delete_plc)

        close_btn = QPushButton("Kapat")
        close_btn.clicked.connect(self.accept)

        btn_layout.addWidget(add_btn)
        btn_layout.addWidget(edit_btn)
        btn_layout.addWidget(del_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def populate(self):
        self.plc_list.clear()
        instances = AppState.plc_config.get("instances", {})
        for plc_id, cfg in instances.items():
            name = cfg.get("name", plc_id)
            status = " [Aktif]" if cfg.get("enabled") else " [Pasif]"
            item = QListWidgetItem(f"{name}{status}")
            item.setData(Qt.UserRole, plc_id)
            self.plc_list.addItem(item)

    def add_plc(self):
        dialog = PLCFormDialog(self)
        if dialog.exec():
            self.populate()

    def edit_plc(self):
        item = self.plc_list.currentItem()
        if not item:
            return
        plc_id = item.data(Qt.UserRole)
        dialog = PLCFormDialog(self, plc_id=plc_id)
        if dialog.exec():
            self.populate()

    def delete_plc(self):
        item = self.plc_list.currentItem()
        if not item:
            return
        plc_id = item.data(Qt.UserRole)

        # Confirm
        name = AppState.plc_config["instances"][plc_id].get("name", plc_id)
        reply = QMessageBox.question(self, "Uyarı", f"'{name}' PLC'sini silmek istediğinizden emin misiniz?",
                                     QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            del AppState.plc_config["instances"][plc_id]
            if AppState.plc_config.get("default_plc_id") == plc_id:
                # Pick another one or None
                ids = list(AppState.plc_config["instances"].keys())
                AppState.plc_config["default_plc_id"] = ids[0] if ids else None

            from backend.config import save_plc_config
            save_plc_config(AppState.plc_config)
            AppState.plc_mgr.set_config(AppState.plc_config)
            self.populate()
