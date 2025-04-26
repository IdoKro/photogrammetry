import asyncio
import websockets
import time
import json
import os

PORT = 8765
SYNC_DELAY = 2  # seconds from now to capture

connected_clients = set()
client_name_map = {}  # NEW: websocket -> device name
current_capture_folder = None

async def handle_client(websocket):
    global current_capture_folder

    connected_clients.add(websocket)
    client_id = id(websocket)
    device_name = f"client_{client_id}"  # fallback if no hello

    print(f"[+] Client {client_id} connected. Total: {len(connected_clients)}")

    try:
        # Try to receive hello message
        hello_raw = await asyncio.wait_for(websocket.recv(), timeout=2.0)
        hello = json.loads(hello_raw)

        if hello.get("type") == "hello":
            device_name = hello.get("device_id", device_name)
            print(f"🤖 Device name received: {device_name}")
        else:
            print(f"⚠️ Unexpected first message: {hello}")

    except Exception as e:
        print(f"⚠️ No hello message received: {e}")

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
                print(f"📸 Received image from {sender_name}: {len(message)} bytes")

                # Save image
                if current_capture_folder is None:
                    current_capture_folder = "output/uncategorized"  # fallback
                    os.makedirs(current_capture_folder, exist_ok=True)

                filename = f"{current_capture_folder}/{sender_name}.jpg"
                with open(filename, "wb") as f:
                    f.write(message)
                print(f"💾 Saved {filename}")

            else:
                data = json.loads(message)
                print(f"📩 Text message: {data}")

    except websockets.exceptions.ConnectionClosed:
        pass

    finally:
        connected_clients.remove(websocket)
        client_name_map.pop(websocket, None)
        print(f"[-] Client {device_name} disconnected. Total: {len(connected_clients)}")

async def wait_for_user_input():
    global current_capture_folder

    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "\nPress ENTER to trigger synchronized capture...\n")

    capture_time = time.time() + SYNC_DELAY
    timestamp_str = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(capture_time))
    current_capture_folder = f"output/capture_{timestamp_str}"
    os.makedirs(current_capture_folder, exist_ok=True)

    message = {
        "type": "capture",
        "time": capture_time
    }

    print(f"\n📸 Sending capture request for T = {capture_time:.3f} to {len(connected_clients)} clients")

    if connected_clients:
        await asyncio.gather(*[client.send(json.dumps(message)) for client in connected_clients])
    else:
        print("⚠️ No clients connected!")

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

async def main():
    async with websockets.serve(
            handle_client,
            "0.0.0.0",
            PORT,
            ping_interval=5,  # send pings every 5 seconds
            ping_timeout=10  # disconnect if no pong after 5 seconds
    ):
        asyncio.create_task(broadcast_time())
        while True:
            await wait_for_user_input()


if __name__ == "__main__":
    while True:
        try:
            asyncio.run(main())
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            print("🔄 Restarting server...")
            time.sleep(2)