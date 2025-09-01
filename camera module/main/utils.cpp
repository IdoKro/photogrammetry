#include "utils.h"
#include <WiFi.h>
#include "arduino_secrets.h"  // Needed if board is defined there

String getBoardType() {
  #if defined(CAMERA_MODEL_WROVER_KIT)
      return "WROVER_KIT";
  #elif defined(CAMERA_MODEL_AI_THINKER)
      return "AI_THINKER";
  #elif defined(CAMERA_MODEL_ESP32S3_EYE)
      return "ESP32S3_EYE";
  #else
      return "UNKNOWN";
  #endif
}

String getMacAddress() {
  uint64_t chipid = ESP.getEfuseMac();  // 48-bit MAC
  char macStr[18];
  snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X",
           (uint8_t)(chipid >> 40), (uint8_t)(chipid >> 32),
           (uint8_t)(chipid >> 24), (uint8_t)(chipid >> 16),
           (uint8_t)(chipid >> 8), (uint8_t)(chipid));
  return String(macStr);
}
