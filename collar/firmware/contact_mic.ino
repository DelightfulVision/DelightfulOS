/*
 * DelightfulOS Collar v2 — Contact Mic + PDM Mic + Sensor Fusion
 * Target: Seeed Studio XIAO ESP32-S3 Sense
 *
 * Sensors:
 *   - Piezo contact mic on throat (pre-speech, speech, swallowing, tap)
 *   - Built-in PDM MEMS mic (air-coupled speech capture)
 *   - Depth sensor / 3D camera — handled separately via USB/SPI
 *
 * Wiring:
 *   Piezo contact mic → bias circuit → A0 (ADC1)
 *     Bias: 1M resistor to 1.65V divider, 100nF coupling cap
 *   Haptic motors → D2/D3/D4/D5 via MOSFET drivers (2N7000 or similar)
 *   Built-in PDM mic on GPIO42 (CLK) / GPIO41 (DATA) — no wiring needed
 *
 * Communication:
 *   WiFi WebSocket → server for AI mediation
 *   Sends pre-processed events OR raw audio chunks (piezo + PDM)
 *
 * WiFi config:
 *   On first boot (or if saved network fails), send config over Serial:
 *     WIFI:ssid:password
 *     SERVER:host:port
 *     USER:user_id
 *   Config is saved to NVS (persists across reboots).
 */

#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include <base64.h>
#include <driver/i2s.h>

// === NVS CONFIG (persisted) ===
Preferences prefs;
String wifiSSID;
String wifiPass;
String serverHost;
int serverPort = 8000;
String userID = "user_a";
bool rawMode = false;

// === PINS ===
const int PIEZO_PIN = A0;
const int HAPTIC_FRONT = D2;
const int HAPTIC_LEFT  = D3;
const int HAPTIC_RIGHT = D4;
const int HAPTIC_BACK  = D5;
const int LED_PIN = LED_BUILTIN;

// === PDM MIC (XIAO ESP32-S3 Sense built-in) ===
#define I2S_PORT    I2S_NUM_0
#define I2S_WS      GPIO_NUM_42  // PDM CLK
#define I2S_DIN     GPIO_NUM_41  // PDM DATA
#define PDM_SAMPLE_RATE  16000
#define PDM_BUFFER_SIZE  512     // samples per read

// === PIEZO SAMPLING ===
const int PIEZO_SAMPLE_RATE = 4000;
const int PIEZO_BUFFER_SIZE = 256;
const int ANALYSIS_INTERVAL_MS = 100;
const int SEND_INTERVAL_MS = 200;
const int HEARTBEAT_INTERVAL_MS = 5000;

// === THRESHOLDS ===
float speechOnsetThreshold = 0.15;
float preSpeechThreshold = 0.05;
float tapDeltaThreshold = 0.10;  // ~410 ADC counts above baseline peak
const int TAP_DEBOUNCE_MS = 300;

// === STATE ===
WebSocketsClient ws;
bool wsConnected = false;

// Piezo state
int16_t piezoBuffer[PIEZO_BUFFER_SIZE];
int piezoIdx = 0;
float currentEnvelope = 0;
float envelopeHistory[50];
int envIdx = 0;
bool preSpeechDetected = false;
bool speechActive = false;
unsigned long lastTapMs = 0;

// PDM mic state
int16_t pdmBuffer[PDM_BUFFER_SIZE];
bool pdmReady = false;

// Haptic state (non-blocking)
struct HapticPulse {
    int pin;
    int pwm;
    unsigned long startMs;
    unsigned long durationMs;
    bool active;
};
HapticPulse hapticSlots[4] = {{0,0,0,0,false},{0,0,0,0,false},{0,0,0,0,false},{0,0,0,0,false}};

// Timing
unsigned long lastAnalysisMs = 0;
unsigned long lastSendMs = 0;
unsigned long lastHeartbeatMs = 0;

// Calibration
bool calibrating = false;
float calibrationSum = 0;
int calibrationCount = 0;
const int CALIBRATION_SAMPLES = 50; // ~5 seconds at 100ms intervals

