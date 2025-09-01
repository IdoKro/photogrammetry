import asyncio
import websockets
import time
import json
import os
import logging
import csv

logger = logging.getLogger("camera_server")
logger.setLevel(logging.INFO)

PORT = 8765
SYNC_DELAY = 2  # seconds from now to capture
TIMEOUT = 15     # seconds to wait for images

METADATA_CSV_PATH = "metadata_log.csv"
METADATA_FIELDS = ["timestamp",
                   "mac",
                   "device_id",
                   "firmware_version",
                   "board_type",
                   "rssi",
                   "resolution",
                   "jpeg_quality",
                   "image_size",
                   "duration",
                   "sync_delay"]

# Ensure CSV file exists with headers
if not os.path.exists(METADATA_CSV_PATH):
    with open(METADATA_CSV_PATH, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=METADATA_FIELDS)
        writer.writeheader()

connected_clients = set()
client_name_map = {}         # websocket -> user-friendly name
client_mac_map = {}          # websocket -> MAC
mac_to_ws = {}               # MAC -> websocket
image_receive_times = {}     # MAC -> time
metadata_records = {}        # MAC -> latest metadata

capture_expected_clients = set()
capture_received_clients = set()

datasheet_name = f"capture_log{time.time()}.csv"

def sanitize_filename(s):
    return "".join(c for c in s if c.isalnum() or c in "-_")

# === Handle each client ===
async def handle_client(websocket):
    global current_capture_folder

    connected_clients.add(websocket)
    client_id = id(websocket)

    mac_id = None
    device_name = f"client_{client_id}"

    logger.info(f"[+] Client {client_id} connected. Total: {len(connected_clients)}")

    try:
        # Try to receive hello message
        hello_raw = await asyncio.wait_for(websocket.recv(), timeout=2.0)
        hello = json.loads(hello_raw)

        if hello.get("type") == "hello":
            mac_id = hello.get("mac")
            device_name = hello.get("device_id", device_name)
            if not mac_id:
                logger.warning("No MAC provided — treating as anonymous")
            else:
                client_mac_map[websocket] = mac_id
                mac_to_ws[mac_id] = websocket

            logger.info(f"Connected: {device_name} (MAC: {mac_id})")
        else:
            logger.warning(f"Unexpected first message: {hello}")

    except Exception as e:
        logger.warning(f"No hello message received: {e}")

    # Save mapping
    client_name_map[websocket] = device_name

    await asyncio.sleep(0.1)

    # Send time sync
    now = time.time()
    await websocket.send(json.dumps({
        "type": "sync",
        "time": now
    }))

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                sender_name = client_name_map.get(websocket, f"unknown_{client_id}")
                mac = client_mac_map.get(websocket)
                logger.info(f"Received image from {sender_name}: {len(message)} bytes")

                # Save image
                if current_capture_folder is None:
                    current_capture_folder = "output/uncategorized"  # fallback
                    os.makedirs(current_capture_folder, exist_ok=True)

                safe_device_name = sanitize_filename(sender_name)
                safe_mac = sanitize_filename(mac)
                filename = f"{current_capture_folder}/{safe_device_name}-{safe_mac}.jpg"
                with open(filename, "wb") as f:
                    f.write(message)
                logger.info(f"Saved {filename}")

                if mac:
                    image_receive_times[mac] = time.time()

                capture_received_clients.add(websocket)

            else:
                data = json.loads(message)
                if data.get("type") == "capture_metadata":
                    mac_id = data.get("mac")
                    device_name = data.get("device_id", f"unknown_{id(websocket)}")

                    metadata_records[mac_id] = data
                    logger.info(f"Metadata received from {device_name} (MAC: {mac_id})")

                    img_time = image_receive_times.get(mac_id)
                    if img_time and capture_request_received_time:
                        duration = img_time - capture_request_received_time
                    else:
                        duration = None

                    # Prepend to CSV file
                    row = {
                        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        "mac": mac_id,
                        "device_id": data.get("device_id", ""),
                        "firmware_version": data.get("firmware_version", ""),
                        "board_type": data.get("board_type", ""),
                        "rssi": data.get("rssi", ""),
                        "resolution": data.get("resolution", ""),
                        "jpeg_quality": data.get("jpeg_quality", ""),
                        "image_size": data.get("image_size", ""),
                        "duration": duration,
                        "sync_delay": SYNC_DELAY
                    }

                    try:
                        with open(METADATA_CSV_PATH, "r", newline="") as f:
                            existing = list(f)
                        with open(METADATA_CSV_PATH, "w", newline="") as f:
                            f.write(','.join(METADATA_FIELDS) + '\n')  # ensure header
                            writer = csv.DictWriter(f, fieldnames=METADATA_FIELDS)
                            writer.writerow(row)
                            f.writelines(existing[1:] if existing and "timestamp" in existing[0] else existing)
                    except Exception as e:
                        logger.error(f"Failed to update metadata CSV: {e}")
                else:
                    logger.info(f"Text message: {data}")

    except websockets.exceptions.ConnectionClosed as e:
        pass

    finally:
        connected_clients.remove(websocket)
        client_name_map.pop(websocket, None)
        if websocket in client_mac_map:
            mac = client_mac_map.pop(websocket)
            mac_to_ws.pop(mac, None)
        logger.info(f"[-] Client {device_name} disconnected. Total: {len(connected_clients)}")

