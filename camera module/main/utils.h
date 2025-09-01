#pragma once

#include <Arduino.h>

// Returns a string representing the ESP32-CAM board type
String getBoardType();

// Returns the MAC address of the device as a string (e.g., "D8:79:A9:A0:ED:30")
String getMacAddress();