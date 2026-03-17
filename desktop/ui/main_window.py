import os
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QGridLayout, QLabel,
    QScrollArea, QPushButton, QHBoxLayout, QListWidget, QListWidgetItem, QFrame
)
from PySide6.QtCore import Qt, QTimer, Slot, QDateTime
from PySide6.QtGui import QColor

from desktop.core.app_state import AppState
from desktop.ui.camera_widget import CameraCard

from desktop.ui.forms.camera_form import CameraFormDialog
from desktop.ui.forms.plc_form import PLCFormDialog, PLCManagerDialog

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("V-Detect Kontrol Paneli")
        self.resize(1280, 800)

        # Central Layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_h_layout = QHBoxLayout(self.central_widget)

        # Left container (Header + Grid)
        self.left_container = QWidget()
        self.left_layout = QVBoxLayout(self.left_container)
        self.main_h_layout.addWidget(self.left_container, stretch=3)

        # Main header
        self.header_layout = QHBoxLayout()
        self.header_label = QLabel("V-Detect Nesne Tespit")
        self.header_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #000000;")
        self.header_layout.addWidget(self.header_label)

        # PLC Status Indicator
        self.plc_status_label = QLabel("PLC: Bekleniyor...")
        self.plc_status_label.setStyleSheet("background-color: #374151; padding: 4px 8px; border-radius: 4px; color: #9ca3af;")

        # Controls
        self.add_cam_btn = QPushButton("Kamera Ekle")
        self.plc_set_btn = QPushButton("PLC Ayarları")
        self.toggle_sidebar_btn = QPushButton("Rapor")

        # Style buttons roughly matching original UI style
        button_style_cam = "padding: 8px 16px; background-color: #3b82f6; color: white; border-radius: 4px; font-weight: bold;"
        button_style_plc = "padding: 8px 16px; background-color: #777777; color: white; border-radius: 4px; font-weight: bold;"
        button_style_panel = "padding: 8px 16px; background-color: #777777; color: white; border-radius: 4px; font-weight: bold;"
        self.add_cam_btn.setStyleSheet(button_style_cam)
        self.plc_set_btn.setStyleSheet(button_style_plc)
        self.toggle_sidebar_btn.setStyleSheet(button_style_panel)

        self.header_layout.addStretch()
        self.header_layout.addWidget(self.plc_status_label)
        self.header_layout.addWidget(self.plc_set_btn)
        self.header_layout.addWidget(self.add_cam_btn)
        self.header_layout.addWidget(self.toggle_sidebar_btn)

        self.plc_set_btn.clicked.connect(self.open_plc_settings)
        self.add_cam_btn.clicked.connect(self.open_camera_form)
        self.toggle_sidebar_btn.clicked.connect(self.toggle_sidebar)

        self.left_layout.addLayout(self.header_layout)

        # Grid view with scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.scroll_area.setWidget(self.grid_container)

        self.left_layout.addWidget(self.scroll_area, stretch=1)

        # Right Sidebar (Recent Events)
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(280)
        self.sidebar.setStyleSheet("background-color: #1f2937; border-left: 1px solid #374151;")
        self.sidebar_layout = QVBoxLayout(self.sidebar)

        self.sidebar_header = QHBoxLayout()
        self.sidebar_title = QLabel("Son Tespitler")
        self.sidebar_title.setStyleSheet("font-weight: bold; font-size: 16px; color: #f3f4f6;")
        self.sidebar_header.addWidget(self.sidebar_title)

        self.clear_events_btn = QPushButton("Temizle")
        self.clear_events_btn.setFixedWidth(60)
        self.clear_events_btn.setStyleSheet("font-size: 10px; background-color: #374151; color: #9ca3af; border: 1px solid #4b5563; padding: 2px;")
        self.clear_events_btn.clicked.connect(self.clear_ui_events)
        self.sidebar_header.addWidget(self.clear_events_btn)

        self.open_folder_btn = QPushButton("Klasör")
        self.open_folder_btn.setFixedWidth(60)
        self.open_folder_btn.setStyleSheet("font-size: 10px; background-color: #374151; color: #9ca3af; border: 1px solid #4b5563; padding: 2px;")
        self.open_folder_btn.clicked.connect(self.open_captures_folder)
        self.sidebar_header.addWidget(self.open_folder_btn)

        self.sidebar_layout.addLayout(self.sidebar_header)

        self.event_list = QListWidget()
        self.event_list.setStyleSheet("""
            QListWidget { background: transparent; border: none; color: #d1d5db; }
            QListWidget::item { border-bottom: 1px solid #374151; padding: 8px; }
        """)
        self.event_list.itemDoubleClicked.connect(self.on_event_double_clicked)
        self.sidebar_layout.addWidget(self.event_list)

        self.main_h_layout.addWidget(self.sidebar)

        # Periodic update timer
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.update_status)
        self.status_timer.start(2000) # Every 2s

        self.camera_cards = {}
        self.fullscreen_camera_id = None
        self.populate_cameras()
        self.refresh_events()

        # Connect alert callback from backend to UI
        AppState.plc_mgr.set_alert_callback(self.on_alert_received)

    @Slot(dict)
    def on_alert_received(self, event):
        # This will be called from a background thread in PLCManager.run
        # We should use a QTimer singleShot or async signal to update UI safely
        # For simplicity, we can just trigger a refresh of the events next timer tick
        # but let's try to add it immediately if person_detected is True
        if event.get("person_detected"):
            QTimer.singleShot(0, lambda: self.add_event_item(event))

    def add_event_item(self, event):
        cam_name = AppState.cameras.get(event['camera_id'], {}).get('name', event['camera_id'])
        ts = QDateTime.fromSecsSinceEpoch(int(event['timestamp'])).toString("HH:mm:ss")
        text = f"[{ts}] {cam_name}\n{event.get('label', 'Nesne')} Tespit Edildi"

        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, {"ts": event['timestamp'], "cam_id": event['camera_id']})
        item.setForeground(QColor("#f87171"))
        self.event_list.insertItem(0, item)
        if self.event_list.count() > 50:
            self.event_list.takeItem(self.event_list.count() - 1)

    def update_status(self):
        # Update PLC Status
        statuses = AppState.plc_mgr.get_statuses()
        if not statuses:
            self.plc_status_label.setText("PLC")
            self.plc_status_label.setStyleSheet("background-color: #374151; padding: 4px 8px; border-radius: 4px; color: #9ca3af;")
        else:
            # Check if any are connected (or show first one)
            active = any(statuses.values())
            if active:
                self.plc_status_label.setText("PLC: AKTİF")
                self.plc_status_label.setStyleSheet("background-color: #065f46; padding: 4px 8px; border-radius: 4px; color: #34d399; font-weight: bold;")
            else:
                self.plc_status_label.setText("PLC: PASİF")
                self.plc_status_label.setStyleSheet("background-color: #7f1d1d; padding: 4px 8px; border-radius: 4px; color: #f87171; font-weight: bold;")

    def clear_ui_events(self):
        self.event_list.clear()

    def open_captures_folder(self):
        from backend.config import CAPTURES_DIR
        import os
        if os.path.exists(CAPTURES_DIR):
            os.startfile(CAPTURES_DIR)
        else:
            QMessageBox.information(self, "Bilgi", "Henüz kaydedilmiş bir görsel bulunamadı.")

    def toggle_sidebar(self):
        self.sidebar.setVisible(not self.sidebar.isVisible())

    def on_event_double_clicked(self, item):
        data = item.data(Qt.UserRole)
        if not data or not isinstance(data, dict):
            return

        ts = data.get("ts")
        cam_id = data.get("cam_id")

        import os
        filename = f"{int(ts)}.jpg"
        
        # New pattern: ID_NAME (resolved via manager)
        folder_path = AppState.process_mgr.get_capture_dir(cam_id)
        filepath = os.path.join(folder_path, filename)

        # Fallback for old captures: just ID
        if not os.path.exists(filepath):
            from backend.config import CAPTURES_DIR
            old_filepath = os.path.join(CAPTURES_DIR, cam_id, filename)
            if os.path.exists(old_filepath):
                filepath = old_filepath

        if os.path.exists(filepath):
            os.startfile(filepath)
        else:
            QMessageBox.warning(self, "Hata", f"Görsel bulunamadı: {filename}")

    def refresh_events(self):
        """Initial load of events from SQLite."""
        events = AppState.event_store.query(limit=20)
        self.event_list.clear()
        for e in events:
            # We only show positive detections in the "Recent Events" sidebar for clarity
            if e['person_detected']:
                cam_name = AppState.cameras.get(e['camera_id'], {}).get('name', e['camera_id'])
                ts_str = QDateTime.fromSecsSinceEpoch(int(e['timestamp'])).toString("HH:mm:ss")
                item = QListWidgetItem(f"[{ts_str}] {cam_name}\nNesne Tespit Edildi")
                item.setData(Qt.UserRole, {"ts": e['timestamp'], "cam_id": e['camera_id']})
                self.event_list.addItem(item)

    def populate_cameras(self):
        """Loads cameras from AppState and adds to grid."""
        idx = 0
        for cam_id, cam_data in AppState.cameras.items():
            # If in full-screen mode, only show the selected camera
            if self.fullscreen_camera_id and cam_id != self.fullscreen_camera_id:
                continue

            row = idx // 2
            col = idx % 2

            # Pass None for queue; CameraCard.update_ui_state will fetch it from process_mgr
            card = CameraCard(cam_id, None, cam_data)
            card.camera_edited.connect(self.refresh_cameras)
            card.camera_deleted.connect(self.refresh_cameras)
            card.double_clicked.connect(self.on_camera_double_clicked)
            self.grid_layout.addWidget(card, row, col)
            self.camera_cards[cam_id] = card
            idx += 1

        # Sync PLC queues once all cards are potentially started
        AppState.plc_mgr.set_event_queues(AppState.process_mgr.event_queues)

    def open_camera_form(self):
        dialog = CameraFormDialog(self)
        if dialog.exec():
            # Refresh grid list
            self.refresh_cameras()

    def open_plc_settings(self):
        dialog = PLCManagerDialog(self)
        dialog.exec()

    @Slot(str)
    def on_camera_double_clicked(self, camera_id):
        if self.fullscreen_camera_id == camera_id:
            # Already in full-screen for this camera, go back to grid
            self.fullscreen_camera_id = None
        else:
            # Go full-screen for this camera
            self.fullscreen_camera_id = camera_id
        
        self.refresh_cameras()

    def refresh_cameras(self):
        for card in self.camera_cards.values():
            card.stop_worker()
            card.setParent(None)
            card.deleteLater()

        self.camera_cards.clear()

        # Clear layout fully
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

        self.populate_cameras()

    def closeEvent(self, event):
        """Shut down camera workers cleanly."""
        for card in self.camera_cards.values():
            card.stop_worker()
        super().closeEvent(event)
