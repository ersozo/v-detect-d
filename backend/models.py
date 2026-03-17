"""Pydantic models for the Safety Detection System."""

import urllib.parse
from typing import Optional

from pydantic import BaseModel


class DataCollectionConfig(BaseModel):
    """Configuration for collecting raw frames or video for AI training."""
    enabled: bool = False
    mode: str = "frames"  # 'frames' or 'video'
    interval: int = 5     # Every Nth frame


class CameraConfig(BaseModel):
    id: str
    name: str
    ip: str
    username: str = "admin"
    password: str = ""
    port: int = 554
    stream_path: str = ""
    roi: Optional[list] = None
    zones: Optional[list[dict]] = None
    model_size: str = "n"
    detect_classes: list[int] = [0]
    custom_model: Optional[str] = None
    frame_skip: int = 0
    confidence: float = 0.5
    blur_faces: bool = False
    enabled: bool = True
    data_collection: Optional[DataCollectionConfig] = None
    plc_outputs: Optional[list["CameraPLCOutput"]] = None

    def get_rtsp_url(self) -> str:
        user = urllib.parse.quote(self.username) if self.username else ""
        pwd = urllib.parse.quote(self.password) if self.password else ""

        if user and pwd:
            auth = f"{user}:{pwd}@"
        elif user:
            auth = f"{user}@"
        else:
            auth = ""

        path = (
            self.stream_path
            if self.stream_path.startswith("/")
            else f"/{self.stream_path}" if self.stream_path else ""
        )
        return f"rtsp://{auth}{self.ip}:{self.port}{path}"


class ROIPoint(BaseModel):
    x: int
    y: int


class ROIZone(BaseModel):
    """Named ROI zone with optional severity level."""
    name: str
    points: list[ROIPoint]
    severity: str = "warning"


class ROIUpdate(BaseModel):
    camera_id: str
    points: list[ROIPoint]


class ZonesUpdate(BaseModel):
    camera_id: str
    zones: list[ROIZone]


class PLCCameraMapping(BaseModel):
    """Per-camera PLC address: maps a camera to a specific DB bit."""
    db_number: Optional[int] = None
    byte_idx: Optional[int] = None
    bit_idx: Optional[int] = None


class CameraPLCOutput(BaseModel):
    """Links a camera to a specific PLC and its bit address."""
    plc_id: str
    db_number: Optional[int] = None
    byte_idx: Optional[int] = None
    bit_idx: Optional[int] = None


class PLCInstance(BaseModel):
    """Full configuration for a single Siemens S7 PLC."""
    id: str
    name: str
    enabled: bool = False
    ip: str = "192.168.0.50"
    rack: int = 0
    slot: int = 1
    db_number: int = 38
    lifebit_byte: int = 4
    lifebit_bit: int = 0
    person_byte: int = 6
    person_bit: int = 0
    # Map of camera_id -> mapping for this specific PLC
    camera_mappings: dict[str, PLCCameraMapping] = {}


class PLCConfig(BaseModel):
    """Collection of PLC instances and global settings."""
    instances: dict[str, PLCInstance] = {}
    default_plc_id: Optional[str] = None
