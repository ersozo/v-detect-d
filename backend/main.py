"""FastAPI control plane — signaling, config, health.

This file owns ZERO camera pixels.  It only:
  - manages camera/PLC config (CRUD)
  - relays annotated JPEG frames from camera processes → WebSocket clients
  - relays control commands → camera processes
  - serves the React build for production

Matches arch.txt principle #5:
    "FastAPI for only control plane (signaling + config)"
"""

import asyncio
import logging
import os
import time
from fractions import Fraction
import numpy as np
import cv2
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Body
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# WebRTC imports
try:
    import av
    from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
    from aiortc.rtcrtpsender import RTCRtpSender
    WEBRTC_AVAILABLE = True
except ImportError as e:
    WEBRTC_AVAILABLE = False
    # Provide a fallback base class so that the module parses correctly
    # when aiortc/av are missing or fail to import on Windows.
    class MediaStreamTrack:
        pass

from config import (
    BASE_DIR,
    CAPTURES_DIR,
    EVENTS_DB_PATH,
    load_cameras,
    load_plc_config,
    save_cameras,
    save_plc_config,
)
from event_store import EventStore
from capture import RTSPCapture
from models import CameraConfig, PLCConfig, ROIUpdate, ZonesUpdate
from plc_client import SNAP7_AVAILABLE, check_connection
from plc_manager import PLCManager
from process_manager import ProcessManager

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ============================================================
# Global state
# ============================================================
cameras: dict[str, dict] = {}
process_mgr = ProcessManager(img_path=CAPTURES_DIR)
plc_mgr = PLCManager()
event_store = EventStore(EVENTS_DB_PATH)

# Frame streaming infrastructure
#   _client_queues: camera_id → set of asyncio.Queue (one per WS client)
#   _pump_tasks:    camera_id → asyncio.Task running the frame pump
_latest_frames: dict[str, bytes] = {}
_client_queues: dict[str, set[asyncio.Queue]] = {}
_pump_tasks: dict[str, asyncio.Task] = {}
_pump_frame_counts: dict[str, int] = {}
_last_frame_times: dict[str, float] = {}  # camera_id -> timestamp
_frame_executor = ThreadPoolExecutor(
    max_workers=32, thread_name_prefix="frame-pump"
)

# Alert broadcast: set of asyncio.Queue (one per /ws/alerts client)
_alert_clients: set[asyncio.Queue] = set()

# WebRTC PeerConnections and Active Tracks
_pcs: set = set()
_webrtc_client_counts: dict[str, int] = {}
_webrtc_tracks: dict[str, set[asyncio.Queue]] = {}


def _process_frame_for_webrtc(frame_bytes: bytes):
    """Heavy lifted decoding and reformatting for the thread pool."""
    img = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None

    # Fast resize for real-time streaming
    img = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_NEAREST)

    # Convert and wrap
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    frame = av.VideoFrame.from_ndarray(img_rgb, format="rgb24")
    return frame.reformat(format="yuv420p")


class CameraStreamTrack(MediaStreamTrack):
    """
    A video track that returns frames from the camera's frame pump via an internal queue.
    """
    kind = "video"

    def __init__(self, camera_id: str):
        super().__init__()
        self.camera_id = camera_id
        self._frame_count = 0
        self._start_time = None
        # Internal queue to receive frames from the pump
        self.queue = asyncio.Queue(maxsize=1)

        # Register this track's queue to the global fan-out
        _webrtc_tracks.setdefault(camera_id, set()).add(self.queue)

        # Prepare a black fallback frame once (720p)
        self._black_frame = av.VideoFrame.from_ndarray(
            np.zeros((720, 1280, 3), dtype=np.uint8), format="rgb24"
        ).reformat(format="yuv420p")

        logger.debug("WebRTC: Track created for camera %s", camera_id)

    async def recv(self):
        try:
            # Wait for the next frame from the pump
            frame_bytes = await self.queue.get()

            if self._start_time is None:
                self._start_time = time.time()

            # Offload heavy decoding/resizing/YUV conversion to thread pool
            loop = asyncio.get_running_loop()
            yuv_frame = await loop.run_in_executor(
                _frame_executor, _process_frame_for_webrtc, frame_bytes
            )

            if yuv_frame is None:
                yuv_frame = self._black_frame

            # Correct real-time PTS
            elapsed = time.time() - self._start_time
            yuv_frame.pts = int(elapsed * 90000)
            yuv_frame.time_base = Fraction(1, 90000)

            self._frame_count += 1
            if self._frame_count % 100 == 0:
                logger.debug("WebRTC: Sent 100 frames for %s", self.camera_id)

            return yuv_frame
        except Exception as e:
            logger.error("WebRTC track recv error: %s", e)
            # Returning a black frame is safer than None which can close the sender
            f = self._black_frame
            f.pts = self._frame_count * 4500 # fallback pts
            f.time_base = Fraction(1, 90000)
            return f

    def stop(self):
        """Clean up registration."""
        _webrtc_tracks.get(self.camera_id, set()).discard(self.queue)
        super().stop()


