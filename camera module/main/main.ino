#include <Arduino.h>
#include "arduino_secrets.h"
#include "camera_pins.h"
#include "camera_handler.h"
#include "network_handler.h"
#include "esp_timer.h"
#include "debug.h"
#include "ota.h"

esp_timer_handle_t capture_timer;
double timeOffset = 0;

// OTA timer
unsigned long lastOtaCheck = 0;
const unsigned long OTA_CHECK_INTERVAL = 12000;

void setup() {
  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, LOW);

  Serial.begin(115200);
  delay(500);
  debugPrintln("\n");
  debugPrintln("Version: " + String(OTA_FIRMWARE_VERSION));

  // 1) Wi-Fi with 10s timeout → reboot on failure
  connectToWiFi();

  // 2) Camera
  startCamera();

  // 3) Capture timer
  esp_timer_create_args_t timer_args = {
    .callback = [](void*) { triggerCapture(); },
    .name     = "capture_timer"
  };
  esp_timer_create(&timer_args, &capture_timer);

  // 4) WebSocket (bind handlers & attempt initial connect)
  connectToWebSocket();
  // DO NOT call eventListener(); it's integrated into connectToWebSocket()
}

void loop() {
  // Keep WS alive (poll + gentle reconnect)
  networkLoop();

  // OTA check
  if (millis() - lastOtaCheck >= OTA_CHECK_INTERVAL) {
    lastOtaCheck = millis();
    debugPrintln("Checking For updates");
    checkForOTAUpdate();
  }

  // Keep loop snappy; avoid long blocking work
}
