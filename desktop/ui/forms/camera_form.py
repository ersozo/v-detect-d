import time
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QMessageBox, QGroupBox, QSpinBox, 
    QDoubleSpinBox, QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt
from desktop.core.app_state import AppState

class CameraFormDialog(QDialog):
    def __init__(self, parent=None, camera_id=None):
        super().__init__(parent)
        self.setWindowTitle("Kamera Ayarları")
        self.setMinimumWidth(600)
        self.camera_id = camera_id
        self.is_adding = camera_id is None

        self.existing_data = {}
        if not self.is_adding and camera_id in AppState.cameras:
            self.existing_data = AppState.cameras[camera_id]

        self.setup_ui()
        self.populate()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        # Three Column Layout
        cols_layout = QHBoxLayout()
        layout.addLayout(cols_layout)

        # Column 1: Connection Group
        conn_group = QGroupBox("Bağlantı Ayarları")
        conn_layout = QGridLayout(conn_group)

        self.name_input = QLineEdit()
        self.ip_input = QLineEdit()
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.username_input = QLineEdit()
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.stream_path_input = QLineEdit()

        conn_layout.addWidget(QLabel("Adı:"), 0, 0)
        conn_layout.addWidget(self.name_input, 0, 1)
        conn_layout.addWidget(QLabel("IP Adresi:"), 1, 0)
        conn_layout.addWidget(self.ip_input, 1, 1)
        conn_layout.addWidget(QLabel("Port:"), 2, 0)
        conn_layout.addWidget(self.port_input, 2, 1)
        conn_layout.addWidget(QLabel("Kullanıcı Adı:"), 3, 0)
        conn_layout.addWidget(self.username_input, 3, 1)
        conn_layout.addWidget(QLabel("Parola:"), 4, 0)
        conn_layout.addWidget(self.password_input, 4, 1)
        conn_layout.addWidget(QLabel("RTSP Yolu:"), 5, 0)
        conn_layout.addWidget(self.stream_path_input, 5, 1)

        cols_layout.addWidget(conn_group)

        # Column 2: AI Group
        ai_group = QGroupBox("Yapay Zeka Ayarları")
        ai_layout = QGridLayout(ai_group)

        self.model_size_combo = QComboBox()
        self.model_size_combo.addItems(["n", "s", "m", "l", "x"])

        self.custom_model_input = QLineEdit()
        self.detect_classes_input = QLineEdit()
        self.detect_classes_input.setPlaceholderText("örn. 0,2,7")

        self.frame_skip_input = QSpinBox()
        self.frame_skip_input.setRange(0, 100)

        self.confidence_input = QDoubleSpinBox()
        self.confidence_input.setRange(0.01, 1.0)
        self.confidence_input.setSingleStep(0.05)

        self.blur_faces_checkbox = QCheckBox("Yüzleri Bulanıklaştır")

        ai_layout.addWidget(QLabel("YOLO Model:"), 0, 0)
        ai_layout.addWidget(self.model_size_combo, 0, 1)
        ai_layout.addWidget(QLabel("Özel Model:"), 1, 0)
        ai_layout.addWidget(self.custom_model_input, 1, 1)
        ai_layout.addWidget(QLabel("Sınıf ID:"), 2, 0)
        ai_layout.addWidget(self.detect_classes_input, 2, 1)
        ai_layout.addWidget(QLabel("Kare Atla:"), 3, 0)
        ai_layout.addWidget(self.frame_skip_input, 3, 1)
        ai_layout.addWidget(QLabel("Güven:"), 4, 0)
        ai_layout.addWidget(self.confidence_input, 4, 1)
        ai_layout.addWidget(self.blur_faces_checkbox, 5, 0, 1, 2)

        cols_layout.addWidget(ai_group)

        # Column 3: PLC Group
        plc_group = QGroupBox("PLC Ayarları")
        plc_layout = QVBoxLayout(plc_group)

        self.plc_list = QListWidget()
        plc_layout.addWidget(QLabel("Alarm gönderilecek PLC'leri seçin:"))
        plc_layout.addWidget(self.plc_list)

        cols_layout.addWidget(plc_group)

        # Button box
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
        self.name_input.setText(d.get("name", ""))
        self.ip_input.setText(d.get("ip", ""))
        self.port_input.setValue(int(d.get("port", 554)))
        self.username_input.setText(d.get("username", "admin"))
        self.password_input.setText(d.get("password", ""))
        self.stream_path_input.setText(d.get("stream_path", ""))

        self.model_size_combo.setCurrentText(d.get("model_size", "n"))
        self.custom_model_input.setText(d.get("custom_model", ""))
        self.detect_classes_input.setText(",".join(map(str, d.get("detect_classes", [0]))))
        self.frame_skip_input.setValue(int(d.get("frame_skip", 3)))
        self.confidence_input.setValue(float(d.get("confidence", 0.5)))
        self.blur_faces_checkbox.setChecked(bool(d.get("blur_faces", False)))

        # Populate PLC checklist
        self.plc_list.clear()
        current_plc_outputs = d.get("plc_outputs", [])
        # Extract PLC IDs from current outputs list
        mapped_plc_ids = [o.get("plc_id") for o in current_plc_outputs if o.get("plc_id")]
        
        instances = AppState.plc_config.get("instances", {})
        for plc_id, plc_cfg in instances.items():
            item = QListWidgetItem(plc_cfg.get("name", plc_id))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            check_state = Qt.Checked if plc_id in mapped_plc_ids else Qt.Unchecked
            item.setCheckState(check_state)
            item.setData(Qt.UserRole, plc_id)
            self.plc_list.addItem(item)

    def save(self):
        try:
            req_id = self.camera_id or f"cam_{int(time.time()*1000)}"

            def parse_classes(text):
                return [int(x.strip()) for x in text.split(",") if x.strip().isdigit()]

            cam_data = {
                "id": req_id,
                "name": self.name_input.text(),
                "ip": self.ip_input.text(),
                "port": self.port_input.value(),
                "username": self.username_input.text(),
                "password": self.password_input.text(),
                "stream_path": self.stream_path_input.text(),
                "model_size": self.model_size_combo.currentText(),
                "frame_skip": self.frame_skip_input.value(),
                "confidence": self.confidence_input.value(),
                "blur_faces": self.blur_faces_checkbox.isChecked(),
                "detect_classes": parse_classes(self.detect_classes_input.text()),
                "custom_model": self.custom_model_input.text() or None,
                "plc_outputs": [], # Rebuilt below
                "roi": self.existing_data.get("roi", None),
                "zones": self.existing_data.get("zones", None)
            }

            # Rebuild PLC mappings
            for i in range(self.plc_list.count()):
                item = self.plc_list.item(i)
                if item.checkState() == Qt.Checked:
                    plc_id = item.data(Qt.UserRole)
                    cam_data["plc_outputs"].append({"plc_id": plc_id})

            from backend.models import CameraConfig
            cfg = CameraConfig(**cam_data)
            cam_data["url"] = cfg.get_rtsp_url()

            AppState.cameras[req_id] = cam_data

            from backend.config import save_cameras
            save_cameras(AppState.cameras)
            AppState.plc_mgr.set_cameras(AppState.cameras)

            # Hot-reload / restart handling
            if self.is_adding:
                AppState.process_mgr.start_camera(cam_data)
                AppState.plc_mgr.set_event_queues(AppState.process_mgr.event_queues)
            else:
                old = self.existing_data
                needs_restart = any([
                    old.get("ip") != cam_data["ip"],
                    old.get("port") != cam_data["port"],
                    old.get("username") != cam_data["username"],
                    old.get("password") != cam_data["password"],
                    old.get("stream_path") != cam_data["stream_path"],
                    old.get("model_size") != cam_data["model_size"],
                    old.get("custom_model") != cam_data["custom_model"],
                ])

                if needs_restart:
                    AppState.process_mgr.stop_camera(req_id)
                    AppState.process_mgr.start_camera(cam_data)
                    AppState.plc_mgr.set_event_queues(AppState.process_mgr.event_queues)
                else:
                    AppState.process_mgr.send_command(req_id, {
                        "cmd": "update_config",
                        "confidence": cam_data["confidence"],
                        "frame_skip": cam_data["frame_skip"],
                        "blur_faces": cam_data["blur_faces"],
                        "detect_classes": cam_data["detect_classes"],
                    })

            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Validation Error", str(e))