// Baseline — adaptive exponential moving average of RMS
// EMA adapts to slow drift (temperature, sweat, fit changes) but
// freezes during active events so spikes don't pollute the floor.
float baselineRMS = 0.0;
bool baselineReady = false;
bool bootCalibrating = true;
float bootRMSSum = 0;
int bootCalCount = 0;
const int BOOT_CAL_SAMPLES = 20;       // ~2 seconds at 100ms
const float BASELINE_EMA_ALPHA = 0.02; // slow adaptation (~5s time constant)

// Peak envelope follower (fast attack, slow release)
// Smooths out single-sample ADC noise while still catching transients.
// Attack: instant (follows peak up). Release: exponential decay.
float peakEnvelope = 0.0;
const float ENVELOPE_RELEASE = 0.85;   // decay per frame (~150ms to half)

// Tap state machine: IDLE -> SCAN -> (confirm drop) -> FIRED
//   IDLE:  waiting for envelope to cross threshold
//   SCAN:  peak crossed threshold, scanning for true peak (1-4 frames)
//   Then:  confirm signal drops back to baseline (transient shape)
// Rejects: sustained pressure (speech, head movement), single-sample noise
enum TapState { TAP_IDLE, TAP_SCAN, TAP_CONFIRM_DROP };
TapState tapState = TAP_IDLE;
int tapFrameCount = 0;
float tapSpikePeak = 0;
float tapSpikeZCR = 0;            // zero-crossing rate for shape check
float tapSpikeRMSMax = 0;         // max RMS seen during spike (cough rejection)
const int TAP_SCAN_FRAMES = 2;    // scan window: find true peak (200ms)
const int TAP_MAX_DROP_FRAMES = 3; // must drop back within 300ms after scan
const int TAP_MASK_MS = 400;       // post-tap mask: ignore piezo ringing

// ============================================================
// SIGNAL PROCESSING
// ============================================================

float computeRMS(int16_t* buffer, int size, float scale) {
    float sum = 0;
    for (int i = 0; i < size; i++) {
        float val = (float)buffer[i] / scale;
        sum += val * val;
    }
    return sqrt(sum / size);
}

float computePeak(int16_t* buffer, int size, float scale) {
    float peak = 0;
    for (int i = 0; i < size; i++) {
        float val = abs((float)buffer[i] / scale);
        if (val > peak) peak = val;
    }
    return peak;
}

float computeZCR(int16_t* buffer, int size) {
    // Zero-crossing rate: taps have broadband energy (high ZCR),
    // speech has harmonic structure (lower ZCR).
    int crossings = 0;
    int midpoint = 2048; // 12-bit ADC mid-rail
    for (int i = 1; i < size; i++) {
        if ((buffer[i] >= midpoint) != (buffer[i-1] >= midpoint)) crossings++;
    }
    return (float)crossings / (float)size;
}

bool detectPreSpeech() {
    if (speechActive) return false;
    if (currentEnvelope > preSpeechThreshold && currentEnvelope < speechOnsetThreshold) {
        if (envIdx >= 5) {
            int idx = (envIdx - 3 + 50) % 50;
            float recent = (envelopeHistory[(envIdx - 1 + 50) % 50] +
                           envelopeHistory[(envIdx - 2 + 50) % 50]) / 2.0;
            float older = (envelopeHistory[idx] +
                          envelopeHistory[(idx - 1 + 50) % 50]) / 2.0;
            return recent > older * 1.5;
        }
    }
    return false;
}

