import asyncio
import websockets
import time
import json

PORT = 8765
SYNC_DELAY = 5  # seconds from now to capture

connected_clients = set()

async def handle_client(websocket):
    connected_clients.add(websocket)
    client_id = id(websocket)
    print(f"[+] Client {client_id} connected. Total: {len(connected_clients)}")

    await asyncio.sleep(0.1)  # ⏳ give the handshake time to complete (100ms)

    # 🔄 Immediately send time sync
    now = time.time()
    message = {
        "type": "sync",
        "time": now
    }
    await websocket.send(json.dumps(message))

    try:
        await websocket.wait_closed()
    finally:
        connected_clients.remove(websocket)
        print(f"[-] Client {client_id} disconnected. Total: {len(connected_clients)}")

async def wait_for_user_input():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "\nPress ENTER to trigger synchronized capture...")

    capture_time = time.time() + SYNC_DELAY
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
            ping_timeout=5  # disconnect if no pong after 5 seconds
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