def _get_frame_blocking(q, timeout: float = 0.1):
    """Wait briefly for frame from MP queue."""
    return q.get(timeout=timeout)


# ============================================================
# Frame pump — bridges mp.Queue → per-client asyncio.Queue
# ============================================================


async def _frame_pump(camera_id: str) -> None:
    """Read frames from a camera process and fan-out to WS clients."""
    mp_queue = process_mgr.frame_queues.get(camera_id)
    if mp_queue is None:
        logger.error("No frame queue for camera %s", camera_id)
        return

    logger.info("Frame pump started for camera %s", camera_id)
    loop = asyncio.get_running_loop()
    frame_count = 0

    while camera_id in process_mgr.processes:
        try:
            frame = await loop.run_in_executor(
                _frame_executor, _get_frame_blocking, mp_queue
            )
        except Exception:
            continue

        frame_count += 1
        _pump_frame_counts[camera_id] = frame_count
        _latest_frames[camera_id] = frame
        _last_frame_times[camera_id] = time.time()

        if frame_count == 1:
            logger.info(
                "Frame pump: first frame received for %s (%d bytes)",
                camera_id,
                len(frame),
            )

        # Fan-out to every connected WebSocket client (leaky per client)
        for client_q in list(_client_queues.get(camera_id, set())):
            try:
                # Drain stale frame so client always gets the latest
                while not client_q.empty():
                    try:
                        client_q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                client_q.put_nowait(frame)
            except Exception:
                pass

        # Fan-out to WebRTC tracks
        for rtc_q in list(_webrtc_tracks.get(camera_id, set())):
            try:
                # Same leaky logic: always deliver the freshest frame
                while not rtc_q.empty():
                    rtc_q.get_nowait()
                rtc_q.put_nowait(frame)
            except Exception:
                pass

    logger.info("Frame pump stopped for camera %s", camera_id)


def _start_pump(camera_id: str) -> None:
    if camera_id in _pump_tasks:
        _pump_tasks[camera_id].cancel()
    _pump_tasks[camera_id] = asyncio.create_task(_frame_pump(camera_id))


def _stop_pump(camera_id: str) -> None:
    task = _pump_tasks.pop(camera_id, None)
    if task:
        task.cancel()
    _latest_frames.pop(camera_id, None)
    _client_queues.pop(camera_id, None)
    _pump_frame_counts.pop(camera_id, None)
    _last_frame_times.pop(camera_id, None)


async def _on_camera_restart(camera_id: str) -> None:
    """Callback from health-check after a dead process is respawned."""
    _stop_pump(camera_id)
    _start_pump(camera_id)
    plc_mgr.set_event_queues(process_mgr.event_queues)


def _update_camera_quality(camera_id: str) -> None:
    """Adjust JPEG quality based on number of active listeners."""
    ws_clients = len(_client_queues.get(camera_id, set()))
    webrtc_clients = _webrtc_client_counts.get(camera_id, 0)
    num_clients = ws_clients + webrtc_clients

    # Simple adaptive logic:
    if num_clients <= 1:
        quality = 85
    elif num_clients == 2:
        quality = 70
    elif num_clients == 3:
        quality = 50
    else:
        quality = 35

    process_mgr.send_command(camera_id, {"cmd": "update_quality", "quality": quality})
    logger.debug("Updated camera %s quality to %d (%d clients)", camera_id, quality, num_clients)