bool detectTap() {
    if (!baselineReady) return false;

    // Reject during active speech
    if (speechActive) {
        tapState = TAP_IDLE;
        return false;
    }

    // Post-tap mask: ignore piezo ringing after a confirmed tap
    unsigned long now = millis();
    if (now - lastTapMs < (unsigned long)TAP_MASK_MS) {
        tapState = TAP_IDLE;
        return false;
    }

    float peak = computePeak(piezoBuffer, PIEZO_BUFFER_SIZE, 4095.0);
    float zcr = computeZCR(piezoBuffer, PIEZO_BUFFER_SIZE);

    // Update envelope follower: fast attack, slow release
    if (peak > peakEnvelope) {
        peakEnvelope = peak;                              // instant attack
    } else {
        peakEnvelope = peakEnvelope * ENVELOPE_RELEASE;   // slow release
    }

    // Use max(peak, envelope) for threshold: raw peak catches sustained
    // signals the envelope might dip below, envelope catches transients.
    float effective = max(peak, peakEnvelope);
    float delta = effective - baselineRMS;
    bool aboveThreshold = delta > tapDeltaThreshold;

    switch (tapState) {
        case TAP_IDLE:
            if (aboveThreshold) {
                // Threshold crossed — open scan window to find true peak
                tapState = TAP_SCAN;
                tapFrameCount = 1;
                tapSpikePeak = peak;
                tapSpikeZCR = zcr;
                tapSpikeRMSMax = currentEnvelope;
            }
            break;

        case TAP_SCAN:
            // Scan window: accumulate true peak over a few frames
            tapFrameCount++;
            if (peak > tapSpikePeak) {
                tapSpikePeak = peak;
                tapSpikeZCR = zcr;
            }
            if (currentEnvelope > tapSpikeRMSMax) tapSpikeRMSMax = currentEnvelope;
            if (tapFrameCount >= TAP_SCAN_FRAMES) {
                // Scan done — now wait for signal to drop back
                tapState = TAP_CONFIRM_DROP;
                tapFrameCount = 0;
            }
            break;

        case TAP_CONFIRM_DROP:
            tapFrameCount++;
            if (currentEnvelope > tapSpikeRMSMax) tapSpikeRMSMax = currentEnvelope;
            if (!aboveThreshold) {
                // Peak dropped back. Check if spike had elevated RMS
                // (vocalization) vs brief peak transient (tap).
                // Tap: only a few samples spike, buffer RMS stays near baseline.
                // Cough: entire buffer is elevated, RMS jumps way above baseline.
                float rmsDelta = tapSpikeRMSMax - baselineRMS;
                if (rmsDelta < tapDeltaThreshold * 0.8) {
                    // RMS near baseline throughout — confirmed tap
                    tapState = TAP_IDLE;
                    lastTapMs = now;
                    float confidence = min(1.0f, (tapSpikePeak - baselineRMS) / (tapDeltaThreshold * 2));
                    Serial.printf("[TAP] peak=%.4f base=%.4f delta=%.4f zcr=%.3f conf=%.2f\n",
                        tapSpikePeak, baselineRMS, tapSpikePeak - baselineRMS, tapSpikeZCR, confidence);
                    return true;
                } else {
                    // RMS was elevated during spike — vocalization, not a tap
                    tapState = TAP_IDLE;
                    Serial.printf("[TAP] rejected: spike RMS %.4f >> base %.4f (cough/voice)\n",
                        tapSpikeRMSMax, baselineRMS);
                }
            }
            if (tapFrameCount > TAP_MAX_DROP_FRAMES) {
                // Still above threshold — sustained, not a tap
                tapState = TAP_IDLE;
                Serial.printf("[TAP] rejected: sustained %d frames, peak=%.4f\n",
                    TAP_SCAN_FRAMES + tapFrameCount, tapSpikePeak);
            }
            break;
    }
    return false;
}

// ============================================================
// HAPTIC ENGINE (non-blocking)
// ============================================================

void startHaptic(int pin, float intensity, unsigned long durationMs) {
    int pwm = (int)(constrain(intensity, 0.0, 1.0) * 255);
    // Find a free slot or reuse the one for this pin
    for (int i = 0; i < 4; i++) {
        if (!hapticSlots[i].active || hapticSlots[i].pin == pin) {
            hapticSlots[i].pin = pin;
            hapticSlots[i].pwm = pwm;
            hapticSlots[i].startMs = millis();
            hapticSlots[i].durationMs = durationMs;
            hapticSlots[i].active = true;
            analogWrite(pin, pwm);
            return;
        }
    }
}

