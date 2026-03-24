import time
from queue import Empty
import cv2
import numpy as np

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtGui import QImage, QPainter, QPaintEvent
from PySide6.QtCore import Qt, Signal, Slot, QThread

from desktop.core.app_state import AppState

class CameraWorker(QThread):
    new_frame = Signal(object, str) # Emits (QImage, camera_id)

    def __init__(self, camera_id, mp_queue):
        super().__init__()
        self.camera_id = camera_id
        self.mp_queue = mp_queue
        self.running = True

    def run(self):
        while self.running:
            try:
                frame_bytes = self.mp_queue.get(timeout=0.2)
                # Decode jpeg
                np_arr = np.frombuffer(frame_bytes, np.uint8)
                img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if img is not None:
                    # Convert to QImage
                    h, w, ch = img.shape
                    bytes_per_line = ch * w

                    cv2.cvtColor(img, cv2.COLOR_BGR2RGB, img)
                    qimg = QImage(img.data, w, h, bytes_per_line, QImage.Format_RGB888)

                    self.new_frame.emit(qimg.copy(), self.camera_id)
            except Empty:
                continue
            except Exception as e:
                # Can be silent
                time.sleep(1)

    def stop(self):
        self.running = False
        self.wait()

class OpenGLVideoWidget(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None

    @Slot(object, str)
    def update_frame(self, image, cam_id):
        self.image = image
        self.update()

    def paintEvent(self, event: QPaintEvent):
        painter = QPainter(self)
        if self.image:
            # Stretch image to fill the entire widget area (removes black bars)
            painter.drawImage(self.rect(), self.image)
        else:
            painter.fillRect(self.rect(), Qt.black)

    def mouseDoubleClickEvent(self, event):
        # Propagate to parent CameraCard
        if isinstance(self.parent(), QWidget):
            self.parent().mouseDoubleClickEvent(event)


class CameraCard(QWidget):
    """A card that displays the OpenGL feed and some metadata/controls."""
    camera_edited = Signal()
    camera_deleted = Signal()
    double_clicked = Signal(str) # Emits camera_id

    def __init__(self, camera_id, mp_queue, config_data):
        super().__init__()
        self.camera_id = camera_id
        self.mp_queue = mp_queue
        self.config_data = config_data


        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet("CameraCard { background-color: #111827; border: 1px solid #374151; border-radius: 6px; }")


        # Header section
        self.header_layout = QHBoxLayout()
        self.name_label = QLabel(self.config_data.get("name", f"Kamera {camera_id}"))
        self.name_label.setStyleSheet("font-weight: bold; font-size: 16px;")

        self.edit_btn = QPushButton("Kamera Düzenle")
        self.edit_btn.clicked.connect(self.open_edit)
        self.edit_btn.setFixedWidth(100)

        self.delete_btn = QPushButton("Sil")
        self.delete_btn.clicked.connect(self.delete_camera)
        self.delete_btn.setFixedWidth(60)

        self.toggle_btn = QPushButton()
        self.toggle_btn.setFixedWidth(80)
        self.toggle_btn.clicked.connect(self.toggle_camera)

        self.record_btn = QPushButton("Kaydet")
        self.record_btn.clicked.connect(self.toggle_record)
        self.record_btn.setFixedWidth(80)

        self.record_settings_btn = QPushButton("⚙") # Gear icon for settings
        self.record_settings_btn.setFixedWidth(30)
        self.record_settings_btn.clicked.connect(self.open_record_settings)
        self.record_settings_btn.setToolTip("Veri Toplama Ayarları")

        self.header_layout.addWidget(self.name_label)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.toggle_btn)
        self.header_layout.addWidget(self.record_settings_btn)
        self.header_layout.addWidget(self.record_btn)
        self.header_layout.addWidget(self.edit_btn)
        self.header_layout.addWidget(self.delete_btn)
        self.layout.addLayout(self.header_layout)

        # Video Render
        self.video_widget = OpenGLVideoWidget()
        self.video_widget.setMinimumSize(320, 240)
        self.layout.addWidget(self.video_widget, stretch=1)

        # Start/Stop the queue worker based on state
        self.worker = None
        self.update_ui_state()


    def open_edit(self):
        from desktop.ui.forms.camera_form import CameraFormDialog
        dialog = CameraFormDialog(self.window(), camera_id=self.camera_id)
        if dialog.exec():
            self.camera_edited.emit()

    def update_ui_state(self):
        cam_data = AppState.cameras.get(self.camera_id, {})
        is_enabled = cam_data.get("enabled", True)

        if is_enabled:
            self.toggle_btn.setText("Durdur")
            self.toggle_btn.setStyleSheet("background-color: #ce8106; color: white; font-weight: bold;")
            self.name_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #10b981;") # Greenish
            self.record_btn.setEnabled(True)
            self.record_settings_btn.setEnabled(True)

            # Start worker if not running
            if not self.worker:
                q = AppState.process_mgr.frame_queues.get(self.camera_id)
                if q:
                    self.worker = CameraWorker(self.camera_id, q)
                    self.worker.new_frame.connect(self.video_widget.update_frame)
                    self.worker.start()
        else:
            self.toggle_btn.setText("Başlat")
            self.toggle_btn.setStyleSheet("background-color: #10b981; color: white; font-weight: bold;")
            self.name_label.setStyleSheet("font-weight: bold; font-size: 16px; color: #6b7280;") # Gray
            self.record_btn.setEnabled(False)
            self.record_settings_btn.setEnabled(False)

            # Stop worker if running
            if self.worker:
                self.worker.stop()
                self.worker = None

            # Clear frame
            self.video_widget.update_frame(None, self.camera_id)

        # Update record button state
        dc = cam_data.get("data_collection") or {}
        if dc.get("enabled"):
            self.record_btn.setText("Kaydı Durdur")
            self.record_btn.setStyleSheet("background-color: #ef4444; color: white; font-weight: bold;")
        else:
            self.record_btn.setText("Kaydet")
            self.record_btn.setStyleSheet("")

    def set_alarm_visual(self, active: bool):
        """Changes the card background to signal a detection/alarm."""
        cam_data = AppState.cameras.get(self.camera_id, {})
        if active:
            color = cam_data.get("alarm_color", "#10B981")
            self.setStyleSheet(f"CameraCard {{ background-color: {color}; border: 2px solid {color}; border-radius: 6px; }}")
            self.name_label.setText("")
        else:
            # Revert to default
            self.setStyleSheet("CameraCard { background-color: #111827; border: 1px solid #374151; border-radius: 6px; }")
            name = cam_data.get("name", f"Kamera {self.camera_id}")
            self.name_label.setText(name)

    def toggle_camera(self):
        cam_data = AppState.cameras.get(self.camera_id, {})
        new_state = not cam_data.get("enabled", True)

        # Update AppState
        cam_data["enabled"] = new_state
        AppState.cameras[self.camera_id] = cam_data

        # Perspective: Start or Stop process
        if new_state:
            # Re-generate URL in case it changed (though usually handled in Edit)
            from backend.models import CameraConfig
            cfg = CameraConfig(**cam_data)
            cam_data["url"] = cfg.get_rtsp_url()
            AppState.process_mgr.start_camera(cam_data)
        else:
            AppState.process_mgr.stop_camera(self.camera_id)

        # Sync PLC
        AppState.plc_mgr.set_event_queues(AppState.process_mgr.event_queues)

        # Save config
        from backend.config import save_cameras
        save_cameras(AppState.cameras)

        self.update_ui_state()

    def toggle_record(self):
        cam_data = AppState.cameras.get(self.camera_id, {})
        dc = cam_data.get("data_collection") or {
            "enabled": False,
            "mode": "frames",
            "interval": 5
        }
        if isinstance(dc, object) and hasattr(dc, 'dict'): dc = dc.dict()

        new_state = not dc.get("enabled", False)
        dc["enabled"] = new_state
        cam_data["data_collection"] = dc

        # Save config
        from backend.config import save_cameras
        save_cameras(AppState.cameras)

        # Send command to process
        AppState.process_mgr.send_command(self.camera_id, {
            "cmd": "update_data_collection",
            "config": dc
        })

        self.update_ui_state()

    def open_record_settings(self):
        from desktop.ui.forms.data_collection_form import DataCollectionFormDialog
        dialog = DataCollectionFormDialog(self.window(), camera_id=self.camera_id)
        if dialog.exec():
            self.update_ui_state()

    def delete_camera(self):
        reply = QMessageBox.question(
            self, "Uyarı",
            f"Kamerayı silmek istediğinizden emin misiniz '{self.config_data.get('name')}'?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # Shutdown process and cleanup
            AppState.process_mgr.stop_camera(self.camera_id)
            if self.camera_id in AppState.cameras:
                del AppState.cameras[self.camera_id]

                from backend.config import save_cameras
                save_cameras(AppState.cameras)
                AppState.plc_mgr.set_cameras(AppState.cameras)

                self.camera_deleted.emit()

    def stop_worker(self):
        if self.worker:
            self.worker.stop()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.camera_id)