# ============================================================
# Lifespan
# ============================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Safety Detection System …")

    global cameras
    cameras = load_cameras()
    plc_config = load_plc_config()
    plc_mgr.set_config(plc_config)
    plc_mgr.set_cameras(cameras)
    plc_mgr.set_event_store(event_store)
    plc_mgr.set_alert_callback(_broadcast_alert)

    # Spawn one OS-process per camera
    for cam_id, cam_data in cameras.items():
        process_mgr.start_camera(cam_data)
        _start_pump(cam_id)

    plc_mgr.set_event_queues(process_mgr.event_queues)

    plc_task = asyncio.create_task(plc_mgr.run())
    health_task = asyncio.create_task(
        process_mgr.health_check_loop(on_restart=_on_camera_restart)
    )

    yield

    logger.info("Shutting down …")
    plc_mgr.stop()
    plc_task.cancel()
    health_task.cancel()
    for cid in list(_pump_tasks):
        _stop_pump(cid)

    # Close all WebRTC connections
    coros = [pc.close() for pc in _pcs]
    if coros:
        await asyncio.gather(*coros)
    _pcs.clear()

    process_mgr.stop_all()
    _frame_executor.shutdown(wait=False)
    event_store.close()


app = FastAPI(title="Safety Detection System", lifespan=lifespan)

from auth import APIKeyMiddleware  # noqa: E402

app.add_middleware(APIKeyMiddleware)


@app.get("/api/health")
async def get_health():
    """Returns the aggregate status of the system."""
    active_count = len(process_mgr.processes)
    status = "monitoring" if active_count > 0 else "standby"
    return {
        "status": "success",
        "system_status": status,
        "active_cameras": active_count,
        "total_cameras": len(cameras)
    }


# ---- static mounts ----

STATIC_DIR = os.path.join(BASE_DIR, "static")
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.mount("/captures", StaticFiles(directory=CAPTURES_DIR), name="captures")

REACT_BUILD_DIR = os.path.join(BASE_DIR, "static", "react")
REACT_ASSETS_DIR = os.path.join(REACT_BUILD_DIR, "assets")
if os.path.exists(REACT_ASSETS_DIR):
    app.mount(
        "/assets",
        StaticFiles(directory=REACT_ASSETS_DIR),
        name="react-assets",
    )


# ============================================================
# Camera CRUD
# ============================================================


@app.get("/api/cameras")
async def list_cameras():
    now = time.time()
    # Iterate over a copy of camera values to add 'is_connected' status
    # without modifying the global 'cameras' dictionary directly for the loop.
    # The original `cameras` is a dict {id: camera_data_dict}.
    # We want to return a list of these camera_data_dicts with `is_connected` added.
    camera_list_with_status = []
    for cam_id, cam_data in cameras.items():
        # Create a mutable copy of the camera data to add 'is_connected'
        cam_data_copy = cam_data.copy()
        # A camera is connected if its process is alive AND it sent a frame in the last 5 seconds
        last_time = _last_frame_times.get(cam_id, 0)
        proc = process_mgr.processes.get(cam_id)
        cam_data_copy["is_connected"] = (now - last_time < 5.0) and (proc.is_alive() if proc else False)
        camera_list_with_status.append(cam_data_copy)

    return {"status": "success", "cameras": camera_list_with_status}


@app.post("/api/cameras/test-connection")
async def test_camera_connection(config: CameraConfig):
    """Attempt to open the RTSP stream and return connectivity info."""
    url = config.get_rtsp_url()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        _frame_executor, RTSPCapture.test_connection, url
    )
    return {"status": "success", **result}


@app.post("/api/cameras")
async def add_camera(config: CameraConfig):
    camera_data = config.model_dump()
    camera_data["url"] = config.get_rtsp_url()
    cameras[config.id] = camera_data
    save_cameras(cameras)
    plc_mgr.set_cameras(cameras)

    process_mgr.start_camera(camera_data)
    _start_pump(config.id)
    plc_mgr.set_event_queues(process_mgr.event_queues)

    return {"status": "success", "camera": camera_data}


