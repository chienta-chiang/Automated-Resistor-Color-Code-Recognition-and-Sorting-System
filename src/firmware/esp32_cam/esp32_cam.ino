// esp32_cam.ino
// ESP32-CAM firmware: press the button on GPIO12 -> capture a JPEG -> HTTP multipart POST to the PC.
//
// Optics: a +40 diopter convex lens is fixed in front of the (fixed-focus) camera lens so that
// small resistors can be imaged at close range under the fixed lighting platform.
//
// Setup: copy arduino_secrets.h.example to arduino_secrets.h and fill in Wi-Fi / server values.
// The receiver is src/vision/upload_server.py, or any endpoint accepting the same multipart POST (e.g. XAMPP + PHP).
// Board: "AI Thinker ESP32-CAM" in the Arduino IDE.

#include <WiFi.h>
#include "esp_camera.h"
#include "Arduino.h"
#include <HTTPClient.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "arduino_secrets.h"  // not committed: see arduino_secrets.h.example

const char *ssid = SECRET_WIFI_SSID;
const char *password = SECRET_WIFI_PASSWORD;
#define SERVER SECRET_SERVER_HOST
#define PORT SECRET_SERVER_PORT
#define UPLOAD_URL SECRET_UPLOAD_PATH

#define BUTTON_PIN 12  // capture button, wired to GND, INPUT_PULLUP

camera_fb_t *fb = nullptr;
bool uploadSuccess = false;

// Optional manual sensor tuning helper (disabled by default; camera uses auto-exposure/AWB).
void adjustCameraSettings() {
  sensor_t *s = esp_camera_sensor_get();
  if (s != nullptr) {
    s->set_brightness(s, 2);  // -2 to 2
    s->set_contrast(s, 0);    // -2 to 2
    s->set_saturation(s, 0);  // -2 to 2
    s->set_whitebal(s, 0);    // auto white balance off
    s->set_awb_gain(s, 0);    // AWB gain off
    s->set_wb_mode(s, 1);     // 1 = sunny preset
    s->set_vflip(s, 1);       // flip image vertically
  }
}

// AI-Thinker ESP32-CAM pin map.
bool initCamera() {
  camera_config_t camera_config = {
    .pin_pwdn = 32,
    .pin_reset = -1,
    .pin_xclk = 0,
    .pin_sscb_sda = 26,
    .pin_sscb_scl = 27,
    .pin_d7 = 35,
    .pin_d6 = 34,
    .pin_d5 = 39,
    .pin_d4 = 36,
    .pin_d3 = 21,
    .pin_d2 = 19,
    .pin_d1 = 18,
    .pin_d0 = 5,
    .pin_vsync = 25,
    .pin_href = 23,
    .pin_pclk = 22,
    .xclk_freq_hz = 20000000,
    .ledc_timer = LEDC_TIMER_0,
    .ledc_channel = LEDC_CHANNEL_0,
    .pixel_format = PIXFORMAT_JPEG,
    .frame_size = FRAMESIZE_SVGA,  // 800x600
    .jpeg_quality = 12,            // 0-63, lower = better quality / larger file
    .fb_count = 1
  };

  esp_err_t err = esp_camera_init(&camera_config);
  if (err != ESP_OK) {
    Serial.printf("Camera initialization failed with error 0x%x\n", err);
    return false;
  }
  Serial.println("Camera initialized successfully");
  return true;
}

// Grab and immediately release one frame so the next capture is fresh (flushes the stale buffer).
void capturedImage() {
  fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Failed to get image");
    delay(1000);
    ESP.restart();
  } else {
    Serial.println("Image captured successfully");
  }
  esp_camera_fb_return(fb);
  fb = nullptr;
}

// Capture a frame and POST it as multipart/form-data (field "image", file name "photo.jpg").
void uploadImage() {
  camera_fb_t *fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("Failed to get image");
    delay(1000);
    ESP.restart();
  }

  HTTPClient http;
  String url = "http://" + String(SERVER) + ":" + String(PORT) + UPLOAD_URL;
  http.begin(url);

  String boundary = "ESP32CAM";
  http.addHeader("Content-Type", "multipart/form-data; boundary=" + boundary);

  String body = "--" + boundary + "\r\n";
  body += "Content-Disposition: form-data; name=\"image\"; filename=\"photo.jpg\"\r\n";
  body += "Content-Type: image/jpeg\r\n\r\n";
  body += String((char *)fb->buf, fb->len) + "\r\n";
  body += "--" + boundary + "--\r\n";

  int httpResponseCode = http.POST(body);

  if (httpResponseCode >= 200 && httpResponseCode < 300) {
    String response = http.getString();
    if (!uploadSuccess) {  // print only on the first success
      Serial.println("Upload successful");
      Serial.println("Server response: " + response);
      uploadSuccess = true;
    }
  } else {
    Serial.println("Upload failed");
    String response = http.getString();
    Serial.println("Server response: " + response);
    uploadSuccess = false;
  }

  http.end();
  esp_camera_fb_return(fb);
}

void setup() {
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);  // disable brownout detector
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.println("\nConnecting to Wi-Fi...");
  while (WiFi.status() != WL_CONNECTED) {
    delay(1500);
    Serial.print(".");
  }
  Serial.print("\nIP address: ");
  Serial.println(WiFi.localIP());

  if (!initCamera()) {
    Serial.println("Camera init failed, restarting");
    ESP.restart();
  }
  // Manual sensor overrides in adjustCameraSettings() are left disabled by default.

  pinMode(BUTTON_PIN, INPUT_PULLUP);
  Serial.println("Ready. Press the button to capture.");
}

void loop() {
  static bool buttonPressed = false;
  static unsigned long lastDebounceTime = 0;
  static const unsigned long debounceDelay = 50;  // ms

  int buttonState = digitalRead(BUTTON_PIN);

  if ((millis() - lastDebounceTime) > debounceDelay) {
    if (buttonState == LOW && !buttonPressed) {
      buttonPressed = true;
      lastDebounceTime = millis();
      Serial.println("Button pressed");
      delay(500);
      capturedImage();
      uploadImage();

      delay(500);
      Serial.println("Waiting for next press...");
    } else if (buttonState == HIGH && buttonPressed) {
      buttonPressed = false;
      lastDebounceTime = millis();
    }
  }
}
