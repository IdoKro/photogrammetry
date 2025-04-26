import asyncio
import threading
import tkinter as tk
from PIL import Image, ImageTk, ImageFile
import camera_server
import os
import logging

ImageFile.LOAD_TRUNCATED_IMAGES = True  # allow fast partial images safely

class DeviceWidget:
    def __init__(self, canvas, name, x, y, size=100):
        self.canvas = canvas
        self.name = name
        self.size = size
        self.x = x
        self.y = y
        self.rect = canvas.create_rectangle(x, y, x+size, y+size, outline='blue', width=6)
        self.text = canvas.create_text(x + size/2, y + size + 10, text=name)
        self.image_id = None
        self.state = 'waiting'
        self.image_path = None

    def set_state(self, state):
        self.state = state
        colors = {
            'waiting': 'blue',
            'capturing': 'orange',
            'received': 'green'
        }
        self.canvas.itemconfig(self.rect, outline=colors[state])

    def set_image(self, image_path):
        self.image_path = image_path
        self._load_image()

    def _load_image(self):
        if not self.image_path:
            return

        img = Image.open(self.image_path)
        img = img.resize((self.size - 8, self.size - 8))
        self.tk_image = ImageTk.PhotoImage(img)

        if self.image_id:
            self.canvas.delete(self.image_id)

        self.image_id = self.canvas.create_image(
            self.x + 4,
            self.y + 4,
            anchor='nw',
            image=self.tk_image
        )
        self.set_state('received')

    def update_position(self, x, y, size):
        self.x = x
        self.y = y
        self.size = size
        self.canvas.coords(self.rect, x, y, x+size, y+size)
        self.canvas.coords(self.text, x + size/2, y + size + 10)
        if self.image_path:
            self._load_image()

class TextHandler(logging.Handler):
    def __init__(self, text_widget, max_lines=1000):
        super().__init__()
        self.text_widget = text_widget
        self.max_lines = max_lines

    def emit(self, record):
        msg = self.format(record)

        def append():
            self.text_widget.config(state=tk.NORMAL)

            level = record.levelname  # "DEBUG", "INFO", etc.

            self.text_widget.insert(tk.END, msg + "\n", level)

            self.text_widget.see(tk.END)

            # Limit total lines
            lines = int(self.text_widget.index('end-1c').split('.')[0])
            if lines > self.max_lines:
                self.text_widget.delete("1.0", f"{lines - self.max_lines}.0")

            self.text_widget.config(state=tk.DISABLED)

        self.text_widget.after(0, append)

class CaptureApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Photogrammetry Capture")

        self.canvas = tk.Canvas(root, bg="white")
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.capture_button = tk.Button(root, text="Capture", command=self.capture)
        self.capture_button.pack(pady=5)

        self.log_text = tk.Text(root, height=10, bg="black", fg="white", font=("Courier", 10))
        self.log_text.pack(fill=tk.BOTH, expand=False)
        self.log_text.config(state=tk.DISABLED)

        # === Define log level tags ===
        self.log_text.tag_config("DEBUG", foreground="cyan")
        self.log_text.tag_config("INFO", foreground="white")
        self.log_text.tag_config("WARNING", foreground="yellow")
        self.log_text.tag_config("ERROR", foreground="red")
        self.log_text.tag_config("CRITICAL", foreground="red", underline=1)

        self.device_widgets = {}

        self.root.bind("<Configure>", self.on_window_resize)

        # Attach the logger
        text_handler = TextHandler(self.log_text)
        text_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S"))
        camera_server.logger.addHandler(text_handler)

        self.update_devices()

    def on_window_resize(self, event):
        self.update_devices(force=True)

    def update_devices(self, force=False):
        if not force:
            self.root.after(2000, self.update_devices)

        existing_names = {camera_server.client_name_map.get(ws, f"unknown_{id(ws)}")
                          for ws in camera_server.connected_clients}

        # Remove disconnected devices
        to_delete = [name for name in self.device_widgets if name not in existing_names]
        for name in to_delete:
            del self.device_widgets[name]

        sorted_names = sorted(existing_names)
        num_devices = len(sorted_names)

        if num_devices == 0:
            self.canvas.delete("all")
            return

        canvas_width = self.canvas.winfo_width()
        canvas_height = self.canvas.winfo_height()

        if canvas_width <= 1 or canvas_height <= 1:
            canvas_width = 800
            canvas_height = 600

        margin = 20

        cols = int(num_devices ** 0.5)
        if cols == 0:
            cols = 1

        while True:
            rows = (num_devices + cols - 1) // cols

            available_width = canvas_width - (cols + 1) * margin
            available_height = canvas_height - (rows + 1) * margin

            if cols == 0 or rows == 0:
                break

            device_width = available_width // cols
            device_height = available_height // rows

            device_size = min(device_width, device_height)

            total_height = rows * (device_size + margin + 20) + margin

            if total_height <= canvas_height and device_size >= 50:
                break

            cols += 1

            if cols > num_devices:
                break

        for idx, name in enumerate(sorted_names):
            row = idx // cols
            col = idx % cols
            x = margin + col * (device_size + margin)
            y = margin + row * (device_size + margin + 20)

            if name not in self.device_widgets:
                widget = DeviceWidget(self.canvas, name, x, y, size=device_size)
                self.device_widgets[name] = widget
            else:
                widget = self.device_widgets[name]
                widget.update_position(x, y, device_size)

    def capture(self):
        for widget in self.device_widgets.values():
            widget.set_state('capturing')
        threading.Thread(target=self.capture_async).start()

    def capture_async(self):
        result = asyncio.run(camera_server.trigger_capture_and_wait())

        output_folder = result.get('folder')

        for name, widget in self.device_widgets.items():
            image_path = os.path.join(output_folder, f"{name}.jpg")
            if os.path.exists(image_path):
                widget.set_image(image_path)
            else:
                # Leave orange if image missing
                pass

def run():
    threading.Thread(target=lambda: asyncio.run(camera_server.start_server()), daemon=True).start()

    root = tk.Tk()
    app = CaptureApp(root)
    root.mainloop()


if __name__ == "__main__":
    run()