void updateHaptics() {
    unsigned long now = millis();
    for (int i = 0; i < 4; i++) {
        if (hapticSlots[i].active && (now - hapticSlots[i].startMs >= hapticSlots[i].durationMs)) {
            analogWrite(hapticSlots[i].pin, 0);
            hapticSlots[i].active = false;
        }
    }
}

int hapticPinFromDirection(const char* dir) {
    if (!dir) return HAPTIC_FRONT;
    if (strcmp(dir, "left") == 0)  return HAPTIC_LEFT;
    if (strcmp(dir, "right") == 0) return HAPTIC_RIGHT;
    if (strcmp(dir, "back") == 0)  return HAPTIC_BACK;
    return HAPTIC_FRONT;
}

// ============================================================
// PDM MICROPHONE
// ============================================================

void setupPDM() {
    i2s_config_t i2s_config = {
        .mode = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX | I2S_MODE_PDM),
        .sample_rate = PDM_SAMPLE_RATE,
        .bits_per_sample = I2S_BITS_PER_SAMPLE_16BIT,
        .channel_format = I2S_CHANNEL_FMT_ONLY_LEFT,
        .communication_format = I2S_COMM_FORMAT_STAND_I2S,
        .intr_alloc_flags = ESP_INTR_FLAG_LEVEL1,
        .dma_buf_count = 4,
        .dma_buf_len = PDM_BUFFER_SIZE,
        .use_apll = false,
        .tx_desc_auto_clear = false,
        .fixed_mclk = 0,
    };

    i2s_pin_config_t pin_config = {
        .bck_io_num = I2S_PIN_NO_CHANGE,
        .ws_io_num = I2S_WS,
        .data_out_num = I2S_PIN_NO_CHANGE,
        .data_in_num = I2S_DIN,
    };

    i2s_driver_install(I2S_PORT, &i2s_config, 0, NULL);
    i2s_set_pin(I2S_PORT, &pin_config);
    i2s_set_clk(I2S_PORT, PDM_SAMPLE_RATE, I2S_BITS_PER_SAMPLE_16BIT, I2S_CHANNEL_MONO);
    Serial.println("[MIC] PDM mic initialized");
}

bool readPDM() {
    size_t bytesRead = 0;
    esp_err_t result = i2s_read(I2S_PORT, pdmBuffer, sizeof(pdmBuffer), &bytesRead, 0);
    if (result == ESP_OK && bytesRead > 0) {
        pdmReady = true;
        return true;
    }
    return false;
}

// ============================================================
// BASE64 ENCODING
// ============================================================

String encodeAudioBase64(int16_t* buffer, int numSamples, int bitDepth) {
    int byteLen = numSamples * 2;
    uint8_t* bytes = (uint8_t*)malloc(byteLen);
    if (!bytes) return "";

    for (int i = 0; i < numSamples; i++) {
        if (bitDepth == 12) {
            // Pack 12-bit as 16-bit LE (high nibble zeroed)
            bytes[i * 2]     = buffer[i] & 0xFF;
            bytes[i * 2 + 1] = (buffer[i] >> 8) & 0x0F;
        } else {
            // 16-bit LE
            bytes[i * 2]     = buffer[i] & 0xFF;
            bytes[i * 2 + 1] = (buffer[i] >> 8) & 0xFF;
        }
    }

    String encoded = base64::encode(bytes, byteLen);
    free(bytes);
    return encoded;
}

// ============================================================
// WEBSOCKET
// ============================================================

