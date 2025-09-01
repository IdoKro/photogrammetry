#include "network_handler.h"
#include "camera_handler.h"
#include "arduino_secrets.h"
#include "debug.h"
#include <WiFi.h>
#include <ArduinoJson.h>
#include "esp_timer.h"
#include "esp_camera.h"
#include "camera_pins.h"
#include "utils.h"

using namespace websockets;

extern esp_timer_handle_t capture_timer;
extern double timeOffset;  // We'll define it in main.ino

WebsocketsClient wsClient;

bool connectToWiFi() {
  
  // This function connects the module to the WiFi network. 

  debugPrintln("Connecting to WiFi...");
  WiFi.disconnect(true);
  delay(100);
  WiFi.begin(SECRET_SSID, SECRET_PASS); // WiFi Credentials are stored in arduino_secrets.h

  int retries = 0;
  while (WiFi.status() != WL_CONNECTED && retries < 20) {
    delay(500);
    debugPrint(".");
    retries++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    debugPrintln("\nWiFi connected!");
    debugPrint("IP address: ");
    debugPrintln(WiFi.localIP());
    long rssi = WiFi.RSSI();
    debugPrint("WiFi RSSI: ");
    debugPrintln(rssi);
    return true;
  } else {
    debugPrintln("\nFailed to connect to WiFi.");
    ESP.restart();
    return false;
  }
}

void addCommonMetadata(JsonDocument& doc) {
  doc["device_id"] = SECRET_DEVICE_NAME;
  doc["mac"] = getMacAddress();
  doc["firmware_version"] = OTA_FIRMWARE_VERSION;
  doc["board_type"] = getBoardType();
}

void sendHelloMessage() {
  // Send hello message
  StaticJsonDocument<200> doc;
  doc["type"] = "hello";
  addCommonMetadata(doc);

  
  String payload;
  serializeJson(doc, payload);
  wsClient.send(payload);
}

void sendImage(camera_fb_t *fb) {
  // Send image

  bool success = wsClient.sendBinary((const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);  // After we're done with fb, clear RAM as soon as possible

  if (success) {
    debugPrintln("Image sent successfully!");
  } else {
    debugPrintln("Failed to send image.");
  }
}

void sendImageMetadata(int capturedImageSize) {
  // Send metadata JSON
  StaticJsonDocument<512> doc;
  doc["type"] = "capture_metadata";
  addCommonMetadata(doc);

  doc["rssi"] = WiFi.RSSI();
  
  doc["resolution"] = getCameraConfig().frame_size;
  doc["jpeg_quality"] = getCameraConfig().jpeg_quality;
  doc["image_size"] = capturedImageSize;   // use the saved size

  String json;
  serializeJson(doc, json);

  wsClient.send(json);
}

void sendStatus() {
  // Send status JSON
  StaticJsonDocument<512> doc;
  doc["type"] = "status";
  addCommonMetadata(doc);
  doc["rssi"] = WiFi.RSSI();

  String json;
  serializeJson(doc, json);

  wsClient.send(json);
}

// Initial connection to WebSockets
void connectToWebSocket() {
  wsClient.onEvent([](WebsocketsEvent event, String data) {
    if (event == WebsocketsEvent::ConnectionOpened) {
      debugPrintln("WebSocket connected.");
      sendHelloMessage();
    } else if (event == WebsocketsEvent::ConnectionClosed) {
      debugPrintln("WebSocket disconnected.");
      debugPrint("WiFi RSSI: ");
      debugPrintln(WiFi.RSSI());
    }
  });

  bool connected = wsClient.connect(String("ws://") + SECRET_SERVER_IP + ":8765");
  if (connected) {
    debugPrintln("WebSocket connection successful.");
  } else {
    debugPrintln("WebSocket connection failed.");
  }
}

// Process incoming WebSocket messages from the server
void eventListener() {
  wsClient.onMessage([](WebsocketsMessage message) {
    String data = message.data();

    StaticJsonDocument<200> doc;
    DeserializationError error = deserializeJson(doc, data);
    if (error) {
      debugPrint("JSON parse failed: ");
      debugPrintln(error.c_str());
      return;
    }

    String type = doc["type"];

    if (type == "sync") {
      double serverTime = doc["time"];
      double localTime = millis() / 1000.0;
      timeOffset = serverTime - localTime;
    }
    else if (type == "capture") {

      double targetTime = doc["time"];
      double now = millis() / 1000.0 + timeOffset;
      double delaySec = targetTime - now;

      if (delaySec <= 0) {
        debugPrintln("Target time passed, capturing immediately.");
        triggerCapture();
        return;
      }

      unsigned long delayMs = (unsigned long)(delaySec * 1000);
      debugPrint("Scheduling capture in ");
      debugPrint(delayMs);
      debugPrintln(" ms");

      esp_timer_stop(capture_timer);
      esp_timer_start_once(capture_timer, delayMs * 1000);
    }
    else if (type == "status") {
      sendStatus();
    }
  });
}