# === Periodic broadcast ===
async def broadcast_time():
    while True:
        if connected_clients:
            now = time.time()
            message = \
                {
                "type": "sync",
                "time": now
            }
            await asyncio.gather(*[client.send(json.dumps(message)) for client in connected_clients])
        await asyncio.sleep(5)

# === Start server ===
async def start_server():
    async with websockets.serve(
        handle_client,
        "0.0.0.0",
        PORT,
        ping_interval=20,
        ping_timeout=60
    ):
        logger.info(f"WebSocket server started on port {PORT}")
        try:
            # park forever until cancelled
            await asyncio.Future()
        except asyncio.CancelledError:
            logger.info("Server task cancelled — shutting down websocket server gracefully.")
            # give clients a tick to close if you want:
            await asyncio.sleep(0)
            raise  # let the cancellation propagate cleanly

# === Trigger capture and wait ===
async def trigger_capture_and_wait(sync_delay=SYNC_DELAY, timeout=TIMEOUT):
    global current_capture_folder, capture_expected_clients, capture_received_clients, capture_request_received_time

    capture_request_received_time = time.time()
    capture_time = capture_request_received_time + sync_delay
    timestamp_str = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(capture_time))
    current_capture_folder = f"output/capture_{timestamp_str}"
    os.makedirs(current_capture_folder, exist_ok=True)

    capture_expected_clients = connected_clients.copy()
    capture_received_clients = set()

    message = {
        "type": "capture",
        "time": capture_time
    }

    logger.info(f"Sending capture request for T = {capture_time:.3f} to {len(connected_clients)} clients")
    logger.info(f"Images will be saved to: {current_capture_folder}")
    capturing_time = time.time()

    if connected_clients:
        await asyncio.gather(*[client.send(json.dumps(message)) for client in connected_clients])
    else:
        logger.warning("⚠️ No clients connected!")
        return {
            "success": False,
            "error": "No clients connected",
            "saved_images": 0,
            "folder": current_capture_folder
        }

    # Wait intelligently for all images to arrive
    max_wait = timeout
    check_interval = 0.1  # seconds
    waited = 0

    while waited < max_wait:
        if capture_expected_clients == capture_received_clients:
            break
        await asyncio.sleep(check_interval)
        waited += check_interval

    missing_clients = capture_expected_clients - capture_received_clients
    saved_images = len(capture_received_clients)

    if missing_clients:
        missing_names = [client_name_map.get(client, f"unknown_{id(client)}") for client in missing_clients]
        logger.warning(f"Missing images from: {missing_names}")
        return {
            "success": False,
            "missing": missing_names,
            "saved_images": saved_images,
            "folder": current_capture_folder}
    else:
        images_received_time = time.time()
        logger.info("All images received!")
        logger.info(f"Capture duration: {time.time() - capturing_time:.3f} seconds")

        return {"success": True,
                "saved_images": saved_images,
                "folder": current_capture_folder}