void wsEvent(WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {
        case WStype_DISCONNECTED:
            wsConnected = false;
            Serial.println("[WS] Disconnected");
            digitalWrite(LED_PIN, LOW);
            break;

        case WStype_CONNECTED:
            wsConnected = true;
            Serial.println("[WS] Connected");
            digitalWrite(LED_PIN, HIGH);
            break;

        case WStype_TEXT: {
            JsonDocument doc;
            DeserializationError err = deserializeJson(doc, payload, length);
            if (err) break;

            const char* action = doc["action"];
            if (!action) break;

            // Haptic action (non-blocking)
            if (strcmp(action, "haptic") == 0) {
                JsonObject haptic = doc["payload"];
                if (haptic) {
                    const char* dir = haptic["direction"];
                    float intensity = haptic["intensity"] | 0.5f;
                    int durationMs = haptic["duration_ms"] | 250;
                    const char* pattern = haptic["pattern"];

                    int pin = hapticPinFromDirection(dir);

                    if (pattern && strcmp(pattern, "slow_pulse") == 0) {
                        // Slow pulse: 3 gentle pulses
                        startHaptic(pin, intensity * 0.6, 200);
                        // Subsequent pulses handled by scheduling (simplified: just one longer pulse)
                        startHaptic(pin, intensity * 0.4, 600);
                    } else if (pattern && strcmp(pattern, "double_tap") == 0) {
                        startHaptic(pin, intensity, 100);
                        // Second tap will need a timer; simplified: single longer pulse
                        startHaptic(pin, intensity, 250);
                    } else {
                        startHaptic(pin, intensity, durationMs);
                    }
                }
            }
            // Calibration command
            else if (strcmp(action, "calibrate") == 0) {
                calibrating = true;
                calibrationSum = 0;
                calibrationCount = 0;
                Serial.println("[CAL] Starting calibration...");
            }
            // Config update
            else if (strcmp(action, "config") == 0) {
                JsonObject payload_obj = doc["payload"];
                if (payload_obj.containsKey("speech_threshold")) {
                    speechOnsetThreshold = payload_obj["speech_threshold"];
                    Serial.printf("[CFG] speech_threshold=%.3f\n", speechOnsetThreshold);
                }
                if (payload_obj.containsKey("pre_speech_threshold")) {
                    preSpeechThreshold = payload_obj["pre_speech_threshold"];
                    Serial.printf("[CFG] pre_speech_threshold=%.3f\n", preSpeechThreshold);
                }
                if (payload_obj.containsKey("tap_delta_threshold")) {
                    tapDeltaThreshold = payload_obj["tap_delta_threshold"];
                    Serial.printf("[CFG] tap_delta_threshold=%.3f\n", tapDeltaThreshold);
                }
            }
            break;
        }
    }
}

void sendEvent(const char* eventType, float confidence) {
    if (!wsConnected) return;
    JsonDocument doc;
    doc["type"] = "events";
    doc["timestamp"] = millis() / 1000.0;
    JsonArray events = doc["events"].to<JsonArray>();
    JsonObject evt = events.add<JsonObject>();
    evt["type"] = eventType;
    evt["confidence"] = confidence;

    String output;
    serializeJson(doc, output);
    ws.sendTXT(output);
    Serial.printf("[TX] %s (%.2f)\n", eventType, confidence);
}

void sendHeartbeat() {
    if (!wsConnected) return;
    JsonDocument doc;
    doc["type"] = "heartbeat";
    doc["timestamp"] = millis() / 1000.0;
    doc["uptime_s"] = millis() / 1000;
    doc["wifi_rssi"] = WiFi.RSSI();
    doc["piezo_rms"] = currentEnvelope;
    doc["speech_active"] = speechActive;
    doc["free_heap"] = ESP.getFreeHeap();

    String output;
    serializeJson(doc, output);
    ws.sendTXT(output);
}

void sendRawAudio() {
    if (!wsConnected) return;
    JsonDocument doc;
    doc["type"] = "raw_audio";
    doc["timestamp"] = millis() / 1000.0;

    // Piezo audio (12-bit, 4kHz)
    doc["piezo_sample_rate"] = PIEZO_SAMPLE_RATE;
    doc["piezo_bit_depth"] = 12;
    doc["audio"] = encodeAudioBase64(piezoBuffer, PIEZO_BUFFER_SIZE, 12);

    // PDM mic audio (16-bit, 16kHz) — if available
    if (pdmReady) {
        doc["pdm_sample_rate"] = PDM_SAMPLE_RATE;
        doc["pdm_bit_depth"] = 16;
        doc["pdm_audio"] = encodeAudioBase64(pdmBuffer, PDM_BUFFER_SIZE, 16);
        pdmReady = false;
    }

    // Also include any edge-detected events alongside raw
    JsonArray events = doc["events"].to<JsonArray>();
    if (detectTap()) {
        JsonObject evt = events.add<JsonObject>();
        evt["type"] = "touch";
        evt["confidence"] = 1.0;
    }

    String output;
    serializeJson(doc, output);
    ws.sendTXT(output);
}

