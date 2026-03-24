import time
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QLineEdit, QPushButton, QComboBox, QCheckBox, QMessageBox, QGroupBox, QSpinBox,
    QDoubleSpinBox, QListWidget, QListWidgetItem, QColorDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from desktop.core.app_state import AppState

class CameraFormDialog(QDialog):
    def __init__(self, parent=None, camera_id=None):
        super().__init__(parent)
        self.setWindowTitle("Kamera Ayarları")
        self.setMinimumWidth(1050)
        self.camera_id = camera_id
        self.is_adding = camera_id is None

        self.existing_data = {}
        if not self.is_adding and camera_id in AppState.cameras:
            self.existing_data = AppState.cameras[camera_id]

        self.setup_ui()
        self.populate()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        # Four Column Layout
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
        self.enabled_check = QCheckBox("Kamera Aktif")
        self.enabled_check.setChecked(True)

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
        conn_layout.addWidget(self.enabled_check, 6, 0, 1, 2)
        cols_layout.addWidget(conn_group)

        # Column 2: AI Settings Group
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

        self.roi_btn = QPushButton("Bölge Seç")
        self.roi_btn.clicked.connect(self.open_roi_editor)
        ai_layout.addWidget(self.roi_btn, 5, 0, 1, 2)

        cols_layout.addWidget(ai_group)

        # Column 3: Image Settings Group (Görüntü Ayarları)
        img_group = QGroupBox("Görüntü Ayarları")
        img_layout = QVBoxLayout(img_group)

        # Alarm Flash Color Picker
        self.current_alarm_color = "#10B981"
        self.alarm_color_btn = QPushButton()
        self.alarm_color_btn.setFixedWidth(80)
        self.alarm_color_btn.setCursor(Qt.PointingHandCursor)
        self.alarm_color_btn.clicked.connect(self.pick_alarm_color)

        flash_layout = QHBoxLayout()
        flash_layout.addWidget(QLabel("Alarm Flash Rengi:"))
        flash_layout.addWidget(self.alarm_color_btn)
        flash_layout.addStretch()
        img_layout.addLayout(flash_layout)

        img_layout.addSpacing(10)

        self.blur_faces_checkbox = QCheckBox("Yüzleri Bulanıklaştır")
        img_layout.addWidget(self.blur_faces_checkbox)

        img_layout.addSpacing(10)

        crop_box = QGroupBox("Görüntü Kırpma (Gizlilik)")
        crop_v = QVBoxLayout(crop_box)
        self.crop_enabled_check = QCheckBox("Kırpmayı Etkinleştir")
        crop_v.addWidget(self.crop_enabled_check)

        crop_grid = QGridLayout()
        self.crop_x_input = QSpinBox(); self.crop_x_input.setRange(0, 10000)
        self.crop_y_input = QSpinBox(); self.crop_y_input.setRange(0, 10000)
        self.crop_w_input = QSpinBox(); self.crop_w_input.setRange(0, 10000)
        self.crop_h_input = QSpinBox(); self.crop_h_input.setRange(0, 10000)

        crop_grid.addWidget(QLabel("X:"), 0, 0); crop_grid.addWidget(self.crop_x_input, 0, 1)
        crop_grid.addWidget(QLabel("Y:"), 0, 2); crop_grid.addWidget(self.crop_y_input, 0, 3)
        crop_grid.addWidget(QLabel("W:"), 1, 0); crop_grid.addWidget(self.crop_w_input, 1, 1)
        crop_grid.addWidget(QLabel("H:"), 1, 2); crop_grid.addWidget(self.crop_h_input, 1, 3)
        crop_v.addLayout(crop_grid)

        self.visual_crop_btn = QPushButton("Görsel Olarak Seç")
        self.visual_crop_btn.clicked.connect(self.open_crop_visualizer)
        crop_v.addWidget(self.visual_crop_btn)

        img_layout.addWidget(crop_box)
        img_layout.addStretch()
        cols_layout.addWidget(img_group)

        # Column 4: PLC Settings Group
        plc_group = QGroupBox("PLC Ayarları")
        plc_layout = QVBoxLayout(plc_group)
        self.plc_list = QListWidget()
        plc_layout.addWidget(QLabel("Alarm seçilen PLC'lere gönderilir:"))
        plc_layout.addWidget(self.plc_list)
        cols_layout.addWidget(plc_group)

        # Bottom Buttons
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
        self.enabled_check.setChecked(bool(d.get("enabled", True)))

        self.model_size_combo.setCurrentText(d.get("model_size", "n"))
        self.custom_model_input.setText(d.get("custom_model", ""))
        self.detect_classes_input.setText(",".join(map(str, d.get("detect_classes", [0]))))
        self.frame_skip_input.setValue(int(d.get("frame_skip", 3)))
        self.confidence_input.setValue(float(d.get("confidence", 0.5)))
        self.blur_faces_checkbox.setChecked(bool(d.get("blur_faces", False)))
        self.current_alarm_color = d.get("alarm_color", "#10B981")
        self.update_color_button()
        self.update_roi_btn_text()

        self.crop_enabled_check.setChecked(bool(d.get("crop_enabled", False)))
        self.crop_x_input.setValue(int(d.get("crop_x", 0)))
        self.crop_y_input.setValue(int(d.get("crop_y", 0)))
        self.crop_w_input.setValue(int(d.get("crop_w", 0)))
        self.crop_h_input.setValue(int(d.get("crop_h", 0)))

        # PLC checklist
        self.plc_list.clear()
        current_plc_outputs = d.get("plc_outputs", [])
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

            if not self.ip_input.text().strip(): raise ValueError("IP Adresi boş olamaz.")
            if not self.password_input.text().strip(): raise ValueError("Kamera parolası boş olamaz.")

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
                "enabled": self.enabled_check.isChecked(),
                "crop_enabled": self.crop_enabled_check.isChecked(),
                "crop_x": self.crop_x_input.value(),
                "crop_y": self.crop_y_input.value(),
                "crop_w": self.crop_w_input.value(),
                "crop_h": self.crop_h_input.value(),
                "alarm_color": self.current_alarm_color,
                "detect_classes": parse_classes(self.detect_classes_input.text()),
                "custom_model": self.custom_model_input.text() or None,
                "plc_outputs": [],
                "roi": self.existing_data.get("roi", None),
                "zones": self.existing_data.get("zones", None)
            }

            existing_outputs = {o["plc_id"]: o for o in self.existing_data.get("plc_outputs", []) if "plc_id" in o}
            for i in range(self.plc_list.count()):
                item = self.plc_list.item(i)
                if item.checkState() == Qt.Checked:
                    plc_id = item.data(Qt.UserRole)
                    if plc_id in existing_outputs: cam_data["plc_outputs"].append(existing_outputs[plc_id])
                    else: cam_data["plc_outputs"].append({"plc_id": plc_id})

            from backend.models import CameraConfig
            cfg = CameraConfig(**cam_data)
            cam_data["url"] = cfg.get_rtsp_url()
            AppState.cameras[req_id] = cam_data

            from backend.config import save_cameras
            save_cameras(AppState.cameras)
            AppState.plc_mgr.set_cameras(AppState.cameras)

            if self.is_adding:
                if cam_data["enabled"]:
                    AppState.process_mgr.start_camera(cam_data)
            else:
                old = self.existing_data
                was_enabled = old.get("enabled", True)
                is_enabled = cam_data["enabled"]

                if was_enabled and not is_enabled:
                    AppState.process_mgr.stop_camera(req_id)
                elif not was_enabled and is_enabled:
                    AppState.process_mgr.start_camera(cam_data)
                elif is_enabled:
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
                    else:
                        AppState.process_mgr.send_command(req_id, {
                            "cmd": "update_config",
                            "confidence": cam_data["confidence"],
                            "frame_skip": cam_data["frame_skip"],
                            "blur_faces": cam_data["blur_faces"],
                            "detect_classes": cam_data["detect_classes"],
                            "crop_enabled": cam_data["crop_enabled"],
                            "crop_x": cam_data["crop_x"],
                            "crop_y": cam_data["crop_y"],
                            "crop_w": cam_data["crop_w"],
                            "crop_h": cam_data["crop_h"],
                        })
            AppState.plc_mgr.set_event_queues(AppState.process_mgr.event_queues)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Validation Error", str(e))

    def update_roi_btn_text(self):
        d = self.existing_data
        has_roi = bool(d.get("roi"))
        has_zones = bool(d.get("zones"))
        if has_roi or has_zones:
            self.roi_btn.setText("Bölge Düzenle")
        else:
            self.roi_btn.setText("Bölge Seç")

    def open_roi_editor(self):
        if self.is_adding:
            QMessageBox.information(self, "Bilgi", "Bölge seçimi için önce kamerayı kaydedin.")
            return
        from desktop.ui.forms.roi_form import RoiEditorDialog
        dialog = RoiEditorDialog(self, camera_id=self.camera_id)
        if dialog.exec():
            # Refresh from AppState since RoiEditorDialog saves there
            if self.camera_id in AppState.cameras:
                self.existing_data = AppState.cameras[self.camera_id]
                self.update_roi_btn_text()

    def open_crop_visualizer(self):
        if self.is_adding:
            QMessageBox.information(self, "Bilgi", "Kırpma için önce kamerayı kaydedin.")
            return
        from desktop.ui.forms.crop_form import CropEditorDialog
        cur = (self.crop_x_input.value(), self.crop_y_input.value(), self.crop_w_input.value(), self.crop_h_input.value())
        dialog = CropEditorDialog(self, camera_id=self.camera_id, current_rect=cur)
        if dialog.exec():
            x, y, w, h = dialog.result_rect
            self.crop_x_input.setValue(x)
            self.crop_y_input.setValue(y)
            self.crop_w_input.setValue(w)
            self.crop_h_input.setValue(h)

    def pick_alarm_color(self):
        color = QColorDialog.getColor(QColor(self.current_alarm_color), self, "Alarm Rengi Seç")
        if color.isValid():
            self.current_alarm_color = color.name().upper()
            self.update_color_button()

    def update_color_button(self):
        # Contrasting text color based on background luminance
        c = QColor(self.current_alarm_color)
        lum = (0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()) / 255
        text_color = "#000000" if lum > 0.5 else "#FFFFFF"
        
        self.alarm_color_btn.setText(self.current_alarm_color)
        self.alarm_color_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {self.current_alarm_color};
                color: {text_color};
                border: 1px solid #374151;
                border-radius: 4px;
                font-weight: bold;
                padding: 4px;
            }}
            QPushButton:hover {{
                border: 2px solid #50e3c2;
            }}
        """)
