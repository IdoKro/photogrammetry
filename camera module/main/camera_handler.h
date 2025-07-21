#pragma once

#include "esp_camera.h"

// Initializes the camera hardware
bool startCamera();

// Captures and sends a frame over the network
void triggerCapture();