#pragma once

#include <ArduinoWebsockets.h>
#include "esp_camera.h"
#include "camera_pins.h"

using namespace websockets;

extern WebsocketsClient wsClient;
extern esp_timer_handle_t capture_timer;
extern double timeOffset;

// Network and WebSocket communication APIs
bool connectToWiFi();
void connectToWebSocket();
void sendHelloMessage();
void sendImage(camera_fb_t *fb);
void sendImageMetadata(int capturedImageSize);
void sendStatus();
void eventListener();