@app.put("/api/cameras/{camera_id}")
async def update_camera(camera_id: str, config: CameraConfig):
    if camera_id not in cameras:
        return {"status": "error", "message": "Camera not found"}

    config.id = camera_id
    old = cameras[camera_id]

    # Detect whether we need a full process restart
    needs_restart = any(
        [
            old.get("ip") != config.ip,
            old.get("port") != config.port,
            old.get("username") != config.username,
            old.get("password") != config.password,
            old.get("stream_path") != config.stream_path,
            old.get("model_size") != config.model_size,
            old.get("custom_model") != config.custom_model,
        ]
    )

    camera_data = config.model_dump()
    camera_data["url"] = config.get_rtsp_url()

    # Preserve existing ROI when not explicitly provided
    if config.roi is None and old.get("roi"):
        camera_data["roi"] = old["roi"]

    cameras[camera_id] = camera_data
    save_cameras(cameras)
    plc_mgr.set_cameras(cameras)

    if needs_restart:
        _stop_pump(camera_id)
        process_mgr.stop_camera(camera_id)
        process_mgr.start_camera(camera_data)
        _start_pump(camera_id)
        plc_mgr.set_event_queues(process_mgr.event_queues)
    else:
        # Hot-update running process via control queue
        updates: dict = {"cmd": "update_config"}
        if config.confidence != old.get("confidence"):
            updates["confidence"] = config.confidence
        if config.frame_skip != old.get("frame_skip"):
            updates["frame_skip"] = config.frame_skip
        if config.blur_faces != old.get("blur_faces"):
            updates["blur_faces"] = config.blur_faces
        if config.detect_classes != old.get("detect_classes"):
            updates["detect_classes"] = config.detect_classes
        if len(updates) > 1:
            process_mgr.send_command(camera_id, updates)

        new_roi = camera_data.get("roi")
        if new_roi != old.get("roi"):
            if new_roi:
                process_mgr.send_command(
                    camera_id, {"cmd": "set_roi", "points": new_roi}
                )
            else:
                process_mgr.send_command(camera_id, {"cmd": "clear_roi"})

    return {"status": "success", "camera": camera_data}


@app.delete("/api/cameras/{camera_id}")
async def remove_camera(camera_id: str):
    if camera_id not in cameras:
        return {"status": "error", "message": "Camera not found"}

    _stop_pump(camera_id)
    process_mgr.stop_camera(camera_id)
    del cameras[camera_id]
    save_cameras(cameras)
    plc_mgr.set_cameras(cameras)
    plc_mgr.set_event_queues(process_mgr.event_queues)

    return {"status": "success"}


# ============================================================
# ROI
# ============================================================


@app.put("/api/cameras/{camera_id}/roi")
async def update_roi(camera_id: str, roi: ROIUpdate):
    if camera_id not in cameras:
        return {"status": "error", "message": "Camera not found"}

    points = [{"x": p.x, "y": p.y} for p in roi.points]
    cameras[camera_id]["roi"] = points
    save_cameras(cameras)
    plc_mgr.set_cameras(cameras)
    process_mgr.send_command(camera_id, {"cmd": "set_roi", "points": points})

    return {"status": "success", "roi": points}


@app.delete("/api/cameras/{camera_id}/roi")
async def clear_roi(camera_id: str):
    if camera_id not in cameras:
        return {"status": "error", "message": "Camera not found"}

    cameras[camera_id]["roi"] = None
    save_cameras(cameras)
    process_mgr.send_command(camera_id, {"cmd": "clear_roi"})

    return {"status": "success"}


# ---- Zones (multi-zone ROI) ----


@app.put("/api/cameras/{camera_id}/zones")
async def update_zones(camera_id: str, body: ZonesUpdate):
    if camera_id not in cameras:
        return {"status": "error", "message": "Camera not found"}

    zones = [
        {"name": z.name, "points": [{"x": p.x, "y": p.y} for p in z.points],
         "severity": z.severity}
        for z in body.zones
    ]
    cameras[camera_id]["zones"] = zones
    cameras[camera_id]["roi"] = None
    save_cameras(cameras)
    process_mgr.send_command(camera_id, {"cmd": "set_zones", "zones": zones})

    return {"status": "success", "zones": zones}


@app.delete("/api/cameras/{camera_id}/zones")
async def clear_zones(camera_id: str):
    if camera_id not in cameras:
        return {"status": "error", "message": "Camera not found"}

    cameras[camera_id]["zones"] = None
    save_cameras(cameras)
    process_mgr.send_command(camera_id, {"cmd": "clear_zones"})

    return {"status": "success"}


