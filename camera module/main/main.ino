#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include <ArduinoJson.h>
#include "esp_timer.h"
#include "esp_camera.h"
#include "camera_pins.h"
#include "arduino_secrets.h"

using namespace websockets;

// Globals
WebsocketsClient wsClient;
esp_timer_handle_t capture_timer;
double timeOffset = 0;  // in seconds
unsigned long lastWsReconnectAttempt = 0;
const unsigned long WS_RECONNECT_INTERVAL = 5000;


void safe_reset(){
  Serial.println("🔄 Restarting device...");
  delay(100);  // Allow time for message to flush
  ESP.restart();
}

// --- Connect to WiFi ---
bool connectToWiFi() {
  Serial.println("⏳ Connecting to WiFi...");
  WiFi.disconnect(true);   // Forget old connection
  delay(100);              // Allow Wi-Fi hardware to reset
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

// --- Start Camera ---
bool startCamera() {
  camera_config_t config = getCameraConfig();

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return 0;
  }
  Serial.println("Camera init successful!!");
  return 1;
}

// --- Connect to WebSocket ---
void connectToWebSocket() {
  wsClient.onEvent([](WebsocketsEvent event, String data) {
    if (event == WebsocketsEvent::ConnectionOpened) {
      Serial.println("WebSocket connected.");
    } else if (event == WebsocketsEvent::ConnectionClosed) {
      Serial.println("WebSocket disconnected.");
    }
    //  else if (event == WebsocketsEvent::GotPing) {
    //   Serial.println("Ping received.");
    // }
  });

  subscribeToWebSocketEvents();
  bool connected = wsClient.connect(String("ws://") + SECRET_SERVER_IP + ":8765");

  if (connected) {
    Serial.println("WebSocket connection successful.");
  } else {
    Serial.println("WebSocket connection failed.");
  }
}

// --- Subscribe to Messages ---
void subscribeToWebSocketEvents() {
  wsClient.onMessage([](WebsocketsMessage message) {
    String data = message.data();
    // Serial.println("Message received: " + data);

    StaticJsonDocument<200> doc;
    DeserializationError error = deserializeJson(doc, data);
    if (error) {
      Serial.print("JSON parse failed: ");
      Serial.println(error.c_str());
      return;
    }

    String type = doc["type"];

    if (type == "sync") {
      double serverTime = doc["time"];
      double localTime = millis() / 1000.0;
      timeOffset = serverTime - localTime;

      Serial.print("⏱️ Synced time offset: ");
      Serial.print(timeOffset, 6);
      Serial.println(" sec");

    } else if (type == "capture") {
      double targetTime = doc["time"];
      double now = millis() / 1000.0 + timeOffset;
      double delaySec = targetTime - now;

      if (delaySec <= 0) {
        Serial.println("⚠️ Target time already passed, capturing immediately.");
        triggerCapture();
        return;
      }

      unsigned long delayMs = (unsigned long)(delaySec * 1000);
      Serial.print("📸 Scheduling capture in ");
      Serial.print(delayMs);
      Serial.println(" ms");

      esp_timer_stop(capture_timer);  // safe: stop if already running
      esp_timer_start_once(capture_timer, delayMs * 1000); // convert ms to μs

    }
  });
}

// --- Trigger Capture ---
void triggerCapture() {
  Serial.println("Capturing...");

  // ⚡ Flash the LED
  digitalWrite(LED_GPIO_NUM, HIGH);  // Turn on
  delay(100);                        // Keep it on for 100ms
  digitalWrite(LED_GPIO_NUM, LOW);   // Turn off

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Failed to capture image.");
    return;
  }

  Serial.printf("Image captured: %d bytes\n", fb->len);
  // TODO: upload image

  esp_camera_fb_return(fb);
}

void setup() {

  pinMode(LED_GPIO_NUM, OUTPUT);
  digitalWrite(LED_GPIO_NUM, LOW);  // Make sure it's off initially

  Serial.begin(115200);
  delay(500);  // Let USB and peripherals settle
  Serial.println("\n");

  bool connection_status = connectToWiFi();
  if (!connection_status) {
    safe_reset();
  }
  
  bool camera_status = startCamera();

  connectToWebSocket();

  // Prepare timer
  esp_timer_create_args_t timer_args = {
    .callback = [](void*) { triggerCapture(); },
    .name = "capture_timer"
  };
  esp_timer_create(&timer_args, &capture_timer);
}

// --- Loop ---
void loop() {
  wsClient.poll();
  // Check if WebSocket is disconnected and try reconnecting
  if (!wsClient.available()) {
    unsigned long now = millis();
    if (now - lastWsReconnectAttempt >= WS_RECONNECT_INTERVAL) {
      Serial.println("🔄 WebSocket disconnected, trying to reconnect...");
      connectToWebSocket();
      lastWsReconnectAttempt = now;
    }
  }
}
