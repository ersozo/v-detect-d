# V-Detect — System Architecture

## Overview

V-Detect is a native desktop application designed for real-time object detection, industrial monitoring, and AI dataset collection.
It captures RTSP camera feeds, runs YOLO26 inference (via OpenVINO), enforces complex polygon security zones, communicates with Siemens S7 PLCs via many-to-many logic, and provides a raw data harvesting pipeline for custom model training.

---

## Design Principles

| #   | Principle                             | Implementation                                                                     |
| --- | ------------------------------------- | ---------------------------------------------------------------------------------- |
| 1   | **Streaming ≠ Detection ≠ PLC**       | Three independent layers with no cross-coupling                                    |
| 2   | **Each camera = separate OS process** | `multiprocessing.Process` per camera for CPU isolation (no GIL)                    |
| 3   | **Backlog-free**                      | Leaky queues (`maxsize=1`) — always latest frame, never stale                      |
| 4   | **Many-to-Many PLC**                  | Multi-PLC driving logic where each camera explicitly defines multiple bit outputs  |
| 5   | **Native Desktop UI**                 | PySide6 (Qt) for high-performance rendering and localized control                  |
| 6   | **Per-Camera Visual Alerts**          | Configurable alarm flash colors (Green/Red) in the dashboard grid                  |
| 7   | **AI-Aware Data Collection**          | Dedicated pipeline for raw captures; auto-pauses AI to maximize FPS                |
| 8   | **Privacy-First Cropping**            | Crop applied *after* AI inference — detection on full frame, UI view is cropped    |
| 9   | **Production Data Isolation**         | Uses OS-standard paths (%APPDATA% / ~/.local) for portable, secure installation    |
| 10  | **Bundled Optimized Inference**       | Pre-packages OpenVINO assets via PyInstaller to eliminate first-run conversion lag |

---

## System Diagram

```
                    ┌────────────────────────────┐
                    │      PySide6 Desktop       │
                    │   (MainWindow & Widgets)   │
                    └─────────────▲──────────────┘
                                  │ Direct Frame Rendering
                                  │ (mp.Queue -> QImage)
                    ┌─────────────┴──────────────┐
                    │        App State           │
                    │  - Global Config           │
                    │  - Process Lifecycle       │
                    │  - Event Store (SQLite)    │
                    │  - Multi-PLC Pool          │
                    └───────▲─────────────▲──────┘
                            │             │
              control queue │             │ event queue
              (commands)    │             │ (detections)
                            │             │
        ┌───────────────────┘             └──────────────────┐
        │                                                    │
 ┌──────┴──────────────┐                              ┌──────┴──────────────┐
 │   CameraProcess 1   │                              │   CameraProcess N   │
 │  ┌─ RTSP Capture    │                              │  ┌─ RTSP Capture    │
 │  ├─ AI Detection    │                              │  ├─ AI Detection    │
 │  ├─ Frame Annotator │                              │  ├─ Frame Annotator │
 │  └─ Data Collector  ├────────┐             ┌───────┤  └─ Data Collector  │
 └──────▲──────────────┘        │             │       └──────▲──────────────┘
        │                       ▼             ▼              │
        │                ┌───────────────────────────┐       │
        │                │     data/captures/        │       │
        │                │   (snapshots & training)  │       │
        │                └───────────────────────────┘       │
        │                                                    │
        └──────────────────► PLC Manager ◄───────────────────┘
                                  │
                        ┌─────────┴───────┐
                        │  Multi-PLC Pool │
                ┌───────┴─────────┬───────┴─────────┐
                │                 │                 │
         ┌──────▼────────┐ ┌──────▼────────┐ ┌──────▼────────┐
         │  PLC (Line A) │ │  PLC (Line B) │ │  PLC (Main)   │
         └───────────────┘ └───────────────┘ └───────────────┘
```

---

## Data Flow

### Frame Pipeline (per camera)

```
RTSP Camera
  │
  ▼  cv2.VideoCapture (TCP transport, buffer=1)
RTSPCapture.read()
  │
  ├─► Is "Data Collection" Active?
  │   ├── YES: [Save raw frame/video] -> [Skip AI Detection (Save CPU)]
  │   └── NO:  [Run AI Detection]
  │
  ▼  AI inference (OpenVINO Optimized)
Detector.detect(frame, zones, confidence)
  │  returns: [{ x1, y1, x2, y2, confidence, zone_id, label }, ...]
  │
  ▼  Annotate: Draw boxes + Zone Polygons + Localized Labels
Annotate → Raw Frame Bytes
  │
  ├─► **Privacy Crop**: Applied here (if enabled) before JPEG encoding
  │
  ├──► frame_queue (leaky) → CameraWorker (QThread) → QImage → OpenGLVideoWidget
  │
  └──► event_queue (leaky) → PLC Manager → S7 Write & DB Log
```

### Data Collection Modes
1. **Frames Mode**: Saves individual raw `.jpg` files at a configurable interval (shutter logic).
2. **Video Mode**: Records a continuous high-quality `.avi` (MJPG codec) stream.
*Both modes automatically pause AI inference to ensure the storage task receives maximum hardware priority.*

### IPC Strategy
V-Detect uses **Multiprocessing Queues** for inter-process communication:
- **Frame Queue**: A "leaky" queue that holds exactly 1 frame. If a new frame arrives before the UI consumes the last one, the old one is discarded. This ensures zero latency.
- **Control Queue**: Allows the UI to send commands (Set ROI, Update Sensitivity) to the camera processes while they are running.
- **Event Queue**: Transfers detection data (class, any_detected, timestamp) to the main process for PLC triggering and database logging.

