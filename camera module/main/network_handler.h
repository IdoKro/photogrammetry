#pragma once

#include <ArduinoWebsockets.h>
#include "esp_camera.h"
#include "camera_pins.h"

using namespace websockets;

extern WebsocketsClient wsClient;
extern esp_timer_handle_t capture_timer;
extern double timeOffset;

// Wi-Fi & WebSocket APIs
bool connectToWiFi();           // Boot Wi-Fi with 10s timeout → reboot on failure
void connectToWebSocket();      // Binds handlers (once) and attempts a single connect

// Messaging helpers
void sendHelloMessage();
void sendImage(camera_fb_t *fb);
void sendImageMetadata(int capturedImageSize);
void sendStatus();

// Status & pump
bool isWebSocketConnected();    // Read-only WS state
void networkLoop();             // Call every loop() — polls, backoff reconnects, no flapping
