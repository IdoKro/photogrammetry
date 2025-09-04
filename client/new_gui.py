#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
new_gui.py — Tkinter GUI + LAN Web GUI wrapper for camera_server

- Starts camera_server on a background asyncio loop.
- Tk GUI: shows latest images and a single "Capture All" button.
- Web GUI (http://0.0.0.0:8088/ by default): same idea, from any device on your network.
- Web endpoints:
    GET  /            -> minimal HTML page
    GET  /state       -> JSON { cameras: [{cam_id, filename, mtime, url}] }
    POST /capture     -> triggers camera_server.trigger_capture_and_wait()
    GET  /images/<fn> -> serves latest image files from output directory
- Uses the SAME loop for everything (server, capture, web) to avoid timing skew.
- Streams camera_server logs into the Tk log panel. Clean shutdown.
"""

import asyncio
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

import camera_server

# ---------- Config ----------
WEB_HOST = "0.0.0.0"
WEB_PORT = 8088

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

def discover_output_root() -> Path:
    # server sets current_capture_folder for a capture session; fallback to "output"
    return Path(getattr(camera_server, "current_capture_folder", "output"))

def list_latest_images(root: Path) -> Dict[str, Path]:
    out = {}
    if root.exists():
        for fn in os.listdir(root):
            p = root / fn
            if p.is_file() and p.suffix.lower() in IMAGE_EXTS:
                out[p.stem] = p
    return out

# ---------- Tiles ----------
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
        self.canvas = tk.Canvas(self.border, bg="#111", highlightthickness=0, bd=0)
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
        except Exception:
            self.state.img=None
        self.render()

    def render(self):
        self.canvas.delete("all")
        if not self.state.img: return
        w = max(1, self.canvas.winfo_width()); h = max(1, self.canvas.winfo_height())
        side = min(self.state.img.width, self.state.img.height)
        img = self.state.img.crop(((self.state.img.width-side)//2,
                                   (self.state.img.height-side)//2,
                                   (self.state.img.width+side)//2,
                                   (self.state.img.height+side)//2))
        size = min(w, h)
        if size <= 0: return
        img = img.resize((size, size))
        self.state.tk_img = ImageTk.PhotoImage(img)
        self.canvas.create_image(w//2, h//2, image=self.state.tk_img, anchor="center")

# ---------- Web GUI (aiohttp) ----------
# We start aiohttp server on the SAME loop used by camera_server to avoid drift.
from aiohttp import web
import urllib.parse

_web_runner: Optional[web.AppRunner] = None
_web_site:   Optional[web.TCPSite]   = None

WEB_INDEX_HTML = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Camera Web GUI</title>
<meta name="viewport" content="width=device-width,initial-scale=1" />
<style>
  body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,"Helvetica Neue",Arial}
  .top{display:flex;justify-content:space-between;align-items:center;margin:12px}
  .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px;margin:12px}
  .tile{border:3px solid #5cb85c;border-radius:10px;overflow:hidden;background:#111;color:#ddd}
  .tile img{display:block;width:100%;aspect-ratio:1/1;object-fit:cover;background:#111}
  .bar{display:flex;justify-content:space-between;align-items:center;background:#1b1b1b;padding:6px 10px;font-size:14px}
  button{padding:8px 14px;border-radius:8px;border:0;background:#0275d8;color:white;font-weight:600;cursor:pointer}
  button:disabled{opacity:.6;cursor:not-allowed}
</style>
</head>
<body>
  <div class="top">
    <div><b>Camera Web GUI</b></div>
    <div><button id="cap">Capture All</button></div>
  </div>
  <div id="grid" class="grid"></div>

<script>
const grid = document.getElementById('grid');
const capBtn = document.getElementById('cap');

function phaseColor(p){
  return {IDLE:'#5cb85c', REQUESTED:'#f0ad4e', RECEIVING:'#0275d8', ERROR:'#d9534f'}[p] || '#999';
}

async function loadState(){
  const r = await fetch('/state');
  const j = await r.json();
  grid.innerHTML = '';
  for(const cam of j.cameras){
    const d = document.createElement('div');
    d.className = 'tile';
    d.style.borderColor = phaseColor(cam.phase || 'IDLE');
    d.innerHTML = `
      <img src="${cam.url}" alt="${cam.cam_id}" />
      <div class="bar"><span>${cam.cam_id}</span><span>${cam.phase||'IDLE'}</span></div>`;
    grid.appendChild(d);
  }
}

capBtn.onclick = async ()=>{
  capBtn.disabled = true;
  try{
    const r = await fetch('/capture', {method:'POST'});
    const j = await r.json();
    console.log(j);
    // quick refresh loop
    await new Promise(r=>setTimeout(r, 300));
    await loadState();
  } finally {
    capBtn.disabled = false;
  }
}

loadState();
setInterval(loadState, 1500);
</script>
</body>
</html>"""

async def _web_index(request: web.Request):
    return web.Response(text=WEB_INDEX_HTML, content_type="text/html")

def _safe_join(base: Path, name: str) -> Path:
    # prevent directory traversal
    name = Path(urllib.parse.unquote(name)).name
    return (base / name).resolve()

async def _web_state(request: web.Request):
    root = discover_output_root()
    cams = []
    latest = list_latest_images(root)
    for cam_id, path in latest.items():
        cams.append({
            "cam_id": cam_id,
            "filename": path.name,
            "mtime": path.stat().st_mtime if path.exists() else 0,
            "phase": "IDLE",  # lightweight; Tk tracks transient phases locally
            "url": f"/images/{path.name}"
        })
    return web.json_response({"cameras": cams, "folder": str(root)})

async def _web_capture(request: web.Request):
    async def _invoke():
        if asyncio.iscoroutinefunction(camera_server.trigger_capture_and_wait):
            return await camera_server.trigger_capture_and_wait()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, camera_server.trigger_capture_and_wait)

    try:
        # run on SAME loop
        result = await _invoke()
        return web.json_response({"ok": True, "result": result})
    except Exception as e:
        camera_server.logger.exception("Web capture error")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def _web_image(request: web.Request):
    root = discover_output_root()
    name = request.match_info["name"]
    path = _safe_join(root, name)
    if not path.exists() or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path)

