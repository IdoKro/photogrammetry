#include <WiFi.h>
#include <HTTPClient.h>
#include <Update.h>
#include "debug.h"
#include "arduino_secrets.h"  // for OTA_URL, OTA_VERSION_URL, OTA_FIRMWARE_VERSION
#include "utils.h"

String boardType = getBoardType();
String otaBaseURL = String("http://") + SECRET_SERVER_IP + ":" + OTA_PORT + "/" + boardType;
String versionURL = otaBaseURL + "/version.txt";
String firmwareURL = otaBaseURL + "/firmware/" + boardType + "_" + OTA_FIRMWARE_VERSION + ".bin";

void performOTAUpdate() {
  debugPrintln("Starting OTA firmware download...");

  WiFiClient client;
  HTTPClient http;
  debugPrintln("Connecting to: " + firmwareURL);
  http.begin(client, firmwareURL);
  http.addHeader("Authorization", String("Bearer ") + OTA_AUTH_TOKEN);
  int httpCode = http.GET();

  debugPrintln("HTTP GET (firmware) returned: " + String(httpCode));

  if (httpCode == 200) {
    int contentLength = http.getSize();
    debugPrintln("Firmware content length: " + String(contentLength));

    if (contentLength <= 0) {
      debugPrintln("Invalid content length.");
      return;
    }

    if (!Update.begin(contentLength)) {
      debugPrintln("Update.begin() failed with error: " + String(Update.getError()));
      return;
    }

    debugPrintln("Starting to write firmware stream...");
    size_t written = Update.writeStream(http.getStream());

    debugPrintln("Bytes written: " + String(written));

    if (written == contentLength) {
      debugPrintln("Firmware written successfully.");
    } else {
      debugPrintln("Incomplete write: " + String(written) + "/" + String(contentLength));
    }

    if (Update.end()) {
      debugPrintln("Update finished!");
      if (Update.isFinished()) {
        debugPrintln("Restarting ESP...");
        ESP.restart();
      } else {
        debugPrintln("Update not fully completed.");
      }
    } else {
      debugPrintln("Update.end() failed. Error: " + String(Update.getError()));
    }
  } else {
    debugPrintln("Firmware download failed. HTTP code: " + String(httpCode));
  }

  http.end();
}


void checkForOTAUpdate() {
  HTTPClient http;
  http.begin(versionURL);
  http.addHeader("Authorization", String("Bearer ") + OTA_AUTH_TOKEN);
  int httpCode = http.GET();

  if (httpCode == 200) {
    String newVersion = http.getString();
    newVersion.trim();

    if (newVersion != OTA_FIRMWARE_VERSION) {
      debugPrintln("New firmware version available. Starting OTA...");
      firmwareURL = otaBaseURL + "/firmware/" + boardType + "_" + newVersion + ".bin";
      performOTAUpdate();
    } else {
      // debugPrintln("Firmware is up to date.");
    }
  } else {
    // debugPrintln("Failed to check version file. HTTP code: " + String(httpCode));
  }
  http.end();
}