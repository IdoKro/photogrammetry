import serial
import struct
import time

port = "COM6"  # Replace with your ESP32-CAM serial port
baud_rate = 115200
ser = serial.Serial(port, baud_rate, timeout=10)

def capture_image():
    ser.write(b"CAPTURE\n")
    ser.flush()  # Ensure the command is sent immediately

    print("Waiting for ESP32-CAM to respond...")
    ack = ser.readline().decode().strip()
    if ack != "Taking picture...":
        print(f"Unexpected response: {ack}")
        return

    size_bytes = ser.read(4)
    if len(size_bytes) < 4:
        print("Failed to read image size")
        return

    size = struct.unpack('<I', size_bytes)[0]
    print(f"Image size: {size} bytes")

    image_data = ser.read(size)
    if len(image_data) < size:
        print("Failed to read complete image data")
        return

    with open("captured_image.jpg", "wb") as file:
        file.write(image_data)
    print("Image saved as 'captured_image.jpg'")

if __name__ == "__main__":
    try:
        print("Waiting for ESP32-CAM...")
        input("Press Enter to take a picture.")
        capture_image()
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        ser.close()