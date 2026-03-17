"""RTSP frame capture with automatic reconnection.

Decoupled from detection — this module only reads frames.
"""

import logging
import os
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Force TCP for RTSP stability (avoids UDP packet loss & SETUP 500 errors)
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"


class RTSPCapture:
    """Thin wrapper around cv2.VideoCapture with reconnect logic."""

    RECONNECT_DELAY = 2.0

    def __init__(self, url: str):
        self.url = url
        self._cap: cv2.VideoCapture | None = None
        self._connect()

    def _connect(self) -> None:
        if self._cap is not None:
            self._cap.release()

        self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if self._cap.isOpened():
            logger.info("Connected: %s", self.url)
        else:
            logger.warning("Failed to connect: %s", self.url)

    def read(self) -> np.ndarray | None:
        """Read a single frame, draining the internal buffer first."""
        if self._cap is None or not self._cap.isOpened():
            return None

        # Drain stale buffered frame
        self._cap.grab()

        ret, frame = self._cap.read()
        if not ret or frame is None:
            return None
        return frame

    def reconnect(self) -> None:
        logger.info("Reconnecting to %s ...", self.url)
        time.sleep(self.RECONNECT_DELAY)
        self._connect()

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def get_fps(self) -> float:
        if self._cap:
            return self._cap.get(cv2.CAP_PROP_FPS)
        return 0.0

    @staticmethod
    def test_connection(url: str, timeout: float = 5.0) -> dict:
        """Try opening the RTSP URL and return status + stream info."""
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        deadline = time.time() + timeout
        opened = cap.isOpened()
        frame_ok = False
        width, height, fps = 0, 0, 0.0

        if opened:
            while time.time() < deadline:
                ret, frame = cap.read()
                if ret and frame is not None:
                    height, width = frame.shape[:2]
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_ok = True
                    break

        cap.release()
        return {
            "reachable": opened and frame_ok,
            "opened": opened,
            "frame_received": frame_ok,
            "width": width,
            "height": height,
            "fps": round(fps, 1),
        }
