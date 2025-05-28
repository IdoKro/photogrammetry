#include "camera_handler.h"
#include "camera_pins.h"
#include "debug.h"
#include "network_handler.h"

bool startCamera() {
    camera_config_t config = getCameraConfig();
    esp_err_t err = esp_camera_init(&config);
    if (err != ESP_OK) {
        debugPrintf("Camera init failed with error 0x%x", err);
        return false;
    }
    debugPrintln("Camera init successful!!");
    return true;
}

void triggerCapture() {
    debugPrintln("Capturing...");
    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        debugPrintln("Failed to capture image.");
        return;
    }

    int capturedImageSize = fb->len;
    debugPrintf("Image captured: %d bytes\n", capturedImageSize);

    sendImage(fb);
    sendImageMetadata(capturedImageSize);
}