@app.get("/api/cameras/{camera_id}/frame")
async def get_camera_frame(camera_id: str):
    if camera_id not in cameras:
        return {"status": "error", "message": "Camera not found"}

    process_mgr.send_command(camera_id, {"cmd": "get_frame"})
    frame_bytes = await process_mgr.get_response(camera_id, timeout=5.0)

    if frame_bytes:
        return StreamingResponse(
            iter([frame_bytes]), media_type="image/jpeg"
        )
    return {"status": "error", "message": "Could not capture frame"}


# ============================================================
# PLC
# ============================================================


@app.get("/api/plcs")
async def list_plcs():
    db = load_plc_config()
    # Use real-time status from PLCManager instead of blocking checks
    statuses = plc_mgr.get_statuses()
    for plc_id, inst in db["instances"].items():
        inst["is_connected"] = statuses.get(plc_id, False)
    return db


@app.get("/api/plc/config")
async def get_legacy_plc_config():
    """Returns the default PLC for backward compatibility with old UI."""
    db = load_plc_config()
    default_id = db.get("default_plc_id")
    if not default_id or default_id not in db["instances"]:
        # Fallback if somehow missing
        return {"enabled": False, "snap7_available": SNAP7_AVAILABLE}

    config = db["instances"][default_id]
    config["snap7_available"] = SNAP7_AVAILABLE
    config["is_connected"] = plc_mgr.get_statuses().get(default_id, False)
    return config


@app.put("/api/plc/config")
async def update_legacy_plc_config(config: dict):
    """Updates the default PLC for backward compatibility."""
    db = load_plc_config()
    default_id = db.get("default_plc_id")
    if not default_id:
        return {"status": "error", "message": "No default PLC found"}

    db["instances"][default_id].update(config)
    save_plc_config(db)
    plc_mgr.set_config(db)
    return {"status": "success", "config": db["instances"][default_id]}


@app.post("/api/plcs")
async def add_plc_instance(instance: dict):
    db = load_plc_config()
    plc_id = instance.get("id") or f"plc_{int(time.time())}"
    instance["id"] = plc_id
    db["instances"][plc_id] = instance
    if not db.get("default_plc_id"):
        db["default_plc_id"] = plc_id

    save_plc_config(db)
    plc_mgr.set_config(db)
    return {"status": "success", "id": plc_id}


@app.put("/api/plcs/{plc_id}")
async def update_plc_instance(plc_id: str, instance: dict):
    db = load_plc_config()
    if plc_id not in db["instances"]:
        return {"status": "error", "message": "PLC not found"}

    db["instances"][plc_id].update(instance)
    save_plc_config(db)
    plc_mgr.set_config(db)
    return {"status": "success"}


@app.delete("/api/plcs/{plc_id}")
async def delete_plc_instance(plc_id: str):
    db = load_plc_config()
    if plc_id not in db["instances"]:
        return {"status": "error", "message": "PLC not found"}

    del db["instances"][plc_id]
    if db.get("default_plc_id") == plc_id:
        db["default_plc_id"] = next(iter(db["instances"].keys())) if db["instances"] else None

    save_plc_config(db)
    plc_mgr.set_config(db)
    return {"status": "success"}


# ============================================================
# Events (audit trail)
# ============================================================


@app.get("/api/events")
async def get_events(
    camera_id: str | None = None,
    from_ts: float | None = None,
    to_ts: float | None = None,
    limit: int = 100,
    offset: int = 0,
):
    loop = asyncio.get_running_loop()
    events = await loop.run_in_executor(
        _frame_executor,
        lambda: event_store.query(
            camera_id=camera_id, from_ts=from_ts, to_ts=to_ts,
            limit=min(limit, 1000), offset=offset,
        )
    )
    total = await loop.run_in_executor(
        _frame_executor,
        lambda: event_store.count(
            camera_id=camera_id, from_ts=from_ts, to_ts=to_ts,
        )
    )
    return {"events": events, "total": total, "limit": limit, "offset": offset}


# ============================================================
# Reports (detection captures)
# ============================================================


