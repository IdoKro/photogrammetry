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
TIMEOUT = 5     # seconds to wait for images

connected_clients = set()
client_name_map = {}  # NEW: websocket -> device name
current_capture_folder = None
metadata_records = {}  # NEW: device_name -> metadata dictionary

capture_expected_clients = set()
capture_received_clients = set()

datasheet_name = f"capture_log{time.time()}.csv"

# === Handle each client ===
async def handle_client(websocket):
    global current_capture_folder

    connected_clients.add(websocket)
    client_id = id(websocket)
    device_name = f"client_{client_id}"  # fallback if no hello

    logger.info(f"[+] Client {client_id} connected. Total: {len(connected_clients)}")

    try:
        # Try to receive hello message
        hello_raw = await asyncio.wait_for(websocket.recv(), timeout=2.0)
        hello = json.loads(hello_raw)

        if hello.get("type") == "hello":
            device_name = hello.get("device_id", device_name)
            logger.info(f"🤖 Device name received: {device_name}")
        else:
            logger.warning(f"⚠️ Unexpected first message: {hello}")

    except Exception as e:
        logger.warning(f"⚠️ No hello message received: {e}")

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
                logger.info(f"📸 Received image from {sender_name}: {len(message)} bytes")

                # Save image
                if current_capture_folder is None:
                    current_capture_folder = "output/uncategorized"  # fallback
                    os.makedirs(current_capture_folder, exist_ok=True)

                filename = f"{current_capture_folder}/{sender_name}.jpg"
                with open(filename, "wb") as f:
                    f.write(message)
                logger.info(f"💾 Saved {filename}")

                capture_received_clients.add(websocket)

            else:
                data = json.loads(message)
                if data.get("type") == "capture_metadata":
                    device_name = data.get("device_id", f"unknown_{id(websocket)}")
                    metadata_records[device_name] = data
                    logger.info(f"📝 Metadata received from {device_name}")
                else:
                    logger.info(f"📩 Text message: {data}")

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        connected_clients.remove(websocket)
        client_name_map.pop(websocket, None)
        logger.info(f"[-] Client {device_name} disconnected. Total: {len(connected_clients)}")

# === Periodic broadcast ===
async def broadcast_time():
    while True:
        if connected_clients:
            now = time.time()
            message = {
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
            ping_interval=5,  # send pings every 5 seconds
            ping_timeout=10  # disconnect if no pong after 5 seconds
    ):
        logger.info(f"🌐 WebSocket server started on port {PORT}")
        await asyncio.Future()  # Run forever

# === Trigger capture and wait ===
async def trigger_capture_and_wait(sync_delay=SYNC_DELAY, timeout=TIMEOUT):
    global current_capture_folder, capture_expected_clients, capture_received_clients

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

    logger.info(f"\n📸 Sending capture request for T = {capture_time:.3f} to {len(connected_clients)} clients")
    logger.info(f"🗂️ Images will be saved to: {current_capture_folder}")

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
        logger.warning(f"⚠️ Missing images from: {missing_names}")
        return {
            "success": False,
            "missing": missing_names,
            "saved_images": saved_images,
            "folder": current_capture_folder}
    else:
        images_received_time = time.time()
        logger.info("✅ All images received!")

        save_capture_to_csv(
            current_capture_folder,
            metadata_records,
            capture_request_received_time,
            images_received_time,
            sync_delay,
            len(capture_expected_clients)
        )

        return {"success": True,
                "saved_images": saved_images,
                "folder": current_capture_folder}



def save_capture_to_csv(capture_folder, metadata_records, capture_request_received_time, images_received_time, sync_delay, num_modules):
    csv_path = datasheet_name
    file_exists = os.path.isfile(csv_path)

    # Build list of all devices
    all_devices = sorted(metadata_records.keys())

    # Build CSV header dynamically
    fieldnames = ["capture_folder", "capture_request_received_time", "images_received_time", "sync_delay", "num_modules"]
    for device in all_devices:
        fieldnames.extend([
            f"{device}_capture_request_received",
            f"{device}_capture_started",
            f"{device}_capture_completed",
            f"{device}_image_sent",
            f"{device}_rssi",
            f"{device}_resolution",
            f"{device}_jpeg_quality",
            f"{device}_image_size",
        ])

    # Now always open the file for reading first (if exists)
    old_rows = []
    if file_exists:
        with open(csv_path, mode='r', newline='') as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                old_rows.append(row)

    # Now overwrite file
    with open(csv_path, mode='w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        # Re-write old rows, adapting them
        for old_row in old_rows:
            adapted_row = {field: old_row.get(field, "") for field in fieldnames}
            writer.writerow(adapted_row)

        # Write new row
        new_row = {
            "capture_folder": capture_folder,
            "capture_request_received_time": capture_request_received_time,
            "images_received_time": images_received_time,
            "sync_delay": sync_delay,
            "num_modules": num_modules,
        }

        for device, meta in metadata_records.items():
            times = meta.get("times", {})
            new_row[f"{device}_capture_request_received"] = times.get("capture_request_received")
            new_row[f"{device}_capture_started"] = times.get("capture_started")
            new_row[f"{device}_capture_completed"] = times.get("capture_completed")
            new_row[f"{device}_image_sent"] = times.get("image_sent")

            new_row[f"{device}_rssi"] = meta.get("rssi")
            new_row[f"{device}_resolution"] = meta.get("resolution")
            new_row[f"{device}_jpeg_quality"] = meta.get("jpeg_quality")
            new_row[f"{device}_image_size"] = meta.get("image_size")

        writer.writerow(new_row)