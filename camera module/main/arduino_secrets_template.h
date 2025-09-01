#pragma once

// Replace with your WiFi SSID and password
#define SECRET_SSID "SSID"
#define SECRET_PASS "PASSWORD"

// Server IP address and unique device name for identification
#define SECRET_SERVER_IP "SERVER IP ADDRESS"
#define SECRET_DEVICE_NAME "DEVICE NAME"

#define OTA_FIRMWARE_VERSION "FIRMWARE_VERSION"

#define OTA_PORT "OTA_SERVER_PORT"
#define OTA_URL SECRET_SERVER_IP "/firmware.bin"
#define OTA_VERSION_URL SECRET_SERVER_IP "/version.txt"

#define OTA_AUTH_TOKEN "YOUR_SUPER_SECRET_TOKEN"

// Uncomment the correct board:

// #define CAMERA_MODEL_WROVER_KIT
// #define CAMERA_MODEL_AI_THINKER
// #define CAMERA_MODEL_ESP32S3_EYE