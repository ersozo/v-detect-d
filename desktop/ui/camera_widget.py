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


class CameraCard(QWidget):
    """A card that displays the OpenGL feed and some metadata/controls."""
    camera_edited = Signal()
    camera_deleted = Signal()

    def __init__(self, camera_id, mp_queue, config_data):
        super().__init__()
        self.camera_id = camera_id
        self.mp_queue = mp_queue
        self.config_data = config_data

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(5, 5, 5, 5)

        # Header section
        self.header_layout = QHBoxLayout()
        self.name_label = QLabel(self.config_data.get("name", f"Kamera {camera_id}"))
        self.name_label.setStyleSheet("font-weight: bold;")

        self.roi_btn = QPushButton("Bölge Seç")
        self.roi_btn.clicked.connect(self.open_roi)
        self.roi_btn.setFixedWidth(100)

        self.edit_btn = QPushButton("Kamera Düzenle")
        self.edit_btn.clicked.connect(self.open_edit)
        self.edit_btn.setFixedWidth(100)

        self.delete_btn = QPushButton("Sil")
        self.delete_btn.clicked.connect(self.delete_camera)
        self.delete_btn.setFixedWidth(100)
        self.delete_btn.setStyleSheet("background-color: #ef4444; color: white;")

        self.header_layout.addWidget(self.name_label)
        self.header_layout.addStretch()
        self.header_layout.addWidget(self.roi_btn)
        self.header_layout.addWidget(self.edit_btn)
        self.header_layout.addWidget(self.delete_btn)
        self.layout.addLayout(self.header_layout)

        # Video Render
        self.video_widget = OpenGLVideoWidget()
        self.video_widget.setMinimumSize(320, 240)
        self.layout.addWidget(self.video_widget, stretch=1)

        # Start the queue worker
        self.worker = CameraWorker(camera_id, mp_queue)
        self.worker.new_frame.connect(self.video_widget.update_frame)
        self.worker.start()

        self.update_roi_btn_text()

    def update_roi_btn_text(self):
        cam_data = AppState.cameras.get(self.camera_id, {})
        has_roi = bool(cam_data.get("roi"))
        has_zones = bool(cam_data.get("zones"))

        if has_roi or has_zones:
            self.roi_btn.setText("Bölge Düzenle")
        else:
            self.roi_btn.setText("Bölge Seç")

    def open_roi(self):
        from desktop.ui.forms.roi_form import RoiEditorDialog
        # Pass the main window as parent to keep dialog on top properly
        dialog = RoiEditorDialog(self.window(), camera_id=self.camera_id)
        if dialog.exec():
            # Refresh text if zones were saved
            self.update_roi_btn_text()

    def open_edit(self):
        from desktop.ui.forms.camera_form import CameraFormDialog
        dialog = CameraFormDialog(self.window(), camera_id=self.camera_id)
        if dialog.exec():
            self.camera_edited.emit()

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
