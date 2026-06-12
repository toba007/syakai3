import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import threading

ser = None

def list_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

def connect():
    global ser
    port = port_combo.get()

    if not port:
        messagebox.showerror("Error", "COMポートを選んでください")
        return

    try:
        ser = serial.Serial(port, 115200, timeout=1)
        status_label.config(text=f"接続中: {port}")
        read_thread = threading.Thread(target=read_serial, daemon=True)
        read_thread.start()
    except Exception as e:
        messagebox.showerror("接続エラー", str(e))

def send_motion(cmd):
    global ser
    if ser is None or not ser.is_open:
        messagebox.showwarning("未接続", "先にESP32へ接続してください")
        return

    ser.write((cmd + "\n").encode("utf-8"))
    log.insert(tk.END, f"> {cmd}\n")
    log.see(tk.END)

def read_serial():
    global ser
    while ser and ser.is_open:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if line:
                log.insert(tk.END, f"ESP32: {line}\n")
                log.see(tk.END)
        except:
            break

def refresh_ports():
    port_combo["values"] = list_ports()

def close():
    global ser
    if ser and ser.is_open:
        ser.close()
    root.destroy()

root = tk.Tk()
root.title("6軸首ロボット 表情モーション操作")
root.geometry("420x420")

frame = ttk.Frame(root, padding=10)
frame.pack(fill="both", expand=True)

ttk.Label(frame, text="COMポート").pack(anchor="w")

port_combo = ttk.Combobox(frame, values=list_ports(), state="readonly")
port_combo.pack(fill="x", pady=5)

ttk.Button(frame, text="ポート更新", command=refresh_ports).pack(fill="x")
ttk.Button(frame, text="接続", command=connect).pack(fill="x", pady=5)

status_label = ttk.Label(frame, text="未接続")
status_label.pack(anchor="w", pady=5)

buttons = [
    ("Happy / うれしい", "happy"),
    ("Sad / かなしい", "sad"),
    ("Curious / 興味津々", "curious"),
    ("Agree / うなずき", "agree"),
    ("Sleepy / ねむい", "sleepy"),
    ("Home / ホーム", "home"),
]

for text, cmd in buttons:
    ttk.Button(frame, text=text, command=lambda c=cmd: send_motion(c)).pack(fill="x", pady=3)

ttk.Label(frame, text="ログ").pack(anchor="w", pady=(10, 0))

log = tk.Text(frame, height=8)
log.pack(fill="both", expand=True)

root.protocol("WM_DELETE_WINDOW", close)
root.mainloop()