#pragma once
#include "esp_camera.h"
#include "debug.h"
#include "arduino_secrets.h"

// Define pin mappings for different ESP32-CAM models
#if defined(CAMERA_MODEL_WROVER_KIT)
  #define PWDN_GPIO_NUM  -1
  #define RESET_GPIO_NUM -1
  #define XCLK_GPIO_NUM  21
  #define SIOD_GPIO_NUM  26
  #define SIOC_GPIO_NUM  27

  #define Y9_GPIO_NUM    35
  #define Y8_GPIO_NUM    34
  #define Y7_GPIO_NUM    39
  #define Y6_GPIO_NUM    36
  #define Y5_GPIO_NUM    19
  #define Y4_GPIO_NUM    18
  #define Y3_GPIO_NUM    5
  #define Y2_GPIO_NUM    4
  #define VSYNC_GPIO_NUM 25
  #define HREF_GPIO_NUM  23
  #define PCLK_GPIO_NUM  22

#elif defined(CAMERA_MODEL_AI_THINKER)
  #define PWDN_GPIO_NUM  32
  #define RESET_GPIO_NUM -1
  #define XCLK_GPIO_NUM  0
  #define SIOD_GPIO_NUM  26
  #define SIOC_GPIO_NUM  27

  #define Y9_GPIO_NUM    35
  #define Y8_GPIO_NUM    34
  #define Y7_GPIO_NUM    39
  #define Y6_GPIO_NUM    36
  #define Y5_GPIO_NUM    21
  #define Y4_GPIO_NUM    19
  #define Y3_GPIO_NUM    18
  #define Y2_GPIO_NUM    5
  #define VSYNC_GPIO_NUM 25
  #define HREF_GPIO_NUM  23
  #define PCLK_GPIO_NUM  22

#elif defined(CAMERA_MODEL_ESP32S3_EYE)
  #define PWDN_GPIO_NUM -1
  #define RESET_GPIO_NUM -1
  #define XCLK_GPIO_NUM 15
  #define SIOD_GPIO_NUM 4
  #define SIOC_GPIO_NUM 5

  #define Y2_GPIO_NUM 11
  #define Y3_GPIO_NUM 9
  #define Y4_GPIO_NUM 8
  #define Y5_GPIO_NUM 10
  #define Y6_GPIO_NUM 12
  #define Y7_GPIO_NUM 18
  #define Y8_GPIO_NUM 17
  #define Y9_GPIO_NUM 16

  #define VSYNC_GPIO_NUM 6
  #define HREF_GPIO_NUM 7
  #define PCLK_GPIO_NUM 13

#else
  #error "Camera model not selected"
#endif

// Use GPIO 4 for onboard flash LED; replace with 33 for standard LED
#define LED_GPIO_NUM   4

// Returns a pre-filled configuration struct for the ESP32 camera module
camera_config_t getCameraConfig();