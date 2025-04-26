// === camera_handler.h ===
#pragma once

#include <Arduino.h>
#include "esp_camera.h"
#include "camera_pins.h"
#include "network_handler.h"
#include "testing.h"

// === Capture Timing ===
extern double captureStartedTime;
extern double captureCompletedTime;
extern double imageSentTime;
extern double captureRequestReceivedTime;

// --- Start Camera ---
inline bool startCamera() {
  camera_config_t config = getCameraConfig();

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x", err);
    return 0;
  }
  Serial.println("Camera init successful!!");
  return 1;
}

inline void triggerCapture() {
  Serial.println("Capturing...");
  captureStartedTime = getAccurateTime();

  digitalWrite(LED_GPIO_NUM, HIGH);
  delay(100);
  digitalWrite(LED_GPIO_NUM, LOW);

  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Failed to capture image.");
    return;
  }

  captureCompletedTime = getAccurateTime();

  Serial.printf("Image captured: %d bytes\n", fb->len);

  int capturedImageSize = fb->len;   // 📸 Save now, before freeing fb!

  // --- Send image ---
  bool success = wsClient.sendBinary((const char *)fb->buf, fb->len);

  esp_camera_fb_return(fb);  // 🔥 After we're done with fb

  if (success) {
    Serial.println("✅ Image sent successfully!");
    imageSentTime = getAccurateTime();
  } else {
    Serial.println("❌ Failed to send image.");
    imageSentTime = getAccurateTime();
  }

  // --- Build metadata JSON ---
  StaticJsonDocument<512> doc;
  doc["type"] = "capture_metadata";
  doc["device_id"] = SECRET_DEVICE_NAME;

  JsonObject times = doc.createNestedObject("times");
  times["capture_request_received"] = captureRequestReceivedTime;
  times["capture_started"] = captureStartedTime;
  times["capture_completed"] = captureCompletedTime;
  times["image_sent"] = imageSentTime;

  doc["rssi"] = WiFi.RSSI();
  doc["resolution"] = getCameraConfig().frame_size;
  doc["jpeg_quality"] = getCameraConfig().jpeg_quality;
  doc["image_size"] = capturedImageSize;   // 📸 use the saved size

  String json;
  serializeJson(doc, json);

  wsClient.send(json);
}