// ============================================================
// SERIAL CONFIG
// ============================================================

void loadConfig() {
    prefs.begin("collar", false);
    wifiSSID   = prefs.getString("ssid", "");
    wifiPass   = prefs.getString("pass", "");
    serverHost = prefs.getString("host", "192.168.1.100");
    serverPort = prefs.getInt("port", 8000);
    userID     = prefs.getString("user", "user_a");
    rawMode    = prefs.getBool("raw", false);
    prefs.end();
}

void saveConfig() {
    prefs.begin("collar", false);
    prefs.putString("ssid", wifiSSID);
    prefs.putString("pass", wifiPass);
    prefs.putString("host", serverHost);
    prefs.putInt("port", serverPort);
    prefs.putString("user", userID);
    prefs.putBool("raw", rawMode);
    prefs.end();
    Serial.println("[CFG] Saved to NVS");
}

void processSerialConfig(String line) {
    line.trim();
    if (line.startsWith("WIFI:")) {
        // Format: WIFI:ssid:password
        int firstColon = 5;
        int secondColon = line.indexOf(':', firstColon);
        if (secondColon > firstColon) {
            wifiSSID = line.substring(firstColon, secondColon);
            wifiPass = line.substring(secondColon + 1);
            saveConfig();
            Serial.printf("[CFG] WiFi: %s\n", wifiSSID.c_str());
            Serial.println("[CFG] Reboot to apply (or send REBOOT)");
        }
    }
    else if (line.startsWith("SERVER:")) {
        // Format: SERVER:host:port
        int firstColon = 7;
        int secondColon = line.indexOf(':', firstColon);
        if (secondColon > firstColon) {
            serverHost = line.substring(firstColon, secondColon);
            serverPort = line.substring(secondColon + 1).toInt();
            saveConfig();
            Serial.printf("[CFG] Server: %s:%d\n", serverHost.c_str(), serverPort);
        }
    }
    else if (line.startsWith("USER:")) {
        userID = line.substring(5);
        saveConfig();
        Serial.printf("[CFG] User: %s\n", userID.c_str());
    }
    else if (line.startsWith("RAW:")) {
        rawMode = line.substring(4) == "1" || line.substring(4) == "true";
        saveConfig();
        Serial.printf("[CFG] Raw mode: %s\n", rawMode ? "ON" : "OFF");
    }
    else if (line == "STATUS") {
        Serial.println("=== DelightfulOS Collar Status ===");
        Serial.printf("  WiFi SSID: %s\n", wifiSSID.c_str());
        Serial.printf("  WiFi Connected: %s (RSSI: %d)\n", WiFi.isConnected() ? "YES" : "NO", WiFi.RSSI());
        Serial.printf("  IP: %s\n", WiFi.localIP().toString().c_str());
        Serial.printf("  Server: %s:%d\n", serverHost.c_str(), serverPort);
        Serial.printf("  User: %s\n", userID.c_str());
        Serial.printf("  WS Connected: %s\n", wsConnected ? "YES" : "NO");
        Serial.printf("  Raw Mode: %s\n", rawMode ? "ON" : "OFF");
        Serial.printf("  Piezo RMS: %.4f\n", currentEnvelope);
        Serial.printf("  Baseline RMS: %.4f (%s)\n", baselineRMS, baselineReady ? "ready" : "calibrating");
        Serial.printf("  Tap Delta Threshold: %.3f\n", tapDeltaThreshold);
        Serial.printf("  Speech Threshold: %.3f\n", speechOnsetThreshold);
        Serial.printf("  Free Heap: %d\n", ESP.getFreeHeap());
        Serial.printf("  Uptime: %lus\n", millis() / 1000);
    }
    else if (line == "REBOOT") {
        Serial.println("[SYS] Rebooting...");
        delay(100);
        ESP.restart();
    }
    else if (line == "HELP") {
        Serial.println("Commands:");
        Serial.println("  WIFI:ssid:password  — Set WiFi credentials");
        Serial.println("  SERVER:host:port    — Set server address");
        Serial.println("  USER:user_id        — Set user ID");
        Serial.println("  RAW:1 / RAW:0       — Toggle raw audio mode");
        Serial.println("  STATUS              — Show current status");
        Serial.println("  REBOOT              — Restart collar");
        Serial.println("  HELP                — This message");
    }
}

