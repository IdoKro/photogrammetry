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

// Reconnect variables
unsigned long lastWsReconnectAttempt = 0;
unsigned long lastWsRestart = 0;
unsigned long lastOtaCheck = 0;
const unsigned long WS_RECONNECT_INTERVAL = 5000;
const unsigned long OTA_CHECK_INTERVAL = 12000;
const unsigned long WS_RESTART_INTERVAL = 30000;

void setup() {

  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, LOW);  // Make sure it's off initially

  Serial.begin(115200);
  delay(500);  // Let USB and peripherals settle
  debugPrintln("\n");
  debugPrintln("Version: " + String(OTA_FIRMWARE_VERSION));

  bool connection_status = connectToWiFi();
  
  bool camera_status = startCamera();


  // Prepare timer
  esp_timer_create_args_t timer_args = {
    .callback = [](void*) { triggerCapture(); },
    .name = "capture_timer"
  };
  esp_timer_create(&timer_args, &capture_timer);
  
  connectToWebSocket();
  eventListener();
}

// --- Loop ---
void loop() {
  if (millis() - lastOtaCheck >= OTA_CHECK_INTERVAL) {
    lastOtaCheck = millis();
    debugPrintln("Checking For updates");
    checkForOTAUpdate();
  }
  wsClient.poll();
  // Check if WebSocket is disconnected and try reconnecting
  if (!wsClient.available()) {
    unsigned long now = millis();
    if (now - lastWsRestart >= WS_RESTART_INTERVAL){
        ESP.restart();
        lastWsRestart = now;
    }
    else if (now - lastWsReconnectAttempt >= WS_RECONNECT_INTERVAL) {
      debugPrintln("WebSocket disconnected, trying to reconnect...");
      wsClient.close();
      delay(100); // Give some time to fully close
      connectToWebSocket();
      lastWsReconnectAttempt = now;
    }
  }
}
