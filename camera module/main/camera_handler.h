// === camera_handler.h ===
#pragma once

#include <Arduino.h>
#include "esp_camera.h"
#include "camera_pins.h"
#include "network_handler.h"

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

// --- Trigger Capture ---
inline void triggerCapture() {
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