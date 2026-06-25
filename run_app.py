import os
import sys
import time
import subprocess
import threading
import socket
import ctypes


# ===== PyInstaller 路径修正 =====
# 打包后 sys._MEIPASS 指向解压临时目录，需要加入 sys.path 才能正确 import
if hasattr(sys, '_MEIPASS'):
    _base = sys._MEIPASS
    if _base not in sys.path:
        sys.path.insert(0, _base)
    # 同时确保 EXE 所在目录也在 path 中（用于写 data 等持久化文件）
    _exe_dir = os.path.dirname(sys.executable)
    if _exe_dir not in sys.path:
        sys.path.insert(0, _exe_dir)
else:
    _base = os.path.dirname(os.path.abspath(__file__))

# 检查依赖包，若没有则自动静默安装，确保用户双击即用（打包环境下直接报错防止递归自环）
try:
    import webview
except ImportError as err:
    if hasattr(sys, '_MEIPASS'):
        raise RuntimeError(f"Fatal: Required package 'pywebview' is missing in packaged environment: {err}")
    else:
        print("[loader] Installing pywebview dependency...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pywebview"])
        import webview



# 全局窗口引用，避免作为 WindowAPI 属性从而被 pywebview 的反射器深度遍历导致递归溢出
window = None


class WindowAPI:
    def __init__(self):
        self.is_maximized = False

    def minimize(self):
        global window
        if window:
            window.minimize()

    def toggle_maximize(self):
        global window
        if window:
            if self.is_maximized:
                window.restore()
                self.is_maximized = False
            else:
                window.maximize()
                self.is_maximized = True

    def close(self):
        global window
        if window:
            window.destroy()

    def start_drag(self):
        global window
        if window and sys.platform == "win32":
            try:
                hwnd = int(window.native.Handle.ToInt64())
                ctypes.windll.user32.ReleaseCapture()
                ctypes.windll.user32.SendMessageW(hwnd, 0xA1, 2, 0)
            except Exception as e:
                print(f"[WindowAPI] start_drag error: {e}")




def is_port_in_use(port: int) -> bool:

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def start_backend():
    import uvicorn
    # 直接 import app 对象，让 PyInstaller 能正确追踪依赖
    from backend.main import app
    uvicorn.run(app, host="127.0.0.1", port=8084, log_level="warning")

def main():
    # 1. 确保后台 uvicorn 端口可用，若已被残留占用则尝试杀掉
    if is_port_in_use(8084):
        print("[loader] Port 8084 is in use, cleaning up zombie processes...")
        if sys.platform == "win32":
            try:
                output = subprocess.check_output("netstat -ano | findstr :8084", shell=True).decode()
                pids = set()
                for line in output.strip().split("\n"):
                    parts = line.strip().split()
                    if len(parts) >= 5 and ":8084" in parts[1]:
                        pids.add(parts[-1])
                for pid in pids:
                    subprocess.call(f"taskkill /F /PID {pid}", shell=True)
                time.sleep(0.5)
            except Exception as e:
                print(f"[loader] Failed to kill zombie uvicorn: {e}")

    # 2. 启动后台 FastAPI 服务线程
    backend_thread = threading.Thread(target=start_backend, daemon=True)
    backend_thread.start()

    # 3. 等待后端端口成功响应（最多 6 秒）
    for _ in range(60):
        if is_port_in_use(8084):
            break
        time.sleep(0.1)

    # 4. 拉起独立 Webview 客户端窗口（无浏览器地址栏 / 标签页）
    print("[loader] Launching telemetry dashboard container...")
    global window
    
    # 动态获取 logo.ico 图标的绝对路径以修复打包后图标丢失问题
    if hasattr(sys, '_MEIPASS'):
        logo_path = os.path.join(sys._MEIPASS, "logo.ico")
    else:
        logo_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo.ico")
        
    api = WindowAPI()
    window = webview.create_window(
        title="AI中转站监控大屏 [ TELEMETRY DESKTOP ]",
        url="http://127.0.0.1:8084",
        width=1520,
        height=920,
        min_size=(1024, 700),
        text_select=True,
        background_color="#050912",
        frameless=True,
        on_top=False,
        js_api=api
    )


    def init_window():
        # Center the window on the primary monitor
        try:
            user32 = ctypes.windll.user32
            screen_w = user32.GetSystemMetrics(0)
            screen_h = user32.GetSystemMetrics(1)
            x = (screen_w - 1520) // 2
            y = (screen_h - 920) // 2
            window.move(x, y)
        except Exception:
            pass

    webview.start(init_window)

    # 5. Webview 关闭后主进程退出，daemon 线程随之销毁，端口自动释放
    print("[loader] Telemetry client closed. Exiting.")
    sys.exit(0)

if __name__ == "__main__":
    main()
