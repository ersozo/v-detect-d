import os
import sys
import platform

def setup_windows():
    import winshell
    from win32com.client import Dispatch

    startup_path = winshell.startup()
    path = os.path.join(startup_path, "V-Detect.lnk")
    
    # Path to the executable (if frozen) or the script (if dev)
    if getattr(sys, 'frozen', False):
        target = sys.executable
        cwd = os.path.dirname(sys.executable)
    else:
        target = sys.executable
        main_script = os.path.join(os.path.dirname(os.path.dirname(__file__)), "desktop", "main.py")
        # For dev mode, we need to pass the script path as argument
        arguments = f'"{main_script}" --fullscreen'
        icon = target # Use python icon
    
    if getattr(sys, 'frozen', False):
        arguments = "--fullscreen"
        icon = target
    
    shell = Dispatch('WScript.Shell')
    shortcut = shell.CreateShortCut(path)
    shortcut.Targetpath = target
    shortcut.Arguments = arguments
    shortcut.WorkingDirectory = cwd if getattr(sys, 'frozen', False) else os.path.dirname(main_script)
    shortcut.IconLocation = icon
    shortcut.save()
    print(f"Windows shortcut created at: {path}")

def setup_linux():
    # Path to the .desktop file
    desktop_file_src = os.path.join(os.path.dirname(__file__), "vdetect.desktop")
    autostart_dir = os.path.expanduser("~/.config/autostart")
    
    if not os.path.exists(autostart_dir):
        os.makedirs(autostart_dir)
        
    desktop_file_dst = os.path.join(autostart_dir, "vdetect.desktop")
    
    with open(desktop_file_src, "r") as f:
        content = f.read()
    
    # Ensure --fullscreen is in Exec
    if "--fullscreen" not in content:
        content = content.replace("Exec=VDetect", "Exec=VDetect --fullscreen")
    
    with open(desktop_file_dst, "w") as f:
        f.write(content)
        
    os.chmod(desktop_file_dst, 0o755)
    print(f"Linux autostart entry created at: {desktop_file_dst}")

if __name__ == "__main__":
    system = platform.system()
    try:
        if system == "Windows":
            print("Setting up Windows autostart...")
            # We need pywin32 and winshell for this helper script
            try:
                setup_windows()
            except ImportError:
                print("Error: 'pywin32' and 'winshell' are required to automate shortcut creation on Windows.")
                print("Manual Way: Press Win+R, type 'shell:startup', and create a shortcut to the EXE there with '--fullscreen' argument.")
        elif system == "Linux":
            print("Setting up Linux autostart...")
            setup_linux()
        else:
            print(f"Unsupported system: {system}")
    except Exception as e:
        print(f"An error occurred: {e}")
