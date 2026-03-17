"""Per-camera subprocess — capture, detect, annotate, publish.

Each camera runs in its own OS process for CPU isolation (no GIL
contention between cameras).  Communication with the main process
happens exclusively through multiprocessing Queues:

    frame_queue    – latest annotated JPEG  (leaky, maxsize=1)
    event_queue    – latest detection event  (leaky, maxsize=1)
    control_queue  – commands from main       (unbounded)
    response_queue – one-shot replies          (maxsize=1)
"""

import logging
import multiprocessing
import os
import sys
import time
from queue import Empty, Full

import cv2
import numpy as np
from translations import translate_label

# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
BBOX_COLOR = (0, 255, 255)
ROI_COLOR = (0, 255, 0)
JPEG_QUALITY = [cv2.IMWRITE_JPEG_QUALITY, 75]


def _put_leaky(q: multiprocessing.Queue, item: object) -> None:
    """Put *item*, silently discarding the oldest entry if the queue is full."""
    try:
        q.get_nowait()
    except Empty:
        pass
    try:
        q.put_nowait(item)
    except Full:
        pass


def _draw_roi(frame: np.ndarray, polygon: np.ndarray,
              color=None, label: str = "ROI Zone") -> None:
    if polygon is None or len(polygon) < 3:
        return
    c = color or ROI_COLOR
    overlay = frame.copy()
    cv2.fillPoly(overlay, [polygon], c)
    cv2.addWeighted(overlay, 0.2, frame, 0.8, 0, frame)
    cv2.polylines(frame, [polygon], True, c, 4)
    for pt in polygon:
        cv2.circle(frame, tuple(pt), 5, c, -1)
    cv2.putText(
        frame,
        label,
        (polygon[0][0] + 10, polygon[0][1] - 10),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        c,
        2,
    )


def _draw_detections(
    frame: np.ndarray,
    detections: list[dict],
    class_names: dict[int, str] | None = None,
    blur_faces: bool = False,
) -> None:
    for det in detections:
        if not det["in_roi"]:
            continue
        x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]

        if blur_faces:
            _blur_face_region(frame, x1, y1, x2, y2)

        cv2.rectangle(frame, (x1, y1), (x2, y2), BBOX_COLOR, 6)
        cls_id = det.get("class_id", 0)

        if class_names and cls_id in class_names:
            label = translate_label(class_names[cls_id])
        else:
            label = f"ID:{cls_id}" if cls_id != 0 else "Nesne"

        cv2.putText(
            frame,
            f"{label} {det['confidence']:.2f}",
            (x1, y1 - 10),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            BBOX_COLOR,
            2,
        )


