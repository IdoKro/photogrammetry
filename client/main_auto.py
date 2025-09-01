import asyncio

from anyio import sleep

import camera_server
import logging
import colorlog

def setup_camera_server_logger():
    logger = logging.getLogger("camera_server")
    logger.setLevel(logging.DEBUG)

    handler = logging.StreamHandler()

    formatter = colorlog.ColoredFormatter(
        "%(log_color)s[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt='%H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'blue',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold_red',
        }
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

setup_camera_server_logger()  # <-- move outside async

async def wait_for_user_input():
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, input, "\nPress ENTER to trigger synchronized capture...")
    result = await camera_server.trigger_capture_and_wait()
    await asyncio.sleep(0.2)  # give server a moment to start

    if result["success"]:
        num_images = result["saved_images"]
        folder = result["folder"]

        print(f"Capture successful! {num_images} Images were saved to {folder}")
    else:
        print(f"Capture failed. Missing images from: {result.get('missing', [])}")

async def auto_input():
    result = await camera_server.trigger_capture_and_wait()

    if result["success"]:
        num_images = result["saved_images"]
        folder = result["folder"]

        print(f"Capture successful! {num_images} Images were saved to {folder}")
    else:
        print(f"Capture failed. Missing images from: {result.get('missing', [])}")

    await asyncio.sleep(10)  # give server a moment to start

async def main():
    # Start the server
    asyncio.create_task(camera_server.start_server())

    asyncio.create_task(camera_server.broadcast_time())

    await asyncio.sleep(10)  # give server a moment to start

    await wait_for_user_input()

    while True:
        # await wait_for_user_input()
        await auto_input()

if __name__ == "__main__":
    asyncio.run(main())
