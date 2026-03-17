import sys
import os
import asyncio
import qasync
from PySide6.QtWidgets import QApplication

# Ensure python finds 'desktop' and 'backend'
base_dir = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, base_dir)
sys.path.insert(1, os.path.join(base_dir, "backend"))

# Initialize core states before UI is imported
from desktop.core.app_state import AppState

async def main_loop():
    try:
        AppState.init()

        # Start backend components for enabled cameras
        for cam_id, cam_data in AppState.cameras.items():
            if cam_data.get("enabled", True):
                AppState.process_mgr.start_camera(cam_data)

        AppState.plc_mgr.set_event_queues(AppState.process_mgr.event_queues)
        
        plc_task = asyncio.create_task(AppState.plc_mgr.run())
    except Exception as e:
        print(f"CRITICAL: Failed to initialize backend components: {e}")
        import traceback
        traceback.print_exc()
        return

    async def on_restart(cam_id):
        # Could reconnect the UI queue here later
        pass

    health_task = asyncio.create_task(
        AppState.process_mgr.health_check_loop(on_restart=on_restart)
    )

    from desktop.ui.main_window import MainWindow
    window = MainWindow()
    window.show()

    # Block the coroutine until window closes
    try:
        while window.isVisible():
            await asyncio.sleep(0.1)
    finally:
        # Graceful shutdown
        AppState.plc_mgr.stop()
        plc_task.cancel()
        health_task.cancel()
        AppState.process_mgr.stop_all()
        AppState.event_store.close()

if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)
    
    # Run the qasync event loop integration
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    
    with loop:
        loop.run_until_complete(main_loop())
