# V-Detect — System Architecture

## Overview

V-Detect is a native desktop application designed for real-time object detection and industrial monitoring. 
It captures RTSP camera feeds, runs YOLO26 inference, enforces complex polygon ROI zones, communicates with Siemens S7 PLCs via many-to-many logic, and displays localized monitoring dashboards.

---

## Design Principles

| #   | Principle                             | Implementation                                                         |
| --- | ------------------------------------- | ---------------------------------------------------------------------- |
| 1   | **Streaming ≠ Detection ≠ PLC**       | Three independent layers with no cross-coupling                        |
| 2   | **Each camera = separate OS process** | `multiprocessing.Process` per camera for CPU isolation (no GIL)        |
| 3   | **Backlog-free**                      | Leaky queues (`maxsize=1`) — always latest frame, never stale          |
| 4   | **Multi-PLC & Many-to-Many**          | PLCManager drives multiple PLC connections with cross-mapping logic    |
| 5   | **Native Desktop UI**                 | PySide6 (Qt) for high-performance rendering and localized control       |

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
                    │  - PLC Manager             │
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
 │  ├─ YOLO Detector   │                              │  ├─ YOLO Detector   │
 │  └─ Frame Annotator │                              │  └─ Frame Annotator │
 └──────▲──────────────┘                              └──────▲──────────────┘
        │                                                    │
        └──────────────────► PLC Manager ◄───────────────────┘
                               │
                        ┌──────┴───────┐
                        │ Multi-PLC Pool│
                ┌───────┴───────┬───────┴───────┐
                │               │               │
         ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
         │  PLC 1      │ │  PLC 2      │ │  PLC N      │
         └─────────────┘ └─────────────┘ └─────────────┘
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
  ▼  YOLO26 inference (OpenVINO Optimized)
Detector.detect(frame, zones, confidence)
  │  returns: [{ x1, y1, x2, y2, confidence, zone_name, label }, ...]
  │
  ▼  Annotate: Draw boxes + Zone Polygons + Localized Labels
Annotate → Raw Frame Bytes (JPEG)
  │
  ├──► frame_queue (leaky) → CameraWorker (QThread) → QImage → OpenGLVideoWidget
  │
  └──► event_queue (leaky) → PLC Manager → S7 Write & DB Log
```

### IPC Strategy
V-Detect uses **Multiprocessing Queues** for inter-process communication:
- **Frame Queue**: A "leaky" queue that holds exactly 1 frame. If a new frame arrives before the UI consumes the last one, the old one is discarded. This ensures zero latency.
- **Control Queue**: Allows the UI to send commands (Set ROI, Update Sensitivity) to the camera processes while they are running.
- **Event Queue**: Transfers detection data (class, zone, timestamp) to the main process for PLC triggering and database logging.

---

## File Map

```
desktop/
├── main.py               Entry point. Initializes qasync event loop and MainWindow.
├── core/
│   └── app_state.py      Global shared state (ProcessManager, PLCManager, Config).
└── ui/
    ├── main_window.py    Dashboard UI: Camera grid, Event panel, Sidebar controls.
    ├── camera_widget.py  Camera rendering logic (OpenGL) and process worker threads.
    └── forms/            Configuration dialogs (Camera, PLC, ROI Editor).

backend/
├── camera_process.py     The "engine" loop running in isolated OS processes.
├── detector.py           AI logic — YOLO26 inference and ROI polygon filtering.
├── plc_manager.py        Orchestrates multi-PLC connectivity and many-to-many logic.
├── process_manager.py    Handles OS-level lifecycle of camera processes.
├── event_store.py        SQLite interface for detection history and auditing.
├── capture.py            RTSP connection stability and frame acquisition.
└── config.py             JSON-based configuration persistence.

data/                     Persistent storage (excluded from Git).
├── cameras_db.json       Camera definitions and AI settings.
├── plcs_db.json          PLC hardware definitions and mappings.
├── events.db             SQLite detection log.
└── captures/             Detection snapshots Gallery.
```

---

## Components

### 1. Camera Engine (`camera_process.py`)
Runs the compute-heavy computer vision pipeline. It is decoupled from the UI to ensure that even if the UI hangs (e.g., during window dragging), the detection and PLC alarms continue uninterrupted.

### 2. PLC Manager (`plc_manager.py`)
Handles industrial communication. 
- **Many-to-Many**: One camera can trigger multiple PLCs; one PLC can aggregate signals from multiple cameras.
- **Fault Tolerance**: Monitors "Lifebit" status for every configured PLC independently.

### 3. Desktop Dashboard (`main_window.py`)
A native PySide6 interface localized in Turkish.
- **Stretched Rendering**: Uses high-performance rendering to eliminate black bars.
- **Event Panel**: Live detection log with one-click snapshot viewing.
- **ROI Editor**: Interactive polygon drawing tool for defining security zones.

---

## Dependencies

- **Framework**: PySide6 (Qt for Python 6)
- **AI Engine**: Ultralytics YOLO26 + OpenVINO (Inference Acceleration)
- **Computer Vision**: OpenCV (RTSP & Annotation)
- **Industrial**: python-snap7 (Siemens S7 Protocol)
- **Async**: qasync (Bridges Python's asyncio with Qt's Event Loop)
- **Storage**: SQLite3

---

## Running Locally

```bash
# Setup environment
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Launch Application
python desktop/main.py
```