@app.get("/api/reports")
async def get_reports():
    def scan_reports():
        reports = []
        if not os.path.exists(CAPTURES_DIR):
            return reports
        for entry in os.scandir(CAPTURES_DIR):
            if entry.is_file() and entry.name.endswith(".jpg"):
                try:
                    ts = int(entry.name.split(".")[0])
                    reports.append({
                        "id": entry.name,
                        "camera_id": None,
                        "timestamp": ts,
                        "image_url": f"/captures/{entry.name}",
                    })
                except ValueError:
                    continue
            elif entry.is_dir():
                cam_id = entry.name
                cam_dir = entry.path
                for f in os.listdir(cam_dir):
                    if not f.endswith(".jpg"):
                        continue
                    try:
                        ts = int(f.split(".")[0])
                        reports.append({
                            "id": f"{cam_id}/{f}",
                            "camera_id": cam_id,
                            "timestamp": ts,
                            "image_url": f"/captures/{cam_id}/{f}",
                        })
                    except ValueError:
                        continue
        reports.sort(key=lambda x: x["timestamp"], reverse=True)
        return reports

    loop = asyncio.get_running_loop()
    reports = await loop.run_in_executor(_frame_executor, scan_reports)
    return reports


@app.delete("/api/reports/{report_id:path}")
async def delete_report(report_id: str):
    if ".." in report_id:
        return {"status": "error", "message": "Invalid report ID"}
    path = os.path.join(CAPTURES_DIR, report_id)
    if os.path.exists(path) and os.path.isfile(path):
        os.remove(path)
        return {"status": "success"}
    return {"status": "error", "message": "Report not found"}


@app.delete("/api/reports")
async def delete_all_reports():
    count = 0
    if not os.path.exists(CAPTURES_DIR):
        return {"status": "success", "deleted": 0}
    for root, _dirs, files in os.walk(CAPTURES_DIR):
        for f in files:
            if f.endswith(".jpg"):
                os.remove(os.path.join(root, f))
                count += 1
    return {"status": "success", "deleted": count}


# ============================================================
# WebSocket streaming  (frame broadcast to N clients)
# ============================================================


@app.post("/api/webrtc/offer/{camera_id}")
async def webrtc_offer(camera_id: str, offer: dict = Body(...)):
    if not WEBRTC_AVAILABLE:
        return {"error": "WebRTC not available on server (missing dependencies)"}

    if camera_id not in cameras:
        return {"error": "Camera not found"}

    pc = RTCPeerConnection()
    _pcs.add(pc)

    # Increment client count for this camera
    _webrtc_client_counts[camera_id] = _webrtc_client_counts.get(camera_id, 0) + 1
    _update_camera_quality(camera_id)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        if pc.connectionState == "failed" or pc.connectionState == "closed":
            await pc.close()
            _pcs.discard(pc)
            # Decrement client count
            _webrtc_client_counts[camera_id] = max(
                0, _webrtc_client_counts.get(camera_id, 1) - 1
            )
            _update_camera_quality(camera_id)
            logger.info("WebRTC connection closed for camera %s", camera_id)

    # Create track
    track = CameraStreamTrack(camera_id)

    # Add transceiver with the track and force VP8 codec for maximum compatibility
    transceiver = pc.addTransceiver(track, direction="sendonly")
    try:
        capabilities = RTCRtpSender.getCapabilities("video")
        # Find VP8 in the supported codecs
        vp8_codecs = [c for c in capabilities.codecs if c.name == "VP8"]
        if vp8_codecs:
            transceiver.setCodecPreferences(vp8_codecs)
            logger.debug("WebRTC: Forced VP8 codec for camera %s", camera_id)
    except Exception as e:
        logger.warning("WebRTC: Could not set VP8 preference: %s", e)

    # Handle offer
    await pc.setRemoteDescription(
        RTCSessionDescription(sdp=offer["sdp"], type=offer["type"])
    )

    # Create answer
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    logger.info("WebRTC offer handled for camera %s", camera_id)
    return {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type}


# ============================================================
# Alert WebSocket  (detection state changes → all clients)
# ============================================================


def _broadcast_alert(event: dict) -> None:
    """Called from PLCManager (sync context) on detection state changes."""
    import json as _json
    payload = _json.dumps(event)
    logger.info("Broadcasting UI Alert for %s: %s (clients=%d)",
                event.get('camera_id'), event.get('person_detected'), len(_alert_clients))
    for q in list(_alert_clients):
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            try:
                q.get_nowait()
                q.put_nowait(payload)
            except Exception:
                pass


