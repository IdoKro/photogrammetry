#pragma once

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include "arduino_secrets.h"

using namespace websockets;

inline WebsocketsClient wsClient;

inline bool connectToWiFi() {
  Serial.println("⏳ Connecting to WiFi...");
  WiFi.disconnect(true);
  delay(100);
  WiFi.begin(SECRET_SSID, SECRET_PASS);

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    Serial.print(".");
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n✅ WiFi connected!");
    Serial.print("📡 IP address: ");
    Serial.println(WiFi.localIP());
    return true;
  } else {
    Serial.println("\n❌ Failed to connect to WiFi.");
    return false;
  }
}

inline void connectToWebSocket() {
  wsClient.onEvent([](WebsocketsEvent event, String data) {
    if (event == WebsocketsEvent::ConnectionOpened) {
      Serial.println("✅ WebSocket connected.");
    } else if (event == WebsocketsEvent::ConnectionClosed) {
      Serial.println("❌ WebSocket disconnected.");
    }
    // else if (event == WebsocketsEvent::GotPing) {
    //   Serial.println("📶 Ping received.");
    // }
  });

  bool connected = wsClient.connect(String("ws://") + SECRET_SERVER_IP + ":8765");
  if (connected) {
    Serial.println("✅ WebSocket connection successful.");
  } else {
    Serial.println("❌ WebSocket connection failed.");
  }
}