---

## File Map

```
desktop/
├── main.py               Entry point. Initializes qasync event loop and MainWindow.
├── core/
│   └── app_state.py      Global shared state (ProcessManager, PLCManager, Config).
└── ui/
    ├── main_window.py    Dashboard UI: Camera grid, Full-screen toggle, Snapshots.
    ├── camera_widget.py  Camera rendering logic (OpenGL) and interactive controls.
    └── forms/
        ├── camera_form.py          Camera hardware & AI settings.
        ├── plc_form.py             Multi-PLC Manager & Mapping editor.
        ├── roi_form.py             Interactive polygon zone editor.
        ├── crop_form.py            Visual crop selection (Privacy).
        └── data_collection_form.py Training data recording settings.

backend/
├── camera_process.py     The "engine" loop. Handles AI, capture, and data collection.
├── detector.py           AI logic — YOLO inference and ROI polygon filtering.
├── plc_manager.py        Orchestrates many-to-many PLC event routing.
├── plc_client.py         Snap7 client implementation with Lifebit/IO support.
├── process_manager.py    Handles OS-level lifecycle and IPC command routing.
├── event_store.py        SQLite interface for detection history and auditing.
├── capture.py            RTSP connection stability and frame acquisition.
└── config.py             JSON-based configuration persistence.

data/                     Storage during development (Local directory).
│                         On production installation, this is replaced by:
│                         Windows: %APPDATA%\VDetect
│                         Linux: ~/.local/share/v-detect
├── cameras_db.json       Camera definitions and Data Collection configs.
├── plcs_db.json          Multi-PLC database instances.
├── events.db             SQLite detection log.
└── captures/             📁 organized by camera name ({name})
    ├── snapshots/        Detection-triggered images.
    └── training/         Raw data collected for custom models (JPG/AVI).
```

---

## Components

### 1. Unified Camera Engine (`camera_process.py`)
A heavy-duty asynchronous loop that manages per-camera hardware resources. It supports **hot-reloading** of configurations (sensitivity, ROI, zones) without process restarts via the IPC `control_queue`.

### 2. Many-to-Many PLC Orchestrator (`plc_manager.py`)
A centralized pool that manages multiple industrial connections simultaneously using a decentralized mapping strategy.
- **Camera-Owned Outputs**: Each camera configuration defines its own list of PLC targets (IP, DB, Byte, Bit). This replaces legacy centralized PLC-side mapping.
- **Many-to-Many Routing**: One camera can trigger multiple PLCs; one PLC can receive signals from multiple cameras.
- **Fault Tolerance**: Monitors "Lifebit" status for every configured PLC independently.
- **Independent Clients**: A failure in one PLC connection does not block others.

### 3. Data Collection System
A dedicated subsystem for harvesting AI training data.
- **Raw Capture**: Captures un-annotated frames directly from the stream.
- **Automatic Optimization**: Detection is paused during recording to ensure smooth capture and low CPU thermals.

### 4. Desktop Dashboard (`main_window.py`)
A native PySide6 interface localized in Turkish.
- **Full-Screen Focus**: Double-click any feed to zoom; double-click to return.
- **Stretched Rendering**: Uses high-performance rendering to eliminate black bars.
- **Event Panel**: Live detection log with one-click snapshot viewing.
- **ROI Editor**: Interactive polygon drawing tool for defining security zones.
- **Privacy Crop**: Dedicated visual tool for limiting the visible stream area while preserving full-frame AI accuracy.
- **Visual Feedback**: Real-time card flashing with user-defined colors (Green/Red) upon detection.

---

## Dependencies

- **UI Framework**: PySide6 (Qt for Python 6)
- **AI Engine**: Ultralytics YOLOv8/v10 + OpenVINO (Inference Acceleration)
- **Computer Vision**: OpenCV (with MJPG/XVID support)
- **Industrial**: python-snap7 (Siemens S7 Protocol)
- **Async**: qasync (Bridges Python's asyncio with Qt's Event Loop)
- **Storage**: SQLite3

---

## Hardware Considerations

Due to its multiprocess architecture, V-Detect scales significantly with CPU cores.
- **Minimum**: 4 Core (2-4 Cameras)
- **Recommended**: 8+ Core (8+ Cameras)
- **Acceleration**: Intel CPU with OpenVINO support is highly recommended for optimal AI latency.

---

## Deployment & Packaging

V-Detect is architected for standalone, professional distribution on Windows and Linux.

### 1. Windows Bundling
- **Tool**: PyInstaller 6.x
- **Config**: `vdetect.spec`
- **Output**: Portable directory in `dist/VDetect`
- **Strategy**: Bundles `torch`, `ultralytics`, `openvino`, and all backend source code while stripping unnecessary UI libraries.

### 2. Windows Installer
- **Tool**: Inno Setup
- **Config**: `vdetect_installer.iss`
- **Feature**: Creates a professional `VDetect_Setup.exe` with desktop shortcuts, start menu integration, and automated versioning.

### 3. Linux Packaging (Ubuntu)
- **Format**: AppImage
- **Support**: Uses `scripts/vdetect.desktop` for system integration.
- **Portable**: Designed to work on generic Ubuntu/Debian installs without user-level Python setup.

---

## Running Locally

```bash
# Setup environment
python -m venv .venv
# On Windows
.venv\Scripts\activate
# On Linux
source .venv/bin/activate

pip install -r requirements.txt

# Launch Application (Development)
python desktop/main.py

# Build Production Bundle (Windows)
python scripts/build.py
```
