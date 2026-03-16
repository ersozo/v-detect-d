import math
import numpy as np
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QWidget, QListWidget, QListWidgetItem,
    QMessageBox, QSplitter
)
from PySide6.QtCore import Qt, Signal, Slot, QPointF
from PySide6.QtGui import QPainter, QColor, QPen, QImage, QPolygonF

from desktop.core.app_state import AppState

class RoiCanvasWidget(QWidget):
    point_added = Signal(QPointF)
    drawing_completed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image = None
        self.zones = []
        self.active_points = []
        self.is_closed = False
        self.hover_point = None

        self.setMouseTracking(True)

    def set_image(self, img_bytes):
        if img_bytes:
            # Decode JPEG from raw bytes
            import cv2
            np_arr = np.frombuffer(img_bytes, np.uint8)
            img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if img is not None:
                cv2.cvtColor(img, cv2.COLOR_BGR2RGB, img)
                h, w, ch = img.shape
                bytes_per_line = ch * w
                self.image = QImage(img.data, w, h, bytes_per_line, QImage.Format_RGB888).copy()
                self.setMinimumSize(400, 300)
                self.update()

    def set_zones(self, zones):
        self.zones = zones
        self.update()

    def reset_drawing(self):
        self.active_points = []
        self.is_closed = False
        self.hover_point = None
        self.update()

    def undo_last_point(self):
        if self.active_points and not self.is_closed:
            self.active_points.pop()
            self.update()

    def get_image_coords(self, pos: QPointF):
        if not self.image:
            return None

        # Calculate bounding rect of scaled image
        scaled_img = self.image.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x_offset = (self.width() - scaled_img.width()) / 2
        y_offset = (self.height() - scaled_img.height()) / 2

        # Filter clicks outside the image bounds
        if pos.x() < x_offset or pos.x() > x_offset + scaled_img.width():
            return None
        if pos.y() < y_offset or pos.y() > y_offset + scaled_img.height():
            return None

        # Scale clicked coordinates back to native image dimensions
        scale_x = self.image.width() / scaled_img.width()
        scale_y = self.image.height() / scaled_img.height()

        nx = (pos.x() - x_offset) * scale_x
        ny = (pos.y() - y_offset) * scale_y

        return QPointF(nx, ny)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            pt = self.get_image_coords(event.position())
            if not pt or self.is_closed:
                return

            if len(self.active_points) >= 3:
                # Check distance to first point to close shape
                fpt = self.active_points[0]
                dist = math.hypot(pt.x() - fpt.x(), pt.y() - fpt.y())
                # Allow 15px radius natively scaled approx
                if dist < (self.image.width() * 0.05):
                    self.is_closed = True
                    self.drawing_completed.emit()
                    self.update()
                    return

            self.active_points.append(pt)
            self.point_added.emit(pt)
            self.update()

    def mouseDoubleClickEvent(self, event):
        if len(self.active_points) >= 3 and not self.is_closed:
            self.is_closed = True
            self.drawing_completed.emit()
            self.update()

    def mouseMoveEvent(self, event):
        if self.is_closed or not self.active_points:
            self.hover_point = None
            return

        pt = self.get_image_coords(event.position())
        self.hover_point = pt
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), Qt.black)

        if not self.image:
            return

        scaled_img = self.image.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x_offset = (self.width() - scaled_img.width()) / 2
        y_offset = (self.height() - scaled_img.height()) / 2

        painter.drawImage(x_offset, y_offset, scaled_img)

        # Draw coordinate scale logic
        scale_x = scaled_img.width() / self.image.width()
        scale_y = scaled_img.height() / self.image.height()

        def to_view(p):
            return QPointF(x_offset + p.x() * scale_x, y_offset + p.y() * scale_y)

        # Draw Saved Zones
        for zone in self.zones:
            pts = zone.get("points", [])
            if len(pts) < 3:
                continue

            poly = QPolygonF([to_view(QPointF(p["x"], p["y"])) for p in pts])
            color = QColor("#10b981") if zone.get("severity") == "warning" else QColor("#ef4444")

            fill_color = QColor(color)
            fill_color.setAlphaF(0.25)

            painter.setPen(QPen(color, 3))
            painter.setBrush(fill_color)
            painter.drawPolygon(poly)

            # Draw Label
            painter.setPen(Qt.white)
            fp = to_view(QPointF(pts[0]["x"], pts[0]["y"]))
            painter.drawText(fp, zone.get("name", "Zone"))

        # Draw Active Zone
        if self.active_points:
            active_color = QColor("#3b82f6")
            painter.setPen(QPen(active_color, 2))

            view_pts = [to_view(p) for p in self.active_points]

            if self.is_closed:
                fill_color = QColor(active_color)
                fill_color.setAlphaF(0.25)
                poly = QPolygonF(view_pts)
                painter.setBrush(fill_color)
                painter.drawPolygon(poly)
            else:
                for i in range(len(view_pts) - 1):
                    painter.drawLine(view_pts[i], view_pts[i+1])

                if self.hover_point:
                    pen = QPen(active_color, 2, Qt.DashLine)
                    painter.setPen(pen)
                    painter.drawLine(view_pts[-1], to_view(self.hover_point))

            # Draw circles for vertices
            for idx, p in enumerate(view_pts):
                if idx == 0 and len(view_pts) >= 3 and not self.is_closed:
                    painter.setBrush(QColor("#fbbf24"))
                    painter.setPen(QColor("#f59e0b"))
                else:
                    painter.setBrush(active_color)
                    painter.setPen(QColor("#2563eb"))
                painter.drawEllipse(p, 6, 6)


