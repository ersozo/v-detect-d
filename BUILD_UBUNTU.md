# Building V-Detect AppImage on Ubuntu

Follow these steps to create a portable AppImage of V-Detect from your Ubuntu system.

## 1. System Preparation
Open your terminal and install the necessary system dependencies:
```bash
sudo apt update
sudo apt install -y python3-venv python3-pip libgl1 libglib2.0-0 file fuse wget imagemagick
```

## 2. Using the Build Script
I have provided an automation script in `scripts/build_appimage.sh`. 

### Granting Permissions
Make the script executable:
```bash
chmod +x scripts/build_appimage.sh
```

### Running the Build
Run the script from the **project root**:
```bash
./scripts/build_appimage.sh
```

### What the Script Does:
1.  **Sets up a Virtual Environment**: Creates `.venv_linux` and installs requirements.
2.  **Builds with PyInstaller**: Generates a Linux executable bundle in `dist/VDetect`.
3.  **Packages as AppImage**:
    - Downloads `linuxdeploy`.
    - Converts `desktop/ui/assets/icon.ico` to a PNG icon.
    - Packages everything into a single `.AppImage` file.

## 3. Deployment
Once the process is finished, you will find a file like `V-Detect-1.0.0-x86_64.AppImage` in the root directory.

### To Run:
```bash
chmod +x V-Detect-1.0.0-x86_64.AppImage
./V-Detect-1.0.0-x86_64.AppImage
```

---
**Note:** If you are building on a very new version of Ubuntu (e.g., 24.04), the resulting AppImage may not run on older versions (e.g., 20.04) due to higher GLIBC versions. For maximum compatibility, build on the oldest Ubuntu version you intend to support (e.g., Ubuntu 20.04 or 22.04 LTS).
