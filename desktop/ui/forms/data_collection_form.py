from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QComboBox, QSpinBox, QGroupBox
)
from desktop.core.app_state import AppState

class DataCollectionFormDialog(QDialog):
    def __init__(self, parent=None, camera_id=None):
        super().__init__(parent)
        self.setWindowTitle("Veri Toplama Ayarları")
        self.setMinimumWidth(300)
        self.camera_id = camera_id
        
        # Load existing
        self.existing_data = {}
        cam_data = AppState.cameras.get(camera_id, {})
        self.existing_data = cam_data.get("data_collection") or {
            "enabled": False,
            "mode": "frames",
            "interval": 5
        }
        if isinstance(self.existing_data, object) and hasattr(self.existing_data, 'dict'):
             self.existing_data = self.existing_data.dict()

        self.setup_ui()
        self.populate()

    def setup_ui(self):
        layout = QVBoxLayout(self)

        group = QGroupBox("Veri Toplama Parametreleri")
        g_layout = QVBoxLayout(group)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Kare Kaydet (Frames)", "Video Kaydet (Video)"])
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)
        # Note: Video recording might be harder to implement in the leaky-queue architecture 
        # but we can support it in camera_process if we use cv2.VideoWriter

        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 1000)
        self.interval_spin.setSuffix(" karede bir")

        g_layout.addWidget(QLabel("Kayıt Modu:"))
        g_layout.addWidget(self.mode_combo)
        self.interval_label = QLabel("Kayıt Sıklığı:")
        g_layout.addWidget(self.interval_label)
        g_layout.addWidget(self.interval_spin)
        
        info_label = QLabel("ℹ <i>Kayıt sırasında CPU tasarrufu için AI tespiti otomatik olarak durdurulur.</i>")
        info_label.setWordWrap(True)
        info_label.setStyleSheet("color: #6b7280; margin-top: 10px;")
        g_layout.addWidget(info_label)

        layout.addWidget(group)

        # Buttons
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
        mode = d.get("mode", "frames")
        self.mode_combo.setCurrentIndex(0 if mode == "frames" else 1)
        self.interval_spin.setValue(d.get("interval", 5))
        self.on_mode_changed(self.mode_combo.currentIndex())

    def on_mode_changed(self, index):
        is_frames = (index == 0)
        self.interval_spin.setVisible(is_frames)
        self.interval_label.setVisible(is_frames)

    def save(self):
        mode = "frames" if self.mode_combo.currentIndex() == 0 else "video"
        
        new_config = {
            "enabled": self.existing_data.get("enabled", False),
            "mode": mode,
            "interval": self.interval_spin.value()
        }
        
        # Update AppState
        if self.camera_id in AppState.cameras:
            AppState.cameras[self.camera_id]["data_collection"] = new_config
            
            # Save to disk
            from backend.config import save_cameras
            save_cameras(AppState.cameras)
            
            # Update running process if enabled
            if AppState.cameras[self.camera_id].get("enabled"):
                AppState.process_mgr.send_command(self.camera_id, {
                    "cmd": "update_data_collection",
                    "config": new_config
                })
        
        self.accept()
