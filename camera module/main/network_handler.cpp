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

// ===== Heartbeat =====
static const unsigned long HB_INTERVAL_MS  = 12000; // send PING every 12s
static const unsigned long HB_TIMEOUT_MS   = 3000;  // expect PONG within 3s
static const uint8_t       HB_MAX_MISSES   = 2;     // after 2 misses → reconnect
static const unsigned long SOFT_WD_MS      = 45000; // no RX/PONG for 45s → reconnect

static bool          s_waitingPong    = false;
static uint8_t       s_pongMisses     = 0;
static unsigned long s_lastPingMs     = 0;
static unsigned long s_lastActivityMs = 0; // any RX, PONG, or connect

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
      s_wsConnected   = true;
      s_waitingPong   = false;
      s_pongMisses    = 0;
      s_lastActivityMs= millis();
      debugPrintln("WebSocket connected.");
      sendHelloMessage();
    } else if (event == WebsocketsEvent::ConnectionClosed) {
      if (s_wsConnected) debugPrintln("WebSocket disconnected.");
      s_wsConnected   = false;
      s_waitingPong   = false;
    } else if (event == WebsocketsEvent::GotPong) {
      s_lastActivityMs= millis();
      s_waitingPong   = false;
      s_pongMisses    = 0;
      // debugPrintln("[WS] PONG");
    } else if (event == WebsocketsEvent::GotPing) {
      s_lastActivityMs= millis(); // library auto-replies
    }
  });

    wsClient.onMessage([](WebsocketsMessage message) {
      s_lastActivityMs = millis();
      
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
        double localTime = (double)esp_timer_get_time() / 1e6;
        timeOffset = serverTime - localTime;
      }
      else if (type == "capture") {
        double targetTime = doc["time"];
        double now = (double)esp_timer_get_time() / 1e6 + timeOffset;
        double delaySec   = targetTime - now;
        
        // tiny tolerance
        if (delaySec < 0 && delaySec > -0.010) delaySec = 0;

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
  // Always pump the client first (non-blocking)
  wsClient.poll();

  // Track Wi-Fi status each iteration (portable across core versions)
  s_wifiUp = (WiFi.status() == WL_CONNECTED);

  // If Wi-Fi dropped while WS was connected, close WS once (prevents half-open)
  if (!s_wifiUp && s_wsConnected) {
    debugPrintln("[WS] Wi-Fi down → closing WS");
    wsClient.close();
    s_wsConnected  = false;
    s_waitingPong  = false;
    s_pongMisses   = 0;
    // no return: we’ll wait for Wi-Fi to come back and reconnect below
  }

  // If Wi-Fi is up but WS isn't, attempt reconnect with backoff
  if (s_wifiUp && !s_wsConnected) {
    const unsigned long now = millis();
    if (now - s_lastWsAttemptMs >= WS_RETRY_BACKOFF_MS) {
      s_lastWsAttemptMs = now;
      connectToWebSocket();  // single attempt; no flapping
    }
    // When not connected, reset heartbeat state
    s_waitingPong = false;
    s_pongMisses  = 0;
    return;  // nothing else to do until WS connects
  }

  // ----- At this point, WS is connected (or Wi-Fi is down and we already closed WS) -----
  if (!s_wsConnected) return;

  const unsigned long now = millis();

  // Soft watchdog: no activity (no RX/PONG) for too long → reconnect
  if (s_lastActivityMs && (now - s_lastActivityMs) > SOFT_WD_MS) {
    debugPrintln("[WS] Soft watchdog timeout → reconnect");
    wsClient.close();          // force tear-down; backoff will reopen
    s_wsConnected  = false;
    s_waitingPong  = false;
    s_pongMisses   = 0;
    return;
  }

  // Heartbeat: send PING periodically and expect PONG quickly
  if (!s_waitingPong && (now - s_lastPingMs) >= HB_INTERVAL_MS) {
    if (wsClient.ping()) {
      s_waitingPong = true;
      s_lastPingMs  = now;
      // debugPrintln("[WS] PING");
    } else {
      // Couldn't send ping → connection is dodgy; restart WS
      debugPrintln("[WS] ping() failed → reconnect");
      wsClient.close();
      s_wsConnected  = false;
      s_waitingPong  = false;
      s_pongMisses   = 0;
      return;
    }
  }

  // If awaiting PONG, enforce timeout and count misses
  if (s_waitingPong && (now - s_lastPingMs) >= HB_TIMEOUT_MS) {
    s_waitingPong = false;   // allow next ping
    if (++s_pongMisses >= HB_MAX_MISSES) {
      debugPrintln("[WS] PONG timeout (max misses) → reconnect");
      wsClient.close();
      s_wsConnected  = false;
      s_pongMisses   = 0;
      return;
    }
  }
}