@app.websocket("/ws/alerts")
async def ws_alerts(websocket: WebSocket):
    await websocket.accept()
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
    _alert_clients.add(q)
    logger.info("Alert WS client connected (total=%d)", len(_alert_clients))

    async def reader():
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass

    reader_task = asyncio.create_task(reader())

    try:
        while True:
            # Check if client disconnected
            if reader_task.done():
                break

            try:
                # Wait for alert, send ping if idle for 15s to keep proxy alive
                msg = await asyncio.wait_for(q.get(), timeout=15.0)
                await websocket.send_text(msg)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
            except Exception:
                break
    finally:
        reader_task.cancel()
        _alert_clients.discard(q)
        logger.info("Alert WS client disconnected (total=%d)", len(_alert_clients))


@app.websocket("/ws/{camera_id}")
async def ws_stream(websocket: WebSocket, camera_id: str):
    await websocket.accept()

    if camera_id not in cameras:
        await websocket.send_json({"error": "Camera not found"})
        await websocket.close()
        return

    # Each client gets its own asyncio.Queue fed by the frame pump
    client_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
    _client_queues.setdefault(camera_id, set()).add(client_q)

    _update_camera_quality(camera_id)

    async def reader():
        try:
            while True:
                await websocket.receive_text()
        except Exception:
            pass

    reader_task = asyncio.create_task(reader())

    try:
        while True:
            if reader_task.done():
                break
            try:
                # Wait for frame, send ping if idle for 15s
                frame = await asyncio.wait_for(client_q.get(), timeout=15.0)
                await websocket.send_bytes(frame)
            except asyncio.TimeoutError:
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
            except Exception:
                break
    except Exception:
        pass
    finally:
        reader_task.cancel()
        _client_queues.get(camera_id, set()).discard(client_q)
        _update_camera_quality(camera_id)
        logger.info("WebSocket client disconnected for camera %s", camera_id)


# ============================================================
# MJPEG fallback  (backward compatibility / embedding)
# ============================================================


@app.get("/video/{camera_id}")
async def video_feed(camera_id: str):
    if camera_id not in cameras:
        return {"status": "error", "message": "Camera not found"}

    async def generate():
        client_q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=2)
        _client_queues.setdefault(camera_id, set()).add(client_q)
        _update_camera_quality(camera_id)
        try:
            while True:
                frame = await client_q.get()
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )
        finally:
            _client_queues.get(camera_id, set()).discard(client_q)
            _update_camera_quality(camera_id)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ============================================================
# React frontend
# ============================================================


_DEV_HTML = HTMLResponse(
    content=(
        "<html><body style='font-family:sans-serif;padding:40px;"
        "background:#1e293b;color:#f1f5f9'>"
        "<h1>Development Mode</h1>"
        "<p>React dev server: "
        "<a href='http://localhost:3000' style='color:#3b82f6'>"
        "http://localhost:3000</a></p></body></html>"
    )
)


def _serve_react():
    react_index = os.path.join(REACT_BUILD_DIR, "index.html")
    if os.path.exists(react_index):
        return FileResponse(react_index)
    return _DEV_HTML


@app.get("/", response_class=HTMLResponse)
async def index():
    return _serve_react()


@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str):
    """SPA catch-all: serve index.html for any route not matched above."""
    return _serve_react()


# ============================================================
# Debug / health
# ============================================================


@app.get("/api/debug/pipeline")
async def debug_pipeline():
    """Shows the state of every camera pipeline for troubleshooting."""
    info = {}
    for cam_id in cameras:
        proc = process_mgr.processes.get(cam_id)
        info[cam_id] = {
            "process_alive": proc.is_alive() if proc else False,
            "process_pid": proc.pid if proc else None,
            "pump_frames_received": _pump_frame_counts.get(cam_id, 0),
            "has_latest_frame": cam_id in _latest_frames,
            "latest_frame_size": len(_latest_frames[cam_id])
            if cam_id in _latest_frames
            else 0,
            "ws_clients": len(_client_queues.get(cam_id, set())),
        }
    return info


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error("Unhandled error: %s", exc)
    return {"status": "error", "message": str(exc)}


# ============================================================
# Entry point
# ============================================================

if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()

    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