async def start_webgui():
    global _web_runner, _web_site
    app = web.Application()
    app.router.add_get("/", _web_index)
    app.router.add_get("/state", _web_state)
    app.router.add_post("/capture", _web_capture)
    app.router.add_get("/images/{name}", _web_image)

    _web_runner = web.AppRunner(app)
    await _web_runner.setup()
    _web_site = web.TCPSite(_web_runner, host=WEB_HOST, port=WEB_PORT)
    await _web_site.start()
    camera_server.logger.info(f"🌐 Web GUI at http://{WEB_HOST}:{WEB_PORT}/")

async def stop_webgui():
    global _web_runner, _web_site
    try:
        if _web_site:
            await _web_site.stop()
        if _web_runner:
            await _web_runner.cleanup()
    finally:
        _web_runner = None
        _web_site = None

# ---------- GUI ----------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Camera Server GUI")
        self.geometry("1200x800")

        top=ttk.Frame(self); top.pack(fill="x")
        ttk.Button(top,text="Capture All",command=self.capture).pack(side="right")
        ttk.Label(top, text=f"Web GUI: http://{WEB_HOST}:{WEB_PORT}/").pack(side="left", padx=6)

        self.inner=ttk.Frame(self); self.inner.pack(fill="both",expand=True)
        self.tiles: Dict[str,CamTile]={}

        log_frame=ttk.Frame(self); log_frame.pack(fill="x",side="bottom")
        self.log=tk.Text(log_frame,height=10,state="normal"); self.log.pack(fill="x")
        camera_server.logger.addHandler(TkTextHandler(self.log))
        camera_server.logger.setLevel(logging.INFO)

        self.after(500,self.scan)

        # start server tasks on SAME loop + web gui
        self.server_futs = []
        self.server_futs.append(_async.run(camera_server.start_server()))
        if hasattr(camera_server, "broadcast_time"):
            self.server_futs.append(_async.run(camera_server.broadcast_time()))
        self.server_futs.append(_async.run(start_webgui()))

        self.protocol("WM_DELETE_WINDOW",self.on_close)

    def ensure_tile(self,cam_id):
        if cam_id not in self.tiles:
            state=CamState(cam_id)
            tile=CamTile(self.inner,state)
            tile.pack(side="left",padx=5,pady=5,fill="y")
            self.tiles[cam_id]=tile
        return self.tiles[cam_id]

    def scan(self):
        root=discover_output_root()
        latest = list_latest_images(root)
        for cam_id, path in latest.items():
            tile=self.ensure_tile(cam_id)
            if tile.state.path!=path:
                tile.set_phase("RECEIVING")
                tile.set_image(path)
                tile.set_phase("IDLE")
        self.after(1000,self.scan)

    def capture(self):
        # UI phase update
        for t in self.tiles.values(): t.set_phase("REQUESTED")

        async def _invoke_on_server_loop():
            if asyncio.iscoroutinefunction(camera_server.trigger_capture_and_wait):
                return await camera_server.trigger_capture_and_wait()
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, camera_server.trigger_capture_and_wait)

        def _worker():
            try:
                fut = _async.run(_invoke_on_server_loop())
                res = fut.result()
                camera_server.logger.info(f"Capture result: {res}")
            except Exception as e:
                camera_server.logger.error(f"Capture error: {e}")
        threading.Thread(target=_worker,daemon=True).start()

    def on_close(self):
        # Stop web GUI first
        try:
            _async.run(stop_webgui()).result(timeout=2)
        except Exception:
            pass
        # Cancel long-running server tasks
        for f in getattr(self, "server_futs", []):
            try: f.cancel()
            except Exception: pass
        _async.stop()
        self.destroy()

if __name__=="__main__":
    App().mainloop()
