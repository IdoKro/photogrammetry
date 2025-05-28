#pragma once

#include "arduino_secrets.h"
#include <Arduino.h>
#include <stdio.h>
#include <stdarg.h>

// This module includes debugging functions to be executed only if in debug mode
#define DEBUG true


// Debug print
template<typename T>
inline void debugPrintln(const T& message) {
  if (DEBUG) {
    Serial.println(message);
  }
}

// Debug print without newline
template<typename T>
inline void debugPrint(const T& message) {
  if (DEBUG) {
    Serial.print(message);
  }
}

// printf-style debug output
inline void debugPrintf(const char* format, ...) {
  if (!DEBUG) return;

  char buffer[256];
  va_list args;
  va_start(args, format);
  vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);

  Serial.print(buffer);
}
