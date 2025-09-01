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
extern double timeOffset;  // defined in main.ino

// ===== Tunables =====
static const unsigned long WIFI_BOOT_TIMEOUT_MS = 10000; // 10s → reboot if can't connect at boot
static const unsigned long WS_RETRY_BACKOFF_MS  = 4000;  // try WS connect every 4s when needed

WebsocketsClient wsClient;

// connection state
static volatile bool s_wsConnected = false;
static volatile bool s_wifiUp      = false;
static unsigned long s_lastWsAttemptMs = 0;

bool isWebSocketConnected() { return s_wsConnected; }

// ---------- Wi-Fi ----------

bool connectToWiFi() {
  debugPrintln("Connecting to WiFi...");
  WiFi.mode(WIFI_STA);
  WiFi.persistent(false);
  WiFi.setAutoReconnect(true);

  // one-time Wi-Fi event install (optional; we still poll status in loop)
  static bool eventsInstalled = false;
  if (!eventsInstalled) {
    eventsInstalled = true;
    WiFi.onEvent([](WiFiEvent_t event, WiFiEventInfo_t){
      if (event == WIFI_EVENT_STA_DISCONNECTED) {
        s_wifiUp = false;
        if (s_wsConnected) {                // close WS only if it was connected
          debugPrintln("[WS] Closing because Wi-Fi dropped");
          wsClient.close();
        }
        s_wsConnected = false;
      }
    });
  }

  WiFi.disconnect(true);
  delay(100);
  WiFi.begin(SECRET_SSID, SECRET_PASS);

  const unsigned long t0 = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - t0) < WIFI_BOOT_TIMEOUT_MS) {
    delay(250);
    debugPrint(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    s_wifiUp = true;
    debugPrintln("\nWiFi connected!");
    debugPrint("IP address: ");  debugPrintln(WiFi.localIP());
    debugPrint("WiFi RSSI: ");   debugPrintln(WiFi.RSSI());
    return true;
  } else {
    s_wifiUp = false;
    debugPrintln("\nWiFi connection failed after 10s. Rebooting...");
    delay(200);
    ESP.restart();
    return false; // not reached
  }
}

// ---------- Common JSON helpers ----------

void addCommonMetadata(JsonDocument& doc) {
  doc["device_id"] = SECRET_DEVICE_NAME;
  doc["mac"] = getMacAddress();
  doc["firmware_version"] = OTA_FIRMWARE_VERSION;
  doc["board_type"] = getBoardType();
}

void sendHelloMessage() {
  StaticJsonDocument<200> doc;
  doc["type"] = "hello";
  addCommonMetadata(doc);
  String payload;
  serializeJson(doc, payload);
  wsClient.send(payload);
}

void sendImage(camera_fb_t *fb) {
  bool success = wsClient.sendBinary((const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  if (success) debugPrintln("Image sent successfully!\n");
  else         debugPrintln("Failed to send image.");
}

void sendImageMetadata(int capturedImageSize) {
  StaticJsonDocument<512> doc;
  doc["type"] = "capture_metadata";
  addCommonMetadata(doc);
  doc["rssi"] = WiFi.RSSI();
  doc["resolution"] = getCameraConfig().frame_size;
  doc["jpeg_quality"] = getCameraConfig().jpeg_quality;
  doc["image_size"] = capturedImageSize;
  String json; serializeJson(doc, json);
  wsClient.send(json);
}

void sendStatus() {
  StaticJsonDocument<512> doc;
  doc["type"] = "status";
  addCommonMetadata(doc);
  doc["rssi"] = WiFi.RSSI();
  String json; serializeJson(doc, json);
  wsClient.send(json);
}

// ---------- WebSocket ----------

void connectToWebSocket() {
  if (WiFi.status() != WL_CONNECTED) {
    s_wifiUp = false;
    debugPrintln("[WS] Skip connect: Wi-Fi not up");
    return;
  }
  s_wifiUp = true;

  // Bind lifecycle + message handlers ONCE
  static bool handlersBound = false;
  if (!handlersBound) {
    handlersBound = true;

    wsClient.onEvent([](WebsocketsEvent event, String){
      if (event == WebsocketsEvent::ConnectionOpened) {
        s_wsConnected = true;
        debugPrintln("WebSocket connected.");
        sendHelloMessage();
      } else if (event == WebsocketsEvent::ConnectionClosed) {
        if (s_wsConnected) debugPrintln("WebSocket disconnected.");
        s_wsConnected = false;
      }
    });

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
        double localTime  = millis() / 1000.0;
        timeOffset = serverTime - localTime;
      }
      else if (type == "capture") {
        double targetTime = doc["time"];
        double now        = millis() / 1000.0 + timeOffset;
        double delaySec   = targetTime - now;

        if (delaySec <= 0) {
          debugPrintln("Target time passed, capturing immediately.");
          triggerCapture();
          return;
        }

        unsigned long delayMs = (unsigned long)(delaySec * 1000);
        debugPrint("\nScheduling capture in "); debugPrint(delayMs); debugPrintln(" ms");

        esp_timer_stop(capture_timer);
        esp_timer_start_once(capture_timer, delayMs * 1000);
      }
      else if (type == "status") {
        sendStatus();
      }
    });
  }

  const String url = String("ws://") + SECRET_SERVER_IP + ":8765";
  debugPrint("[WS] Connecting to "); debugPrintln(url);
  if (wsClient.connect(url)) {
    debugPrintln("WebSocket connection successful.");
  } else {
    debugPrintln("WebSocket connection failed.");
  }
}

// ---------- Keepalive / Reconnect loop ----------

void networkLoop() {
  // Always pump the client
  wsClient.poll();

  // Track Wi-Fi status each iteration (portable across core versions)
  s_wifiUp = (WiFi.status() == WL_CONNECTED);

  // If Wi-Fi dropped while WS connected, close WS once (prevents half-open)
  if (!s_wifiUp && s_wsConnected) {
    debugPrintln("[WS] Wi-Fi down → closing WS");
    wsClient.close();
    s_wsConnected = false;
  }

  // If Wi-Fi is up but WS isn't, attempt reconnect with backoff
  if (s_wifiUp && !s_wsConnected) {
    const unsigned long now = millis();
    if (now - s_lastWsAttemptMs >= WS_RETRY_BACKOFF_MS) {
      s_lastWsAttemptMs = now;
      connectToWebSocket();  // single attempt
    }
  }
}
