#pragma once

#include "arduino_secrets.h"
#include <Arduino.h>
#include <stdio.h>
#include <stdarg.h>

// Enable or disable debug prints globally
#define DEBUG true


// Print with newline if DEBUG enabled
template<typename T>
inline void debugPrintln(const T& message) {
  if (DEBUG) {
    Serial.println(message);
  }
}

// Print without newline if DEBUG enabled
template<typename T>
inline void debugPrint(const T& message) {
  if (DEBUG) {
    Serial.print(message);
  }
}

// Printf-style debug function
inline void debugPrintf(const char* format, ...) {
  if (!DEBUG) return;

  char buffer[256];
  va_list args;
  va_start(args, format);
  vsnprintf(buffer, sizeof(buffer), format, args);
  va_end(args);

  Serial.print(buffer);
}