class RoiEditorDialog(QDialog):
    def __init__(self, parent=None, camera_id=None):
        super().__init__(parent)
        self.setWindowTitle(f"Bölge Editörü - {camera_id}")
        self.resize(1024, 768)
        self.camera_id = camera_id

        self.zones = []
        cam_data = AppState.cameras.get(self.camera_id, {})
        if cam_data.get("zones"):
            self.zones = list(cam_data["zones"])
        elif cam_data.get("roi"):
            self.zones = [{
                "name": "Main Zone",
                "points": cam_data["roi"],
                "severity": "warning"
            }]

        self.setup_ui()
        self.fetch_preview()
        self.update_zone_list()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)

        # Left side Canvas
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)

        self.canvas = RoiCanvasWidget()
        self.canvas.set_zones(self.zones)
        canvas_layout.addWidget(self.canvas)

        tools_layout = QHBoxLayout()
        undo_btn = QPushButton("Geri Al")
        undo_btn.clicked.connect(self.canvas.undo_last_point)
        clear_btn = QPushButton("Çizimi Temizle")
        clear_btn.clicked.connect(self.canvas.reset_drawing)
        tools_layout.addWidget(undo_btn)
        tools_layout.addWidget(clear_btn)
        canvas_layout.addLayout(tools_layout)

        splitter.addWidget(canvas_container)

        # Right side Details/Zones List
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)

        sidebar_layout.addWidget(QLabel("Yeni Bölge:"))
        self.z_name_in = QLineEdit()
        self.z_name_in.setPlaceholderText("örn. Güvenlik Bölgesi")
        self.z_sev_cb = QComboBox()
        self.z_sev_cb.addItem("Yeşil", "uyarı")
        self.z_sev_cb.addItem("Kırmızı", "alarm")

        add_btn = QPushButton("Listeye Ekle")
        add_btn.clicked.connect(self.add_current_zone)

        sidebar_layout.addWidget(self.z_name_in)
        sidebar_layout.addWidget(QLabel("Kritiklik Seviyesi:"))
        sidebar_layout.addWidget(self.z_sev_cb)
        sidebar_layout.addWidget(add_btn)

        sidebar_layout.addWidget(QLabel("Mevcut Bölgeler:"))
        self.zone_list = QListWidget()
        sidebar_layout.addWidget(self.zone_list)

        remove_btn = QPushButton("Seçili Bölgeyi Sil")
        remove_btn.clicked.connect(self.remove_zone)
        sidebar_layout.addWidget(remove_btn)

        splitter.addWidget(sidebar)
        splitter.setSizes([700, 300])
        main_layout.addWidget(splitter)

        # Dialog buttons
        btns = QHBoxLayout()
        btns.addStretch()
        cancel_btn = QPushButton("İptal")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Kaydet")
        save_btn.clicked.connect(self.save_zones)
        btns.addWidget(cancel_btn)
        btns.addWidget(save_btn)

        main_layout.addLayout(btns)

    def update_zone_list(self):
        self.zone_list.clear()
        for idx, z in enumerate(self.zones):
            item = QListWidgetItem(f"{z['name']} ({z['severity']}) - {len(z['points'])} pts")
            item.setData(Qt.UserRole, idx)
            self.zone_list.addItem(item)
        self.canvas.set_zones(self.zones)

    def add_current_zone(self):
        if not self.canvas.is_closed or len(self.canvas.active_points) < 3:
            QMessageBox.warning(self, "Hata", "Lütfen önce geçerli bir bölge (poligon) çizimini tamamlayın.")
            return

        points = [{"x": p.x(), "y": p.y()} for p in self.canvas.active_points]
        name = self.z_name_in.text() or f"Bolge {len(self.zones)+1}"

        self.zones.append({
            "name": name,
            "points": points,
            "severity": self.z_sev_cb.currentData()
        })

        self.canvas.reset_drawing()
        self.z_name_in.clear()
        self.update_zone_list()

    def remove_zone(self):
        sel = self.zone_list.selectedItems()
        if not sel:
            return
        idx = sel[0].data(Qt.UserRole)
        del self.zones[idx]
        self.update_zone_list()

    def fetch_preview(self):
        import asyncio
        import qasync

        async def do_fetch():
            AppState.process_mgr.send_command(self.camera_id, {"cmd": "get_frame"})
            buf = await AppState.process_mgr.get_response(self.camera_id, timeout=5.0)
            if buf:
                self.canvas.set_image(buf)

        asyncio.create_task(do_fetch())

    def save_zones(self):
        cam = AppState.cameras.get(self.camera_id)
        if not cam:
            return

        cam["zones"] = self.zones
        cam["roi"] = None

        from backend.config import save_cameras
        save_cameras(AppState.cameras)

        AppState.process_mgr.send_command(self.camera_id, {"cmd": "set_zones", "zones": self.zones})
        self.accept()