def _blur_face_region(
    frame: np.ndarray, x1: int, y1: int, x2: int, y2: int
) -> None:
    """Gaussian-blur the estimated head area (top ~22 % of the bbox)."""
    h = y2 - y1
    w = x2 - x1
    fh, fw = frame.shape[:2]

    fy1 = max(0, y1)
    fy2 = min(fh, y1 + int(h * 0.22))
    fx1 = max(0, x1)
    fx2 = min(fw, x2)

    if fy2 > fy1 and fx2 > fx1:
        roi = frame[fy1:fy2, fx1:fx2]
        ks = (max(3, (w // 7) | 1), max(3, (h // 7) | 1))
        frame[fy1:fy2, fx1:fx2] = cv2.GaussianBlur(roi, ks, 30)


# ---------------------------------------------------------------------------
# ROI / Zone helpers
# ---------------------------------------------------------------------------

ZONE_COLORS = [
    (0, 255, 0),    # green  (warning)
    (0, 0, 255),    # red    (danger)
    (0, 255, 255),  # yellow
    (255, 0, 255),  # magenta
    (255, 165, 0),  # orange
]


def _compute_roi(roi_points: list[dict] | None):
    """Return (polygon ndarray, bbox dict) or (None, None)."""
    if not roi_points or len(roi_points) < 3:
        return None, None
    polygon = np.array(
        [[p["x"], p["y"]] for p in roi_points], dtype=np.int32
    )
    xs = [p["x"] for p in roi_points]
    ys = [p["y"] for p in roi_points]
    bbox = {"x": min(xs), "y": min(ys), "x2": max(xs), "y2": max(ys)}
    return polygon, bbox


def _compute_zones(zones: list[dict] | None):
    """Convert zone dicts into a list of (name, severity, polygon, bbox)."""
    if not zones:
        return []
    result = []
    for z in zones:
        points = z.get("points", [])
        if len(points) < 3:
            continue
        polygon = np.array(
            [[p["x"], p["y"]] for p in points], dtype=np.int32
        )
        xs = [p["x"] for p in points]
        ys = [p["y"] for p in points]
        bbox = {"x": min(xs), "y": min(ys), "x2": max(xs), "y2": max(ys)}
        result.append((
            z.get("name", f"Zone {len(result)+1}"),
            z.get("severity", "warning"),
            polygon,
            bbox,
        ))
    return result


def _merge_bboxes(bboxes: list[dict]) -> dict:
    """Compute the bounding box that encloses all given bboxes."""
    return {
        "x": min(b["x"] for b in bboxes),
        "y": min(b["y"] for b in bboxes),
        "x2": max(b["x2"] for b in bboxes),
        "y2": max(b["y2"] for b in bboxes),
    }


# ---------------------------------------------------------------------------
# Camera subprocess
# ---------------------------------------------------------------------------


class CameraProcess(multiprocessing.Process):
    """One instance per camera.  Fully isolated from the main process."""

    def __init__(
        self,
        camera_id: str,
        rtsp_url: str,
        model_size: str,
        confidence: float,
        frame_skip: int,
        roi: list | None,
        zones: list | None,
        blur_faces: bool,
        img_path: str,
        frame_queue: multiprocessing.Queue,
        event_queue: multiprocessing.Queue,
        control_queue: multiprocessing.Queue,
        response_queue: multiprocessing.Queue,
        stop_event: multiprocessing.Event,
        detect_classes: list[int] = [0],
        custom_model: str | None = None,
    ):
        super().__init__(daemon=True, name=f"Camera-{camera_id}")
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.model_size = model_size
        self.confidence = confidence
        self.frame_skip = max(0, frame_skip)
        self.roi = roi
        self.zones = zones
        self.blur_faces = blur_faces
        self.img_path = img_path
        self.detect_classes = detect_classes
        self.custom_model = custom_model
        # IPC channels
        self.frame_queue = frame_queue
        self.event_queue = event_queue
        self.control_queue = control_queue
        self.response_queue = response_queue
        self.stop_event = stop_event
        self.jpeg_quality = 75
        self.data_collection = {
            "enabled": False,
            "mode": "frames",
            "interval": 5
        }
        self.video_writer = None

    # ------------------------------------------------------------------
    # Main loop (runs in child process)
    # ------------------------------------------------------------------

    def run(self) -> None:
        # Ensure backend/ is importable even on Windows spawn
        sys.path.insert(
            0, os.path.dirname(os.path.abspath(__file__))
        )

        logging.basicConfig(
            level=logging.INFO,
            format=f"[%(levelname)s] [cam:{self.camera_id}] %(message)s",
        )
        log = logging.getLogger(f"camera.{self.camera_id}")

        from capture import RTSPCapture
        from detector import Detector

        log.info("Process started – %s", self.rtsp_url)

        capture = RTSPCapture(self.rtsp_url)
        model_path = self.custom_model if self.custom_model else self.model_size
        detector = Detector(model_path, self.confidence)
        class_names = detector.get_names()

        roi_polygon, roi_bbox = _compute_roi(self.roi)
        zone_data = _compute_zones(self.zones)

        os.makedirs(self.img_path, exist_ok=True)

        frame_count = 0
        last_detections: list[dict] = []
        detection_active = False
        last_save_ts = 0.0

        while not self.stop_event.is_set():
            # --- control commands (non-blocking) ---
            roi_polygon, roi_bbox, zone_data = self._process_commands(
                capture, detector, roi_polygon, roi_bbox, zone_data
            )

            # --- capture ---
            frame = capture.read()
            if frame is None:
                capture.reconnect()
                continue

            # --- detect (respecting frame_skip and data_collection) ---
            # Default behavior: Disable detection when collecting data to save CPU
            is_collecting = self.data_collection.get("enabled", False)
            
            should_detect = (not is_collecting) and (
                self.frame_skip == 0
                or frame_count % (self.frame_skip + 1) == 0
            )

            if is_collecting:
                last_detections = []
                detection_active = False

            if should_detect:
                if zone_data:
                    all_bboxes = [z[3] for z in zone_data]
                    merged_bbox = _merge_bboxes(all_bboxes) if all_bboxes else None
                    raw_dets = detector.detect(
                        frame, None, merged_bbox, self.detect_classes
                    )
                    last_detections = []
                    for det in raw_dets:
                        cx = (det["x1"] + det["x2"]) // 2
                        cy = (det["y1"] + det["y2"]) // 2
                        in_any_zone = False
                        for _name, _sev, poly, _bb in zone_data:
                            if cv2.pointPolygonTest(poly, (float(cx), float(cy)), False) >= 0:
                                in_any_zone = True
                                break
                        det["in_roi"] = in_any_zone
                        last_detections.append(det)
                else:
                    last_detections = detector.detect(
                        frame, roi_polygon, roi_bbox, self.detect_classes
                    )
                detection_active = any(
                    d["in_roi"] for d in last_detections
                )

            # --- annotate ---
            display = frame.copy()
            _draw_detections(display, last_detections, class_names, self.blur_faces)
            if zone_data:
                for i, (zname, zsev, zpoly, _zbb) in enumerate(zone_data):
                    # Default color from list
                    color = ZONE_COLORS[i % len(ZONE_COLORS)]

                    # Force explicit colors for known severities (including legacy TR keys)
                    if zsev in ["danger", "alarm"]:
                        color = (0, 0, 255)  # Red (BGR)
                    elif zsev in ["warning", "uyarı"]:
                        color = (0, 255, 0)  # Green (BGR)

                    _draw_roi(display, zpoly, color=color, label=zname)
            else:
                _draw_roi(display, roi_polygon)

            # --- encode ---
            quality_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
            ok, jpeg = cv2.imencode(".jpg", display, quality_params)
            if not ok:
                frame_count += 1
                continue
            frame_bytes = jpeg.tobytes()

            # --- publish (leaky queues — always latest, never backlog) ---
            detected_objs = [d for d in last_detections if d["in_roi"]]
            main_label = "Tespit"
            if detected_objs and class_names:
                cls_id = detected_objs[0].get("class_id", 0)
                main_label = translate_label(class_names.get(cls_id, "Nesne"))

            _put_leaky(self.frame_queue, frame_bytes)
            _put_leaky(
                self.event_queue,
                {
                    "camera_id": self.camera_id,
                    "is_detected": detection_active,
                    "count": len(detected_objs),
                    "label": main_label,
                    "timestamp": time.time(),
                },
            )

            # --- save capture (throttle to 1 per second) ---
            now = time.time()
            if detection_active and should_detect and now - last_save_ts >= 1.0:
                last_save_ts = now
                try:
                    cv2.imwrite(
                        os.path.join(self.img_path, f"{int(now)}.jpg"),
                        display,
                    )
                except Exception:
                    pass

            # --- Data Collection (Raw frames or video for training) ---
            if self.data_collection.get("enabled"):
                mode = self.data_collection.get("mode", "frames")
                train_dir = os.path.join(self.img_path, "training")
                if not os.path.exists(train_dir):
                    os.makedirs(train_dir, exist_ok=True)

                if mode == "frames":
                    # Release video writer if it was active
                    if self.video_writer:
                        self.video_writer.release()
                        self.video_writer = None

                    interval = self.data_collection.get("interval", 5)
                    if frame_count % interval == 0:
                        try:
                            ts_ms = int(time.time() * 1000)
                            cv2.imwrite(
                                os.path.join(train_dir, f"raw_{ts_ms}.jpg"),
                                frame,
                            )
                        except Exception: pass
                
                elif mode == "video":
                    if self.video_writer is None:
                        # Initialize VideoWriter
                        ts_ms = int(time.time() * 1000)
                        # Switch to AVI/XVID for better stability on Windows
                        v_path = os.path.join(train_dir, f"rec_{ts_ms}.avi")
                        # MJPG is widely supported on Windows without extra codecs
                        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
                        h, w = frame.shape[:2]
                        # Try to get real FPS from capture, else default to 20
                        fps = capture.get_fps()
                        if fps is None or fps <= 0 or fps > 120: 
                            fps = 20.0
                            
                        self.video_writer = cv2.VideoWriter(v_path, fourcc, fps, (w, h))
                        if not self.video_writer.isOpened():
                            log.error("Failed to open VideoWriter for path: %s", v_path)
                            self.video_writer = None
                        else:
                            log.info("Started video recording: %s at %d FPS (%dx%d)", v_path, fps, w, h)
                    
                    if self.video_writer:
                        self.video_writer.write(frame)
            else:
                # Collection disabled, ensure video writer is released
                if self.video_writer:
                    log.info("Closing video recording.")
                    self.video_writer.release()
                    self.video_writer = None

            frame_count += 1

            if frame_count == 1:
                log.info("First frame captured and queued")
            elif frame_count % 300 == 0:
                log.info("Frames processed: %d", frame_count)

        if self.video_writer:
            self.video_writer.release()
            self.video_writer = None
            
        capture.release()
        log.info("Process stopped")

    # ------------------------------------------------------------------
    # Control command handler
    # ------------------------------------------------------------------

    def _process_commands(self, capture, detector, roi_polygon, roi_bbox, zone_data):
        """Drain the control queue (non-blocking)."""
        try:
            while True:
                cmd = self.control_queue.get_nowait()
                action = cmd.get("cmd")

                if action == "set_roi":
                    self.roi = cmd["points"]
                    roi_polygon, roi_bbox = _compute_roi(self.roi)
                    self.zones = None
                    zone_data = []

                elif action == "clear_roi":
                    self.roi = None
                    roi_polygon, roi_bbox = None, None
                    self.zones = None
                    zone_data = []

                elif action == "set_zones":
                    self.zones = cmd["zones"]
                    zone_data = _compute_zones(self.zones)
                    self.roi = None
                    roi_polygon, roi_bbox = None, None

                elif action == "clear_zones":
                    self.zones = None
                    zone_data = []

                elif action == "update_config":
                    if "confidence" in cmd:
                        self.confidence = cmd["confidence"]
                        detector.set_confidence(cmd["confidence"])
                    if "frame_skip" in cmd:
                        self.frame_skip = max(0, cmd["frame_skip"])
                    if "blur_faces" in cmd:
                        self.blur_faces = cmd["blur_faces"]
                    if "detect_classes" in cmd:
                        self.detect_classes = cmd["detect_classes"]

                elif action == "update_quality":
                    if "quality" in cmd:
                        self.jpeg_quality = max(10, min(100, int(cmd["quality"])))

                elif action == "update_data_collection":
                    if "config" in cmd:
                        self.data_collection = cmd["config"]

                elif action == "get_frame":
                    frame = capture.read()
                    if frame is not None:
                        if zone_data:
                            for i, (zn, zs, zp, _) in enumerate(zone_data):
                                c = ZONE_COLORS[i % len(ZONE_COLORS)]
                                if zs == "danger":
                                    c = (0, 0, 255)
                                _draw_roi(frame, zp, color=c, label=zn)
                        elif roi_polygon is not None:
                            _draw_roi(frame, roi_polygon)
                        quality_params = [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality]
                        _, buf = cv2.imencode(".jpg", frame, quality_params)
                        self.response_queue.put(buf.tobytes())
                    else:
                        self.response_queue.put(None)

        except Empty:
            pass

        return roi_polygon, roi_bbox, zone_data
