"""Event-driven PLC manager with camera-state aggregation.

Reads detection events from *all* camera event queues, aggregates
them (person detected in ANY camera → True), and drives the PLC at
a fixed update rate (~10 Hz).

This decouples PLC writes from the individual camera loops, matching
arch.txt principle #4:  "PLC event-driven & aggregate".
"""

import asyncio
import logging
import time
from queue import Empty
from typing import TYPE_CHECKING

from plc_client import SNAP7_AVAILABLE, LifeBit, connect_plc, update_plc

if TYPE_CHECKING:
    from event_store import EventStore

logger = logging.getLogger(__name__)


class PLCManager:
    UPDATE_HZ = 10  # PLC update frequency

    def __init__(self):
        self._running = False
        self._plcs: dict[str, any] = {}  # plc_id -> snap7 client
        self._lifebits: dict[str, LifeBit] = {}  # plc_id -> LifeBit
        self._config: dict = {"instances": {}, "default_plc_id": None}
        self._event_queues: dict = {}  # camera_id → mp.Queue
        self._camera_states: dict[str, bool] = {}  # camera_id → person_detected
        self._camera_labels: dict[str, str] = {}  # camera_id → last_label
        self._cameras: dict[str, dict] = {}  # camera_id → full config
        self._event_store: "EventStore | None" = None
        self._alert_callback = None
        self._connection_statuses: dict[str, bool] = {} # plc_id -> connected
        self._last_connect_attempt: dict[str, float] = {} # To avoid rapid retries

    def set_config(self, config: dict) -> None:
        self._config = config
        # Disconnect any PLCs that are no longer in the config or need a reset
        current_ids = set(config.get("instances", {}).keys())
        for plc_id in list(self._plcs.keys()):
            if plc_id not in current_ids:
                client = self._plcs.pop(plc_id)
                self._lifebits.pop(plc_id, None)
                # Disconnect in background to avoid blocking the API thread
                import threading
                def _bg_disconnect(c):
                    try:
                        c.disconnect()
                    except:
                        pass
                threading.Thread(target=_bg_disconnect, args=(client,), daemon=True).start()

    def set_event_store(self, store: "EventStore") -> None:
        self._event_store = store

    def set_cameras(self, cameras: dict) -> None:
        """Stores the full camera configs to allow many-to-many PLC routing."""
        self._cameras = cameras

    def set_alert_callback(self, callback) -> None:
        """Set async callback(event_dict) called on every detection state change."""
        self._alert_callback = callback

    def set_event_queues(self, queues: dict) -> None:
        self._event_queues = queues
        # Preserve states for cameras that are still active
        self._camera_states = {
            k: v
            for k, v in self._camera_states.items()
            if k in queues
        }
        # Initialize missing cameras to False (Safe) explicitly to avoid None-flicker
        for k in queues:
            if k not in self._camera_states:
                self._camera_states[k] = False

    def get_statuses(self) -> dict[str, bool]:
        """Returns the current connection status for all known PLCs."""
        return dict(self._connection_statuses)

    async def run(self) -> None:
        """Long-running background task — call as ``asyncio.create_task``."""
        from version import VERSION
        self._running = True
        interval = 1.0 / self.UPDATE_HZ
        logger.info(f"Multi-PLC Manager started (v{VERSION}) (%d Hz)", self.UPDATE_HZ)

        # To prevent flickering alerts, we track "When did we last see a detection?"
        OFF_DELAY_SECONDS = 0.8
        last_seen_detection: dict[str, float] = {}
        alert_sent_state: dict[str, bool] = {}

        while self._running:
            # --- 1. Drain events and update raw states ---
            for camera_id, q in list(self._event_queues.items()):
                try:
                    event = q.get_nowait()
                    new_raw_state = bool(event.get("is_detected", False))

                    if new_raw_state:
                        last_seen_detection[camera_id] = time.time()

                    self._camera_states[camera_id] = new_raw_state
                    if new_raw_state and event.get("label"):
                        self._camera_labels[camera_id] = event.get("label")

                    if self._event_store:
                        loop = asyncio.get_running_loop()
                        await loop.run_in_executor(
                            None,
                            lambda: self._event_store.log(
                                camera_id=camera_id,
                                is_detected=new_raw_state,
                                obj_count=event.get("count", 0),
                                timestamp=event.get("timestamp"),
                            )
                        )
                except Empty:
                    pass

            # --- 2. Hysteresis logic for alerts ---
            now = time.time()
            for camera_id in list(self._event_queues.keys()):
                is_currently_detected = self._camera_states.get(camera_id, False)
                ts_last_seen = last_seen_detection.get(camera_id, 0)
                smoothed_state = is_currently_detected or (now - ts_last_seen < OFF_DELAY_SECONDS)

                prev_alert_state = alert_sent_state.get(camera_id)
                if smoothed_state != prev_alert_state:
                    alert_sent_state[camera_id] = smoothed_state
                    is_cold_start_false = (prev_alert_state is None and not smoothed_state)

                    if self._alert_callback and not is_cold_start_false:
                        try:
                            self._alert_callback({
                                "camera_id": camera_id,
                                "is_detected": smoothed_state,
                                "timestamp": now,
                                "count": 1 if smoothed_state else 0,
                                "label": self._camera_labels.get(camera_id, "Nesne")
                            })
                        except Exception as e:
                            logger.error("Alert callback error: %s", e)

            # --- 3. Drive PLCs (Multi-instance) ---
            if SNAP7_AVAILABLE:
                instances = self._config.get("instances", {})
                loop = asyncio.get_running_loop()

                for plc_id, plc_cfg in instances.items():
                    if not plc_cfg.get("enabled"):
                        self._connection_statuses[plc_id] = False
                        continue

                    # Connect if needed, but don't block other PLCs
                    if plc_id not in self._plcs:
                        # Avoid hammering unreachable PLCs
                        last_attempt = self._last_connect_attempt.get(plc_id, 0)
                        if now - last_attempt < 30.0:  # Retry every 30s
                            continue

                        self._last_connect_attempt[plc_id] = now

                        # Background connection task to avoid blocking the main loop
                        async def _connect_task(pid, cfg):
                            try:
                                client = await loop.run_in_executor(
                                    None, lambda: connect_plc(cfg)
                                )
                                if client:
                                    self._plcs[pid] = client
                                    self._lifebits[pid] = LifeBit()
                                    self._connection_statuses[pid] = True
                                else:
                                    self._connection_statuses[pid] = False
                            except Exception as e:
                                logger.error("PLC %s connection failed: %s", pid, e)
                                self._connection_statuses[pid] = False

                        asyncio.create_task(_connect_task(plc_id, plc_cfg))
                        continue

                    # Write to PLC
                    plc_client = self._plcs.get(plc_id)
                    if plc_client:
                        try:
                            lifebit = self._lifebits[plc_id]

                            # --- Aggregation logic for this PLC (Many-to-Many) ---
                            # A camera impacts this PLC if:
                            # 1. It is explicitly mapped inside the PLC's config (Backward matching)
                            # 2. It has an output entry in ITS OWN CONFIG targeting this PLC

                            mapped_cam_ids = set()

                            # Camera-side outputs (Many-to-Many)
                            for cam_id, cam_cfg in self._cameras.items():
                                outputs = cam_cfg.get("plc_outputs") or []
                                if any(o.get("plc_id") == plc_id for o in outputs):
                                    mapped_cam_ids.add(cam_id)

                            # Aggregate person detection for ONLY these cameras
                            any_triggered_for_plc = any(
                                alert_sent_state.get(cid, False)
                                for cid in mapped_cam_ids
                            )

                            loop = asyncio.get_running_loop()
                            await loop.run_in_executor(
                                None,
                                lambda: update_plc(
                                    plc_client,
                                    plc_cfg,
                                    lifebit.toggle(),
                                    any_triggered_for_plc,
                                    alert_sent_state,
                                    cameras_cfg=self._cameras
                                )
                            )
                        except Exception as e:
                            logger.error("PLC %s write error: %s", plc_id, e)
                            self._connection_statuses[plc_id] = False
                            # Remove so it tries to reconnect next tick
                            try:
                                plc_client.disconnect()
                            except:
                                pass
                            self._plcs.pop(plc_id, None)

            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
        for plc_id, client in self._plcs.items():
            try:
                client.disconnect()
            except Exception:
                pass
        self._plcs.clear()
