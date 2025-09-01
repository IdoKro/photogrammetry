#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
new_gui.py — Tkinter GUI wrapper for camera_server

- Starts camera_server in the background (async coroutine).
- Provides a single "Capture All" button → calls camera_server.trigger_capture_and_wait().
- Watches the filesystem (camera_server.current_capture_folder / output/) and shows latest image per camera.
- Each tile border shows phase: IDLE=green, REQUESTED=orange, RECEIVING=blue.
- Camera server logs are streamed live into the bottom text widget.
- Clean shutdown cancels server task to avoid "Task was destroyed but it is pending".
"""

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

import camera_server

# ---------- Async runner in background thread ----------
class AsyncRunner:
    def __init__(self):
        self.loop = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._ready = threading.Event()
        self._thread.start()
        self._ready.wait()

    def _run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def stop(self):
        if self.loop:
            self.loop.call_soon_threadsafe(self.loop.stop)

_async = AsyncRunner()

# ---------- Logging handler ----------
class TkTextHandler(logging.Handler):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget
        self.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", "%H:%M:%S"))

    def emit(self, record):
        msg = self.format(record)
        self.widget.after(0, lambda: self._append(msg))

    def _append(self, msg):
        self.widget.configure(state="normal")
        self.widget.insert("end", msg + "\n")
        self.widget.see("end")
        self.widget.configure(state="disabled")

# ---------- Helpers ----------
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
PHASE_COLORS = {"IDLE":"#5cb85c", "REQUESTED":"#f0ad4e", "RECEIVING":"#0275d8", "ERROR":"#d9534f"}

def discover_output_root():
    return Path(getattr(camera_server, "current_capture_folder", "output"))

def list_latest_images(root: Path):
    out = {}
    if root.exists():
        for fn in os.listdir(root):
            p = root / fn
            if p.suffix.lower() in IMAGE_EXTS:
                out[p.stem] = p
    return out

@dataclass
class CamState:
    cam_id: str
    phase: str = "IDLE"
    path: Optional[Path] = None
    img: Optional[Image.Image] = None
    tk_img: Optional[ImageTk.PhotoImage] = None

class CamTile(ttk.Frame):
    def __init__(self, parent, state: CamState):
        super().__init__(parent)
        self.state = state
        self.border = tk.Frame(self, bd=3, relief="solid", bg=PHASE_COLORS["IDLE"])
        self.border.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(self.border, bg="#111")
        self.canvas.pack(fill="both", expand=True)
        bottom = ttk.Frame(self.border); bottom.pack(fill="x")
        self.name_lbl = ttk.Label(bottom, text=state.cam_id); self.name_lbl.pack(side="left")
        self.phase_lbl = ttk.Label(bottom, text=state.phase); self.phase_lbl.pack(side="right")
        self.bind("<Configure>", lambda e: self.render())

    def set_phase(self, phase):
        self.state.phase = phase
        self.phase_lbl.config(text=phase)
        self.border.config(bg=PHASE_COLORS.get(phase,"#999"))
        self.render()

    def set_image(self, path: Path):
        self.state.path = path
        try:
            self.state.img = Image.open(path).convert("RGB")
        except: self.state.img=None
        self.render()

    def render(self):
        self.canvas.delete("all")
        if not self.state.img: return
        w,h=self.canvas.winfo_width(),self.canvas.winfo_height()
        side=min(self.state.img.width,self.state.img.height)
        img=self.state.img.crop(((self.state.img.width-side)//2,
                                 (self.state.img.height-side)//2,
                                 (self.state.img.width+side)//2,
                                 (self.state.img.height+side)//2))
        img=img.resize((min(w,h),min(w,h)))
        self.state.tk_img=ImageTk.PhotoImage(img)
        self.canvas.create_image(w//2,h//2,image=self.state.tk_img,anchor="center")

# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Camera Server GUI")
        self.geometry("1200x800")

        top=ttk.Frame(self); top.pack(fill="x")
        ttk.Button(top,text="Capture All",command=self.capture).pack(side="right")

        self.inner=ttk.Frame(self); self.inner.pack(fill="both",expand=True)
        self.tiles: Dict[str,CamTile]={}

        log_frame=ttk.Frame(self); log_frame.pack(fill="x",side="bottom")
        self.log=tk.Text(log_frame,height=10,state="normal"); self.log.pack(fill="x")
        camera_server.logger.addHandler(TkTextHandler(self.log))
        camera_server.logger.setLevel(logging.INFO)

        self.after(500,self.scan)

        # start server tasks on THE SAME loop and keep strong refs
        self.server_futs = []
        self.server_futs.append(_async.run(camera_server.start_server()))
        if hasattr(camera_server, "broadcast_time"):
            self.server_futs.append(_async.run(camera_server.broadcast_time()))

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def ensure_tile(self,cam_id):
        if cam_id not in self.tiles:
            state=CamState(cam_id)
            tile=CamTile(self.inner,state)
            tile.pack(side="left",padx=5,pady=5,fill="y")
            self.tiles[cam_id]=tile
        return self.tiles[cam_id]

    def scan(self):
        root=discover_output_root()
        for cam_id,path in list_latest_images(root).items():
            tile=self.ensure_tile(cam_id)
            if tile.state.path!=path:
                tile.set_phase("RECEIVING")
                tile.set_image(path)
                tile.set_phase("IDLE")
        self.after(1000,self.scan)

    def capture(self):
        # UI: mark REQUESTED right away
        for t in self.tiles.values():
            t.set_phase("REQUESTED")

        async def _invoke_on_server_loop():
            """
            This runs entirely inside the SAME event loop where start_server() runs.
            Any loop.time()/asyncio.sleep in camera_server will now be consistent.
            """
            if asyncio.iscoroutinefunction(camera_server.trigger_capture_and_wait):
                return await camera_server.trigger_capture_and_wait()
            # If it isn't a coroutine function, run it in a thread but keep this wrapper on the server loop
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, camera_server.trigger_capture_and_wait)

        def _worker():
            try:
                fut = _async.run(_invoke_on_server_loop())
                res = fut.result()  # waits in this worker thread only
                camera_server.logger.info(f"Capture result: {res}")
            except Exception as e:
                camera_server.logger.error(f"Capture error: {e}")

        threading.Thread(target=_worker, daemon=True).start()

    def on_close(self):
        # cancel all long-running server tasks first
        for f in getattr(self, "server_futs", []):
            try:
                f.cancel()
            except Exception:
                pass
        _async.stop()
        self.destroy()

if __name__=="__main__":
    App().mainloop()
