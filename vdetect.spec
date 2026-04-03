# -*- mode: python ; coding: utf-8 -*-
import os
import sys
# More aggressive collection for OpenVINO frontends and plugins
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files, copy_metadata

datas, binaries, hiddenimports = collect_all("torch")

# ONNX for model export
datas_o, binaries_o, hiddenimports_o = collect_all("onnx")
datas_ort, binaries_ort, hiddenimports_ort = collect_all("onnxruntime")
datas += datas_o + datas_ort
binaries += binaries_o + binaries_ort
hiddenimports += hiddenimports_o + hiddenimports_ort

# Ultralytics needs many submodules and data
datas_u, binaries_u, hiddenimports_u = collect_all("ultralytics")
datas += datas_u
binaries += binaries_u
hiddenimports += hiddenimports_u + collect_submodules("ultralytics")

# OpenVINO is particularly tricky with plugins/frontends
datas_ov, binaries_ov, hiddenimports_ov = collect_all("openvino")
# copy_metadata is crucial for OpenVINO 2024 discovery
datas += datas_ov + copy_metadata("openvino")
binaries += binaries_ov
hiddenimports += hiddenimports_ov + [
    'openvino._pyopenvino',
    'openvino.inference_engine',
    'openvino.preprocess',
    'openvino.runtime',
]

# Ensure we get the frontend libraries which are often missed
try:
    import openvino
    ov_path = os.path.dirname(openvino.__file__)
    
    # Mirror the entire internal hierarchy of the openvino package
    for root, dirs, files in os.walk(ov_path):
        for file in files:
            if file.endswith('.so') or '.so.' in file:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(root, os.path.dirname(ov_path))
                binaries.append((full_path, rel_path))
            elif file == 'plugins.xml':
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(root, os.path.dirname(ov_path))
                datas.append((full_path, rel_path))
except ImportError:
    pass

block_cipher = None

# Base directories
project_root = os.getcwd()
backend_dir = os.path.join(project_root, 'backend')
desktop_dir = os.path.join(project_root, 'desktop')

a = Analysis(
    [os.path.join(desktop_dir, 'main.py')],
    pathex=[project_root, backend_dir, desktop_dir],
    binaries=binaries,
    datas=datas + [
        ('backend', 'backend'),
        ('data/models', 'data/models'),
    ],
    hiddenimports=hiddenimports + [
        'qasync',
        'PySide6.QtOpenGLWidgets',
        'PySide6.QtSvg',
        'cv2',
        'ultralytics',
        'openvino',
        'snap7',
        'pydantic',
        'backend.camera_process',
        'backend.detector',
        'backend.plc_manager',
        'backend.plc_client',
        'backend.process_manager',
        'backend.event_store',
        'backend.capture',
        'backend.config',
        'backend.models',
        'backend.translations',
        'backend.version',
        'unittest',
        'torch',
        'torch.fx',
        'torch.utils',
        'torch.utils._config_module',
    ],
    hookspath=[],
    # ... (rest stays the same)
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VDetect',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False, # Set to False for clean production build
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.abspath(os.path.join('desktop', 'ui', 'assets', 'icon.ico')) if os.path.exists(os.path.join('desktop', 'ui', 'assets', 'icon.ico')) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VDetect',
)
