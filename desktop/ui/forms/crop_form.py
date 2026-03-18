import numpy as np
import cv2
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QMessageBox
)
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QPainter, QColor, QPen, QImage, QFont

from desktop.core.app_state import AppState

class CropCanvasWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.start_point = None
        self.end_point = None
        self.is_drawing = False
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)

    def set_image(self, img_bytes):
        if img_bytes:
            np_arr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is not None:
                cv2.cvtColor(img, cv2.COLOR_BGR2RGB, img)
                h, w, ch = img.shape
                bytes_per_line = ch * w
                self.image = QImage(img.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
                self.setMinimumSize(400, 300)
                self.update()

    def get_image_coords(self, pos: QPointF):
        if not self.image: return None
        scaled_img = self.image.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x_offset = (self.width() - scaled_img.width()) / 2
        y_offset = (self.height() - scaled_img.height()) / 2

        if pos.x() < x_offset or pos.x() > x_offset + scaled_img.width(): return None
        if pos.y() < y_offset or pos.y() > y_offset + scaled_img.height(): return None

        scale_x = self.image.width() / scaled_img.width()
        scale_y = self.image.height() / scaled_img.height()
        nx = (pos.x() - x_offset) * scale_x
        ny = (pos.y() - y_offset) * scale_y
        return QPointF(nx, ny)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.get_image_coords(event.position())
            if pt:
                self.start_point = pt
                self.end_point = pt
                self.is_drawing = True
                self.update()

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            pt = self.get_image_coords(event.position())
            if pt:
                self.end_point = pt
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_drawing:
            pt = self.get_image_coords(event.position())
            if pt:
                self.end_point = pt
            self.is_drawing = False
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), Qt.black)

        if not self.image:
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, "Görüntü bekleniyor...")
            return

        scaled_img = self.image.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x_offset = (self.width() - scaled_img.width()) / 2
        y_offset = (self.height() - scaled_img.height()) / 2
        painter.drawImage(x_offset, y_offset, scaled_img)

        if self.start_point and self.end_point:
            scale_x = scaled_img.width() / self.image.width()
            scale_y = scaled_img.height() / self.image.height()

            p1 = QPointF(x_offset + self.start_point.x() * scale_x, y_offset + self.start_point.y() * scale_y)
            p2 = QPointF(x_offset + self.end_point.x() * scale_x, y_offset + self.end_point.y() * scale_y)

            rect = QRectF(p1, p2).normalized()

            active_color = QColor("#3b82f6")
            painter.setPen(QPen(active_color, 2))

            fill_color = QColor(active_color)
            fill_color.setAlphaF(0.25)
            painter.setBrush(fill_color)
            painter.drawRect(rect)

            r_orig = QRectF(self.start_point, self.end_point).normalized()
            dim_text = f"{int(r_orig.width())}x{int(r_orig.height())} px"

            # Draw dimension on top/center of the rect
            painter.setBrush(QColor(0,0,0,160))
            painter.setPen(Qt.NoPen)
            text_rect = QRectF(rect.center().x() - 40, rect.top() - 25, 80, 20)
            painter.drawRoundedRect(text_rect, 4, 4)
            painter.setPen(Qt.white)
            painter.drawText(text_rect, Qt.AlignCenter, dim_text)

class CropEditorDialog(QDialog):
    def __init__(self, parent=None, camera_id=None, current_rect=None):
        super().__init__(parent)
        self.setWindowTitle(f"Kırpma Editörü - {camera_id}")
        self.resize(1024, 768)
        self.camera_id = camera_id
        self.result_rect = None

        self.setup_ui()

        if current_rect and current_rect[2] > 0 and current_rect[3] > 0:
            self.canvas.start_point = QPointF(current_rect[0], current_rect[1])
            self.canvas.end_point = QPointF(current_rect[0] + current_rect[2], current_rect[1] + current_rect[3])

        self.fetch_preview()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(2)

        # Very Compact Header
        header_widget = QWidget()
        header_widget.setFixedHeight(20)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(5, 0, 5, 0)

        # self.title_label = QLabel("KIRPMA ALANI SEÇİMİ")
        # self.title_label.setStyleSheet("font-size: 15px")
        # header_layout.addWidget(self.title_label)

        header_layout.addStretch()
        self.res_label = QLabel("Çözünürlük: --")
        self.res_label.setStyleSheet("font-size: 15px; color: #6b7280;")
        header_layout.addWidget(self.res_label)
        main_layout.addWidget(header_widget)

        # Canvas
        self.canvas = CropCanvasWidget()
        main_layout.addWidget(self.canvas)

        # Tools & Buttons
        footer = QHBoxLayout()
        clear_btn = QPushButton("Geri Dön / Temizle")
        clear_btn.clicked.connect(self.clear_selection)
        footer.addWidget(clear_btn)

        refresh_btn = QPushButton("Yenile")
        refresh_btn.clicked.connect(self.fetch_preview)
        footer.addWidget(refresh_btn)

        footer.addStretch()

        cancel_btn = QPushButton("İptal")
        cancel_btn.clicked.connect(self.reject)

        save_btn = QPushButton("Kaydet")
        save_btn.clicked.connect(self.accept_crop)
        # save_btn.setStyleSheet("font-weight: bold; color: #2563eb;")

        footer.addWidget(cancel_btn)
        footer.addWidget(save_btn)
        main_layout.addLayout(footer)

    def clear_selection(self):
        self.canvas.start_point = None
        self.canvas.end_point = None
        self.canvas.update()

    def fetch_preview(self):
        import asyncio
        async def do_fetch():
            AppState.process_mgr.send_command(self.camera_id, {"cmd": "get_frame", "draw": False})
            buf = await AppState.process_mgr.get_response(self.camera_id, timeout=5.0)
            if buf:
                self.canvas.set_image(buf)
                if self.canvas.image:
                   self.res_label.setText(f"{self.canvas.image.width()}x{self.canvas.image.height()}")

        # Consistent with how roi_form might do it or simply create task
        asyncio.create_task(do_fetch())

    def accept_crop(self):
        if self.canvas.start_point and self.canvas.end_point:
            r = QRectF(self.canvas.start_point, self.canvas.end_point).normalized()
            if r.width() < 16 or r.height() < 16:
                 QMessageBox.warning(self, "Hata", "Alan çok küçük.")
                 return
            self.result_rect = (int(r.x()), int(r.y()), int(r.width()), int(r.height()))
            self.accept()
        else:
            QMessageBox.warning(self, "Hata", "Alan seçilmedi.")
