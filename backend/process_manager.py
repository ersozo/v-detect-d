"""Process lifecycle manager for camera subprocesses.

Creates / stops / monitors one CameraProcess per camera.
Exposes the IPC queues so the main process can read frames and events.
"""

import asyncio
import logging
import os
import multiprocessing
import re
from queue import Empty

from camera_process import CameraProcess

logger = logging.getLogger(__name__)


class ProcessManager:
    def __init__(self, img_path: str):
        self.img_path = img_path
        self.processes: dict[str, CameraProcess] = {}
        self.frame_queues: dict[str, multiprocessing.Queue] = {}
        self.event_queues: dict[str, multiprocessing.Queue] = {}
        self.control_queues: dict[str, multiprocessing.Queue] = {}
        self.response_queues: dict[str, multiprocessing.Queue] = {}
        self.stop_events: dict[str, multiprocessing.Event] = {}
        self._camera_configs: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_camera(self, camera_config: dict) -> None:
        camera_id = camera_config["id"]

        if camera_id in self.processes:
            self.stop_camera(camera_id)

        frame_q = multiprocessing.Queue(maxsize=1)
        event_q = multiprocessing.Queue(maxsize=1)
        control_q: multiprocessing.Queue = multiprocessing.Queue()
        response_q = multiprocessing.Queue(maxsize=1)
        stop_e = multiprocessing.Event()

        # Sanitized name for directory
        safe_name = re.sub(r'[^\w\-_\. ]', '_', camera_config.get("name", "Unnamed"))
        
        old_folder_name = f"{camera_id}_{safe_name}"
        old_cam_captures = os.path.join(self.img_path, old_folder_name)
        new_cam_captures = os.path.join(self.img_path, safe_name)

        # Migration logic
        if os.path.exists(old_cam_captures) and not os.path.exists(new_cam_captures):
            try:
                os.rename(old_cam_captures, new_cam_captures)
                logger.info("Folder migrated: %s -> %s", old_folder_name, safe_name)
            except Exception as e:
                logger.warning("Could not migrate folder: %s", e)
        elif not os.path.exists(new_cam_captures):
            # Also check old-old fallback if any
            old_fallback = os.path.join(self.img_path, camera_id)
            if os.path.exists(old_fallback):
                try: os.rename(old_fallback, new_cam_captures)
                except: pass

        cam_captures = new_cam_captures
        os.makedirs(cam_captures, exist_ok=True)

        proc = CameraProcess(
            camera_id=camera_id,
            rtsp_url=camera_config["url"],
            model_size=camera_config.get("model_size", "n"),
            confidence=camera_config.get("confidence", 0.5),
            frame_skip=camera_config.get("frame_skip", 0),
            roi=camera_config.get("roi"),
            zones=camera_config.get("zones"),
            blur_faces=camera_config.get("blur_faces", False),
            img_path=cam_captures,
            frame_queue=frame_q,
            event_queue=event_q,
            control_queue=control_q,
            response_queue=response_q,
            stop_event=stop_e,
            detect_classes=camera_config.get("detect_classes", [0]),
            custom_model=camera_config.get("custom_model"),
            crop_enabled=camera_config.get("crop_enabled", False),
            crop_x=camera_config.get("crop_x", 0),
            crop_y=camera_config.get("crop_y", 0),
            crop_w=camera_config.get("crop_w", 0),
            crop_h=camera_config.get("crop_h", 0),
        )

        # Initialize data collection state from config
        if "data_collection" in camera_config:
            dc_cfg = camera_config["data_collection"]
            if hasattr(dc_cfg, 'dict'): dc_cfg = dc_cfg.dict()
            proc.data_collection = dc_cfg

        proc.start()

        self.processes[camera_id] = proc
        self.frame_queues[camera_id] = frame_q
        self.event_queues[camera_id] = event_q
        self.control_queues[camera_id] = control_q
        self.response_queues[camera_id] = response_q
        self.stop_events[camera_id] = stop_e
        self._camera_configs[camera_id] = camera_config

        logger.info(
            "Camera process started: %s (PID %s)", camera_id, proc.pid
        )

    def stop_camera(self, camera_id: str) -> None:
        if camera_id not in self.processes:
            return

        self.stop_events[camera_id].set()
        proc = self.processes[camera_id]
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2)

        for mapping in (
            self.processes,
            self.frame_queues,
            self.event_queues,
            self.control_queues,
            self.response_queues,
            self.stop_events,
            self._camera_configs,
        ):
            mapping.pop(camera_id, None)

        logger.info("Camera process stopped: %s", camera_id)

    def get_capture_dir(self, camera_id: str) -> str:
        """Returns the specific directory path for a camera, considering ID_NAME naming."""
        config = self._camera_configs.get(camera_id)
        if not config:
            # Fallback for just ID
            return os.path.join(self.img_path, camera_id)

        safe_name = re.sub(r'[^\w\-_\. ]', '_', config.get("name", "Unnamed"))
        return os.path.join(self.img_path, safe_name)

    def stop_all(self) -> None:
        for camera_id in list(self.processes):
            self.stop_camera(camera_id)

    # ------------------------------------------------------------------
    # Commands → camera process
    # ------------------------------------------------------------------

    def send_command(self, camera_id: str, command: dict) -> None:
        q = self.control_queues.get(camera_id)
        if q is not None:
            q.put(command)

    async def get_response(
        self, camera_id: str, timeout: float = 5.0
    ) -> bytes | None:
        q = self.response_queues.get(camera_id)
        if q is None:
            return None
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: q.get(timeout=timeout)
            )
        except Empty:
            return None

    # ------------------------------------------------------------------
    # Health monitoring (self-healing)
    # ------------------------------------------------------------------

    async def health_check_loop(
        self, on_restart=None
    ) -> None:
        """Restart dead camera processes.

        *on_restart(camera_id)* is an optional async callback fired after
        a process is restarted so the caller can re-wire frame pumps etc.
        """
        while True:
            for camera_id in list(self.processes):
                proc = self.processes.get(camera_id)
                if proc is None:
                    continue
                if not proc.is_alive():
                    config = self._camera_configs.get(camera_id)
                    if config is None:
                        continue
                    logger.warning(
                        "Camera %s died (exit=%s), restarting …",
                        camera_id,
                        proc.exitcode,
                    )
                    self.stop_camera(camera_id)
                    self.start_camera(config)
                    if on_restart is not None:
                        await on_restart(camera_id)
            await asyncio.sleep(10)