// ============================================================
// WIFI
// ============================================================

bool connectWiFi(int timeoutMs) {
    if (wifiSSID.length() == 0) {
        Serial.println("[WiFi] No SSID configured. Send WIFI:ssid:password over Serial.");
        return false;
    }

    Serial.printf("[WiFi] Connecting to %s", wifiSSID.c_str());
    WiFi.begin(wifiSSID.c_str(), wifiPass.c_str());

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED && (millis() - start) < (unsigned long)timeoutMs) {
        delay(500);
        Serial.print(".");
        // Check for serial config while waiting
        if (Serial.available()) {
            String line = Serial.readStringUntil('\n');
            processSerialConfig(line);
        }
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] Connected! IP: %s RSSI: %d\n",
            WiFi.localIP().toString().c_str(), WiFi.RSSI());
        return true;
    } else {
        Serial.println("\n[WiFi] FAILED — check credentials (send WIFI:ssid:pass)");
        return false;
    }
}

// ============================================================
// SETUP
// ============================================================

void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n=== DelightfulOS Collar v2 ===");
    Serial.println("Send HELP for commands\n");

    // Load saved config from NVS
    loadConfig();

    // GPIO
    analogReadResolution(12);
    pinMode(PIEZO_PIN, INPUT);
    pinMode(HAPTIC_FRONT, OUTPUT);
    pinMode(HAPTIC_LEFT, OUTPUT);
    pinMode(HAPTIC_RIGHT, OUTPUT);
    pinMode(HAPTIC_BACK, OUTPUT);
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    // PDM mic
    setupPDM();

    // Clear buffers
    memset(piezoBuffer, 0, sizeof(piezoBuffer));
    memset(envelopeHistory, 0, sizeof(envelopeHistory));
    memset(pdmBuffer, 0, sizeof(pdmBuffer));

    // WiFi (10 second timeout — accepts serial config during wait)
    if (!connectWiFi(10000)) {
        Serial.println("[SYS] Running without WiFi. Configure via Serial and REBOOT.");
        // Blink LED to indicate no WiFi
        for (int i = 0; i < 5; i++) {
            digitalWrite(LED_PIN, HIGH); delay(100);
            digitalWrite(LED_PIN, LOW); delay(100);
        }
        return;
    }

    // WebSocket
    String path = rawMode
        ? String("/collar/ws/") + userID + "/raw"
        : String("/collar/ws/") + userID;
    ws.begin(serverHost.c_str(), serverPort, path.c_str());
    ws.onEvent(wsEvent);
    ws.setReconnectInterval(3000);

    Serial.printf("[WS] Connecting to ws://%s:%d%s\n",
        serverHost.c_str(), serverPort, path.c_str());
}

// ============================================================
// LOOP
// ============================================================

