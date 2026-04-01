# build_vdetect.py
import subprocess
import os
import sys

def main():
    # Move to project root (parent of 'scripts')
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    print(f"Working directory: {os.getcwd()}")
    print("Building V-Detect with PyInstaller...")
    # Clean old builds
    if os.path.exists("dist"):
        import shutil
        print("Cleaning old 'dist' folder...")
        shutil.rmtree("dist")
    
    # Detect PyInstaller location
    pyinstaller_cmd = "pyinstaller"
    # Check if we are in a venv or if one exists locally
    venv_pyinstaller = os.path.join(".venv", "Scripts", "pyinstaller.exe")
    if os.path.exists(venv_pyinstaller):
        pyinstaller_cmd = venv_pyinstaller
    
    # Run PyInstaller
    cmd = [pyinstaller_cmd, "--noconfirm", "vdetect.spec"]
    try:
        print(f"Executing: {' '.join(cmd)}")
        subprocess.check_call(cmd)
        print("\nPyInstaller build finished successfully!")
        print("Output is located in 'dist/VDetect/'")
    except Exception as e:
        print(f"\nError building with PyInstaller: {e}")
        return

    print("\nNext steps:")
    print("1. Ensure 'Inno Setup' is installed.")
    print("2. Open 'vdetect_installer.iss' in Inno Setup and compile it.")
    print("3. Your installer will be in the 'Output/' folder as 'VDetect_Setup.exe'")

if __name__ == "__main__":
    main()
