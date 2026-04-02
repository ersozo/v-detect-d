#!/bin/bash
# scripts/build_appimage.sh - Automates AppImage creation for Ubuntu

set -e

# 1. Project Root Check
if [ ! -f "vdetect.spec" ]; then
    echo "[!] Run this script from the project root: ./scripts/build_appimage.sh"
    exit 1
fi

PROJECT_ROOT=$(pwd)
DIST_DIR="$PROJECT_ROOT/dist/VDetect"
APPDIR="$PROJECT_ROOT/build/AppDir"
SCRIPTS_DIR="$PROJECT_ROOT/scripts"

# 2. Prerequisites Check
echo "[*] Checking system dependencies..."
REQUIRED_TOOLS=("python3" "pip" "wget" "convert")
for tool in "${REQUIRED_TOOLS[@]}"; do
    if ! command -v "$tool" &> /dev/null; then
        echo "[!] Error: '$tool' is not installed."
        if [ "$tool" == "convert" ]; then
             echo "    Try: sudo apt install -y imagemagick"
        elif [ "$tool" == "python3" ]; then
             echo "    Try: sudo apt install -y python3"
        fi
        exit 1
    fi
done

# 3. Virtual Environment & Requirements
if [ ! -d ".venv_linux" ]; then
    echo "[*] Creating virtual environment .venv_linux..."
    python3 -m venv .venv_linux
fi
source .venv_linux/bin/activate
echo "[*] Updating pip and installing requirements..."
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

# 4. Build with PyInstaller
echo "[*] Cleaning old builds..."
rm -rf build/ dist/
echo "[*] Running PyInstaller..."
pyinstaller --clean --noconfirm vdetect.spec

if [ ! -d "$DIST_DIR" ]; then
    echo "[!] PyInstaller build failed. Check logs."
    exit 1
fi

# 5. Prepare AppDir
echo "[*] Preparing AppDir structure..."
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Copy PyInstaller bundle to AppDir
cp -r "$DIST_DIR"/* "$APPDIR/usr/bin/"

# 6. Icons & Desktop File
echo "[*] Handling icon and desktop file..."
if [ -f "desktop/ui/assets/icon.ico" ]; then
    echo "    Converting .ico to .png..."
    convert "desktop/ui/assets/icon.ico[0]" "$PROJECT_ROOT/vdetect.png"
fi

if [ ! -f "vdetect.png" ]; then
    echo "[!] Warning: vdetect.png not found and conversion failed."
    echo "    Creating a dummy icon (this is not recommended for production)."
    convert -size 256x256 xc:blue "$PROJECT_ROOT/vdetect.png"
fi

# 7. Download LinuxDeploy
echo "[*] Setting up linuxdeploy..."
if [ ! -f "linuxdeploy-x86_64.AppImage" ]; then
    wget -q https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage
    chmod +x linuxdeploy-x86_64.AppImage
fi

# 8. Final Build
echo "[*] Running linuxdeploy to generate AppImage..."

# We set VERSION environment variable for linuxdeploy
export VERSION=$(grep "VERSION =" backend/version.py | cut -d '"' -f 2 | head -n 1)
if [ -z "$VERSION" ]; then VERSION="1.0.0"; fi

./linuxdeploy-x86_64.AppImage \
    --appdir "$APPDIR" \
    --desktop-file "$SCRIPTS_DIR/vdetect.desktop" \
    --icon-file "$PROJECT_ROOT/vdetect.png" \
    --output appimage

echo ""
echo "[OK] Build complete!"
ls -lh *.AppImage
