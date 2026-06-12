import json
import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import messagebox, ttk

from preview_server import WebMotionPreview

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    serial = None
    list_ports = None


BAUDRATES = (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
DEFAULT_MOTIONS = tuple(f"motion{i}" for i in range(1, 13))
MOTIONS_FILE = Path(__file__).with_name("motions.json")
MOTION_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


class EspMotionClient:
    def __init__(self, on_line):
        self.on_line = on_line
        self.serial = None
        self.reader_thread = None
        self.stop_event = threading.Event()
        self.write_lock = threading.Lock()

    @property
    def connected(self):
        return self.serial is not None and self.serial.is_open

    def connect(self, port, baudrate):
        if serial is None:
            raise RuntimeError("pyserial is not installed. Run: py -m pip install -r requirements.txt")

        self.disconnect()
        self.stop_event.clear()
        self.serial = serial.Serial(port=port, baudrate=int(baudrate), timeout=0.2)
        self.reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.reader_thread.start()

    def disconnect(self):
        self.stop_event.set()
        if self.serial is not None:
            try:
                self.serial.close()
            finally:
                self.serial = None

    def send_line(self, line):
        if not self.connected:
            raise RuntimeError("ESP is not connected.")

        payload = (line.strip() + "\n").encode("utf-8")
        with self.write_lock:
            self.serial.write(payload)
            self.serial.flush()

    def _read_loop(self):
        buffer = bytearray()
        while not self.stop_event.is_set() and self.serial is not None:
            try:
                chunk = self.serial.read(128)
            except serial.SerialException as exc:
                self.on_line(f"ERROR serial read failed: {exc}")
                break

            if not chunk:
                continue

            buffer.extend(chunk)
            while b"\n" in buffer:
                raw_line, _, buffer = buffer.partition(b"\n")
                text = raw_line.decode("utf-8", errors="replace").strip()
                if text:
                    self.on_line(text)


class MotionControlApp(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("ESP Motion Controller")
        self.geometry("980x640")
        self.minsize(880, 560)

        self.incoming = queue.Queue()
        self.client = EspMotionClient(self.incoming.put)
        self.preview = WebMotionPreview()
        self.preview.start()

        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value="115200")
        self.mode_var = tk.StringVar(value="PLAY")
        self.status_var = tk.StringVar(value=f"Preview: {self.preview.url}")
        self.command_var = tk.StringVar()
        self.new_motion_var = tk.StringVar()
        self.motions = self._load_motions()

        self._build_ui()
        self._refresh_ports()
        self._poll_incoming()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        style = ttk.Style(self)
        style.configure("Large.TButton", font=("Segoe UI", 15, "bold"), padding=(18, 16))
        style.configure("Action.TButton", font=("Segoe UI", 16, "bold"), padding=(22, 18))
        style.configure("Large.TRadiobutton", font=("Segoe UI", 14), padding=(10, 8))
        style.configure("Header.TLabel", font=("Segoe UI", 13, "bold"))

        connection = ttk.Frame(self, padding=(14, 12, 14, 8))
        connection.grid(row=0, column=0, sticky="ew")
        connection.columnconfigure(1, weight=1)

        ttk.Label(connection, text="Port", style="Header.TLabel").grid(row=0, column=0, sticky="w")
        self.port_combo = ttk.Combobox(connection, textvariable=self.port_var, state="readonly", width=26)
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=(8, 14))

        ttk.Label(connection, text="Baud", style="Header.TLabel").grid(row=0, column=2, sticky="w")
        self.baud_combo = ttk.Combobox(
            connection,
            textvariable=self.baud_var,
            values=[str(value) for value in BAUDRATES],
            width=10,
        )
        self.baud_combo.grid(row=0, column=3, sticky="w", padx=(8, 14))

        ttk.Button(connection, text="Refresh", style="Large.TButton", command=self._refresh_ports).grid(
            row=0, column=4, padx=(0, 8)
        )
        self.connect_button = ttk.Button(
            connection,
            text="Connect",
            style="Large.TButton",
            command=self._toggle_connection,
        )
        self.connect_button.grid(row=0, column=5)

        mode_bar = ttk.Frame(self, padding=(14, 0, 14, 10))
        mode_bar.grid(row=1, column=0, sticky="ew")
        mode_bar.columnconfigure(3, weight=1)

        ttk.Label(mode_bar, text="Send Mode", style="Header.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Radiobutton(
            mode_bar,
            text="PLAY",
            value="PLAY",
            variable=self.mode_var,
            style="Large.TRadiobutton",
        ).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(
            mode_bar,
            text="QUEUE",
            value="QUEUE",
            variable=self.mode_var,
            style="Large.TRadiobutton",
        ).grid(row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Button(mode_bar, text="Open Web Preview", style="Large.TButton", command=self._open_preview).grid(
            row=0, column=4, sticky="e", padx=(8, 0)
        )

        main = ttk.Frame(self, padding=(14, 0, 14, 10))
        main.grid(row=2, column=0, sticky="nsew")
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        motion_area = ttk.Frame(main)
        motion_area.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        motion_area.columnconfigure(0, weight=1)
        motion_area.rowconfigure(0, weight=1)

        self.motion_canvas = tk.Canvas(motion_area, highlightthickness=0)
        self.motion_canvas.grid(row=0, column=0, sticky="nsew")
        motion_scroll = ttk.Scrollbar(motion_area, orient=tk.VERTICAL, command=self.motion_canvas.yview)
        motion_scroll.grid(row=0, column=1, sticky="ns")
        self.motion_canvas.configure(yscrollcommand=motion_scroll.set)
        self.motion_button_frame = ttk.Frame(self.motion_canvas)
        self.motion_window = self.motion_canvas.create_window((0, 0), window=self.motion_button_frame, anchor="nw")
        self.motion_button_frame.bind("<Configure>", self._sync_motion_scroll_region)
        self.motion_canvas.bind("<Configure>", self._sync_motion_canvas_width)
        self._render_motion_buttons()

        side = ttk.Frame(main)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)
        side.rowconfigure(5, weight=1)

        ttk.Button(side, text="STOP", style="Action.TButton", command=lambda: self._send_control("STOP")).grid(
            row=0, column=0, sticky="ew", pady=(0, 8)
        )
        ttk.Button(side, text="CLEAR QUEUE", style="Action.TButton", command=lambda: self._send_control("CLEAR")).grid(
            row=1, column=0, sticky="ew", pady=(0, 14)
        )

        add_box = ttk.LabelFrame(side, text="Add Motion", padding=(10, 8, 10, 10))
        add_box.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        add_box.columnconfigure(0, weight=1)
        ttk.Entry(add_box, textvariable=self.new_motion_var, font=("Segoe UI", 13)).grid(
            row=0, column=0, sticky="ew", padx=(0, 8), ipady=8
        )
        ttk.Button(add_box, text="Add", style="Large.TButton", command=self._add_motion).grid(row=0, column=1)
        ttk.Button(add_box, text="Remove", style="Large.TButton", command=self._remove_motion).grid(
            row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 8)
        )
        ttk.Button(add_box, text="Reset", style="Large.TButton", command=self._reset_motions).grid(
            row=1, column=1, sticky="ew", pady=(8, 0)
        )

        command_bar = ttk.Frame(side)
        command_bar.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        command_bar.columnconfigure(0, weight=1)
        ttk.Entry(command_bar, textvariable=self.command_var, font=("Segoe UI", 13)).grid(
            row=0, column=0, sticky="ew", padx=(0, 8), ipady=8
        )
        ttk.Button(command_bar, text="Send Raw", style="Large.TButton", command=self._send_custom_command).grid(
            row=0, column=1
        )

        ttk.Label(side, text="Log", style="Header.TLabel").grid(row=4, column=0, sticky="w", pady=(4, 4))
        log_frame = ttk.Frame(side)
        log_frame.grid(row=5, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=10, wrap="word", state="disabled", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        log_scroll.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=log_scroll.set)

        bottom = ttk.Frame(self, padding=(14, 0, 14, 12))
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.columnconfigure(0, weight=1)
        ttk.Label(bottom, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Button(bottom, text="Clear Log", command=self._clear_log).grid(row=0, column=1, sticky="e")

    def _load_motions(self):
        if not MOTIONS_FILE.exists():
            return list(DEFAULT_MOTIONS)

        try:
            data = json.loads(MOTIONS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return list(DEFAULT_MOTIONS)

        if not isinstance(data, list):
            return list(DEFAULT_MOTIONS)

        motions = []
        for item in data:
            if isinstance(item, str) and MOTION_NAME_RE.fullmatch(item) and item not in motions:
                motions.append(item)
        return motions or list(DEFAULT_MOTIONS)

    def _save_motions(self):
        MOTIONS_FILE.write_text(json.dumps(self.motions, indent=2), encoding="utf-8")

    def _render_motion_buttons(self):
        for child in self.motion_button_frame.winfo_children():
            child.destroy()

        for col in range(3):
            self.motion_button_frame.columnconfigure(col, weight=1, uniform="motion")

        for index, motion in enumerate(self.motions):
            row, col = divmod(index, 3)
            self.motion_button_frame.rowconfigure(row, weight=1, uniform="motion")
            ttk.Button(
                self.motion_button_frame,
                text=motion,
                style="Action.TButton",
                command=lambda value=motion: self._send_motion(value),
            ).grid(row=row, column=col, sticky="nsew", padx=6, pady=6, ipady=10)

    def _sync_motion_scroll_region(self, _event=None):
        self.motion_canvas.configure(scrollregion=self.motion_canvas.bbox("all"))

    def _sync_motion_canvas_width(self, event):
        self.motion_canvas.itemconfigure(self.motion_window, width=event.width)

    def _add_motion(self):
        motion = self.new_motion_var.get().strip()
        if not motion:
            messagebox.showinfo("Motion name required", "Enter a motion name first.")
            return
        if not MOTION_NAME_RE.fullmatch(motion):
            messagebox.showwarning(
                "Invalid motion name",
                "Use a C-style function name: letters, numbers, and underscores. Start with a letter.",
            )
            return
        if motion in self.motions:
            messagebox.showinfo("Already exists", f"{motion} is already in the button list.")
            return

        self.motions.append(motion)
        self._save_motions()
        self._render_motion_buttons()
        self.new_motion_var.set("")
        self._log(f"Added motion button: {motion}")

    def _remove_motion(self):
        motion = self.new_motion_var.get().strip()
        if not motion:
            messagebox.showinfo("Motion name required", "Enter the motion name to remove.")
            return
        if motion not in self.motions:
            messagebox.showinfo("Not found", f"{motion} is not in the button list.")
            return

        self.motions.remove(motion)
        self._save_motions()
        self._render_motion_buttons()
        self.new_motion_var.set("")
        self._log(f"Removed motion button: {motion}")

    def _reset_motions(self):
        self.motions = list(DEFAULT_MOTIONS)
        self._save_motions()
        self._render_motion_buttons()
        self.new_motion_var.set("")
        self._log("Motion buttons reset")

    def _refresh_ports(self):
        if list_ports is None:
            self.port_combo.configure(values=[])
            self._log("pyserial is not installed. Run: py -m pip install -r requirements.txt")
            return

        ports = [port.device for port in list_ports.comports()]
        self.port_combo.configure(values=ports)
        if ports and self.port_var.get() not in ports:
            self.port_var.set(ports[0])
        elif not ports:
            self.port_var.set("")
        self._log(f"Ports refreshed: {', '.join(ports) if ports else 'none'}")

    def _toggle_connection(self):
        if self.client.connected:
            self.client.disconnect()
            self.connect_button.configure(text="Connect")
            self.status_var.set(f"Disconnected. Preview: {self.preview.url}")
            self._log("Disconnected")
            return

        port = self.port_var.get().strip()
        if not port:
            messagebox.showwarning("Port required", "Select a serial port first.")
            return

        try:
            self.client.connect(port, self.baud_var.get())
        except Exception as exc:
            messagebox.showerror("Connection failed", str(exc))
            self._log(f"ERROR connect failed: {exc}")
            return

        self.connect_button.configure(text="Disconnect")
        self.status_var.set(f"Connected to {port}. Preview: {self.preview.url}")
        self._log(f"Connected to {port}")

    def _send_motion(self, motion):
        command = f"{self.mode_var.get()} {motion}"
        self.preview.set_motion(motion, self.mode_var.get())
        self._send_command(command, allow_offline=True)

    def _send_control(self, command):
        if command == "STOP":
            self.preview.stop()
        elif command == "CLEAR":
            self.preview.clear()
        self._send_command(command, allow_offline=True)

    def _send_custom_command(self):
        command = self.command_var.get().strip()
        if command:
            self._send_command(command, allow_offline=True)
            self.command_var.set("")

    def _send_command(self, command, allow_offline=False):
        if allow_offline and not self.client.connected:
            self._log(f"> {command} (preview only)")
            self.status_var.set(f"Preview only. Web: {self.preview.url}")
            return

        try:
            self.client.send_line(command)
        except Exception as exc:
            messagebox.showerror("Send failed", str(exc))
            self._log(f"ERROR send failed: {exc}")
            return

        self._log(f"> {command}")

    def _open_preview(self):
        webbrowser.open(self.preview.url)
        self._log(f"Opened web preview: {self.preview.url}")

    def _poll_incoming(self):
        while True:
            try:
                line = self.incoming.get_nowait()
            except queue.Empty:
                break
            self._handle_line(line)
        self.after(80, self._poll_incoming)

    def _handle_line(self, line):
        self._log(f"< {line}")
        upper = line.upper()
        if upper.startswith("READY"):
            self.status_var.set(f"ESP ready. Preview: {self.preview.url}")
        elif upper.startswith("ERROR"):
            self.status_var.set(line)

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _log(self, message):
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def _on_close(self):
        self.client.disconnect()
        self.preview.shutdown()
        self.destroy()


if __name__ == "__main__":
    app = MotionControlApp()
    app.mainloop()
