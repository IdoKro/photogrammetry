#include <WiFi.h>
#include <WebServer.h>
#include "esp_camera.h"
#include "arduino_secrets.h"
#include "camera_pins.h"

WebServer server(80);

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

void handleCapture() {
  Serial.println("Capturing...");
  camera_fb_t* fb = esp_camera_fb_get();

  if (!fb) {
    Serial.println("Camera capture failed");
    server.send(500, "text/plain", "Camera capture failed");
    return;
  }

  Serial.printf("Done. Size: %d bytes\n", fb->len);
  server.send_P(200, "image/jpeg", (const char *)fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

void handleStatus() {
  Serial.println("I'm still listening!");
  server.send(500, "text/plain", "I'm still listening!");
}

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

void safe_reset(){
  Serial.println("🔄 Restarting device...");
  delay(100);  // Allow time for message to flush
  ESP.restart();
}

void setup() {
  Serial.begin(115200);
  delay(500);  // Let USB and peripherals settle
  Serial.println("\n");

  bool connection_status = connectToWiFi();
  if (!connection_status) {
    safe_reset();
  }

  bool camera_status = startCamera();

  server.on("/capture", HTTP_GET, handleCapture);
  server.on("/status", HTTP_GET, handleStatus);
  server.begin();
  Serial.println("HTTP server started");
}

void loop() {
  server.handleClient();
}
