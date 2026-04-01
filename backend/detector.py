"""YOLO object detector.

This module ONLY runs inference.  It has no knowledge of streaming,
PLC, image saving, or UI drawing.  Input: numpy frame + ROI config.
Output: list of detection dicts.
"""

import logging
import os
from typing import Optional

import cv2
import numpy as np
from ultralytics import YOLO
from config import MODELS_DIR, BUNDLED_MODELS_DIR

logger = logging.getLogger(__name__)


class Detector:
    """Stateless-ish YOLO26 detector — call .detect() per frame."""

    def __init__(self, model_path: str = "yolo26n.pt", confidence: float = 0.5):
        self.confidence = max(0.1, min(1.0, confidence))
        self._model: YOLO | None = None
        self._load_model(model_path)

    # ------------------------------------------------------------------
    # Model loading (OpenVINO → PyTorch fallback)
    # ------------------------------------------------------------------

    def _load_model(self, model_input: str) -> None:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"

        if model_input in ["n", "s", "m", "l", "x"]:
            model_filename = f"yolo26{model_input}.pt"
        else:
            model_filename = model_input

        # 1. Resolve Path: Check if it's absolute, or file in MODELS_DIR, or bundled
        if os.path.isabs(model_filename):
            model_pt = model_filename
        else:
            # Check for user-uploaded models first
            user_path = os.path.join(MODELS_DIR, model_filename)
            if os.path.exists(user_path):
                model_pt = user_path
            # Fallback to bundled models
            elif BUNDLED_MODELS_DIR and os.path.exists(os.path.join(BUNDLED_MODELS_DIR, model_filename)):
                model_pt = os.path.join(BUNDLED_MODELS_DIR, model_filename)
            else:
                # Default to user path (may not exist yet, will trigger download/fail)
                model_pt = user_path

        model_base = os.path.splitext(model_pt)[0]
        model_engine = f"{model_base}.engine"
        model_ov = f"{model_base}_openvino_model"

        # 1. Try TensorRT (Engine) if CUDA is available
        if device == "cuda":
            try:
                if not os.path.exists(model_engine):
                    logger.info("Converting %s → TensorRT (.engine) …", model_pt)
                    # Use a temporary YOLO object to export
                    YOLO(model_pt).export(format="engine", half=True, device=0)

                self._model = YOLO(model_engine, task="detect")
                logger.info("Loaded TensorRT engine: %s (Device: %s)", model_engine, device)
                return
            except Exception as e:
                logger.warning("TensorRT failed (%s), falling back...", e)

        # 2. Try OpenVINO (CPU optimization)
        try:
            if not os.path.exists(model_ov):
                # We only skip export in production if the model is in the read-only bundled directory.
                # If a user manually added a .pt to the writable MODELS_DIR, we SHOULD allow export for performance.
                is_bundled = BUNDLED_MODELS_DIR and model_pt.startswith(BUNDLED_MODELS_DIR)
                
                if getattr(sys, 'frozen', False) and is_bundled:
                    logger.warning("OpenVINO folder not found for bundled model and cannot export in production.")
                    raise FileNotFoundError(f"Missing bundled OpenVINO model: {model_ov}")
                
                logger.info("Converting %s → OpenVINO …", model_pt)
                YOLO(model_pt).export(format="openvino", half=True)
            
            self._model = YOLO(model_ov, task="detect")
            logger.info("Loaded OpenVINO model: %s", model_ov)
        except Exception as e:
            logger.warning("OpenVINO failed (%s), falling back to PyTorch", e)
            try:
                # 3. Final fallback to PyTorch (.pt)
                if not os.path.exists(model_pt):
                    logger.error("FATAL: AI Model file not found at %s", model_pt)
                    return
                
                self._model = YOLO(model_pt)
                logger.info("Loaded PyTorch model: %s (Device: %s)", model_pt, device)
            except Exception as e2:
                logger.error("CRITICAL error loading model %s: %s", model_pt, e2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(
        self,
        frame: np.ndarray,
        roi_polygon: Optional[np.ndarray] = None,
        roi_bbox: Optional[dict] = None,
        detect_classes: list[int] = [0],
    ) -> list[dict]:
        """Run detection on *frame*.

        Returns a list of dicts, each with keys:
            x1, y1, x2, y2, confidence, in_roi, class_id
        """
        if self._model is None:
            return []

        detection_frame = frame
        offset_x, offset_y = 0, 0

        if roi_bbox is not None:
            h, w = frame.shape[:2]
            pad = 10
            x1 = max(0, int(roi_bbox["x"] - pad))
            y1 = max(0, int(roi_bbox["y"] - pad))
            x2 = min(w, int(roi_bbox["x2"] + pad))
            y2 = min(h, int(roi_bbox["y2"] + pad))
            detection_frame = frame[y1:y2, x1:x2]
            offset_x, offset_y = x1, y1

        results = self._model(
            detection_frame, conf=self.confidence, verbose=False
        )

        detections: list[dict] = []
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                cls_id = int(box.cls[0])
                if cls_id not in detect_classes:
                    continue

                cx1, cy1, cx2, cy2 = (
                    box.xyxy[0].cpu().numpy().astype(int)
                )
                conf = float(box.conf[0])
                bx1 = int(cx1) + offset_x
                by1 = int(cy1) + offset_y
                bx2 = int(cx2) + offset_x
                by2 = int(cy2) + offset_y

                center_x = (bx1 + bx2) // 2
                center_y = (by1 + by2) // 2

                in_roi = True
                if roi_polygon is not None:
                    in_roi = (
                        cv2.pointPolygonTest(
                            roi_polygon,
                            (float(center_x), float(center_y)),
                            False,
                        )
                        >= 0
                    )

                detections.append(
                    {
                        "x1": bx1,
                        "y1": by1,
                        "x2": bx2,
                        "y2": by2,
                        "confidence": conf,
                        "in_roi": in_roi,
                        "class_id": cls_id,
                    }
                )

        return detections

    def set_confidence(self, confidence: float) -> None:
        self.confidence = max(0.1, min(1.0, confidence))

    def get_names(self) -> dict[int, str]:
        """Return class names map from the underlying YOLO model."""
        if self._model is not None:
            return self._model.names
        return {0: "Person"}