void loop() {
    // Check serial for config commands
    if (Serial.available()) {
        String line = Serial.readStringUntil('\n');
        processSerialConfig(line);
    }

    ws.loop();
    updateHaptics();

    // Read PDM mic (non-blocking)
    readPDM();

    // Sample piezo at target rate
    static unsigned long lastSampleUs = 0;
    unsigned long nowUs = micros();
    if (nowUs - lastSampleUs >= (1000000 / PIEZO_SAMPLE_RATE)) {
        lastSampleUs = nowUs;
        piezoBuffer[piezoIdx] = analogRead(PIEZO_PIN);
        piezoIdx = (piezoIdx + 1) % PIEZO_BUFFER_SIZE;
    }

    unsigned long now = millis();

    // Analysis (every 100ms)
    if (now - lastAnalysisMs >= ANALYSIS_INTERVAL_MS) {
        lastAnalysisMs = now;
        currentEnvelope = computeRMS(piezoBuffer, PIEZO_BUFFER_SIZE, 4095.0);
        envelopeHistory[envIdx] = currentEnvelope;
        envIdx = (envIdx + 1) % 50;

        speechActive = currentEnvelope >= speechOnsetThreshold;
        if (!preSpeechDetected) preSpeechDetected = detectPreSpeech();
        if (speechActive) preSpeechDetected = false;

        // Boot auto-calibration: average RMS over first N quiet samples
        if (bootCalibrating) {
            bootRMSSum += currentEnvelope;
            bootCalCount++;
            if (bootCalCount >= BOOT_CAL_SAMPLES) {
                baselineRMS = bootRMSSum / bootCalCount;
                baselineReady = true;
                bootCalibrating = false;
                Serial.printf("[BOOT-CAL] baselineRMS=%.4f (~%d ADC) tapDelta=%.3f\n",
                    baselineRMS, (int)(baselineRMS * 4095), tapDeltaThreshold);
            }
        }

        // Explicit calibration: collect baseline noise floor (more samples, more accurate)
        if (calibrating) {
            calibrationSum += currentEnvelope;
            calibrationCount++;
            if (calibrationCount >= CALIBRATION_SAMPLES) {
                float baseline = calibrationSum / calibrationCount;
                baselineRMS = baseline;
                baselineReady = true;
                // Set thresholds relative to baseline
                preSpeechThreshold = baseline * 3.0;
                speechOnsetThreshold = baseline * 8.0;
                calibrating = false;
                Serial.printf("[CAL] Done! baselineRMS=%.4f pre=%.4f speech=%.4f tapDelta=%.3f\n",
                    baselineRMS, preSpeechThreshold, speechOnsetThreshold, tapDeltaThreshold);
                // Report to server
                if (wsConnected) {
                    JsonDocument doc;
                    doc["type"] = "calibration";
                    doc["baseline"] = baseline;
                    doc["baseline_rms"] = baselineRMS;
                    doc["pre_speech_threshold"] = preSpeechThreshold;
                    doc["speech_threshold"] = speechOnsetThreshold;
                    doc["tap_delta_threshold"] = tapDeltaThreshold;
                    String output;
                    serializeJson(doc, output);
                    ws.sendTXT(output);
                }
            }
        }

        // Adaptive baseline: slowly track drift when signal is quiet.
        // Freeze during speech, taps, or any active event so spikes
        // don't pull the baseline up and desensitize detection.
        if (baselineReady && !bootCalibrating && !calibrating) {
            float peak = computePeak(piezoBuffer, PIEZO_BUFFER_SIZE, 4095.0);
            bool quiet = !speechActive && (peak - baselineRMS) < tapDeltaThreshold * 0.5;
            if (quiet) {
                baselineRMS = baselineRMS * (1.0 - BASELINE_EMA_ALPHA) + currentEnvelope * BASELINE_EMA_ALPHA;
            }
        }
    }

    // Send data (every 200ms)
    if (now - lastSendMs >= SEND_INTERVAL_MS) {
        lastSendMs = now;

        if (rawMode) {
            sendRawAudio();
        } else {
            if (detectTap()) {
                sendEvent("touch", 1.0);
            }
            if (preSpeechDetected && !speechActive) {
                sendEvent("about_to_speak", min(1.0f, currentEnvelope / speechOnsetThreshold));
            }
            if (speechActive) {
                sendEvent("speaking", min(1.0f, currentEnvelope));
            }
        }
    }

    // Heartbeat (every 5s)
    if (now - lastHeartbeatMs >= HEARTBEAT_INTERVAL_MS) {
        lastHeartbeatMs = now;
        sendHeartbeat();
    }
}
