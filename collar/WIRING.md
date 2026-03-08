# DelightfulOS Collar v2 — Wiring Guide

## XIAO ESP32-S3 Sense Pinout

```
                  USB-C
              ┌───────────┐
         D0 ──┤           ├── 5V
         D1 ──┤           ├── GND
         D2 ──┤  XIAO     ├── 3V3
         D3 ──┤  ESP32-S3 ├── D10
         D4 ──┤  Sense    ├── D9
         D5 ──┤           ├── D8
         D6 ──┤           ├── D7
     A0/D0 ──┤           ├──
              └───────────┘
```

## Piezo Contact Mic Circuit

Bare piezo disc on throat → bias circuit → A0

```
                    3.3V
                     │
                    [1M]  ← 1M resistor (bias to mid-rail)
                     │
    Piezo ──[100nF]──┤──── A0 (ADC1, 12-bit)
    disc    coupling │
                    [1M]  ← 1M resistor (bias to mid-rail)
                     │
                    GND
```

- Bare piezo disc ($0.50), NOT Grove vibration sensor (digital only)
- 100nF ceramic coupling cap blocks DC, passes AC vibration signal
- 1M + 1M voltage divider biases to 1.65V (mid-rail for ADC)
- ADC reads 0-4095 (12-bit), centered at ~2048 when silent
- CRITICAL: Use A0 (ADC1) — ADC2 pins conflict with WiFi

## Haptic Motors

4x coin vibration motors (3V, ~100mA each) via N-channel MOSFETs:

```
    3.3V ──── Motor+ ──── Motor- ──── MOSFET Drain
                                        │
    Dx ──[1K]── MOSFET Gate            MOSFET Source ── GND
```

| Direction | Pin | MOSFET |
|-----------|-----|--------|
| Front     | D2  | 2N7000 |
| Left      | D3  | 2N7000 |
| Right     | D4  | 2N7000 |
| Back      | D5  | 2N7000 |

- 2N7000 N-channel MOSFET (or similar logic-level FET)
- 1K gate resistor limits current from ESP32 GPIO
- Flyback diode (1N4148) across motor recommended but optional for hackathon

## PDM Microphone (Built-in)

No wiring needed — the XIAO ESP32-S3 Sense has a built-in PDM MEMS mic.

| Signal | GPIO |
|--------|------|
| CLK    | 42   |
| DATA   | 41   |

- 16kHz sample rate, 16-bit
- Air-coupled: captures actual speech audio (vs piezo which captures throat vibration)
- Used for speech confirmation and future transcription

## Parts List (Hackathon Minimum)

| Part | Qty | Notes |
|------|-----|-------|
| XIAO ESP32-S3 Sense | 1 | Main MCU |
| Bare piezo disc (27mm) | 1 | ~$0.50, throat-mounted |
| 100nF ceramic cap | 1 | Coupling capacitor |
| 1M resistor | 2 | Bias network |
| Coin vibration motor (3V) | 4 | Directional haptics |
| 2N7000 MOSFET | 4 | Motor drivers |
| 1K resistor | 4 | Gate resistors |
| USB-C cable | 1 | Power + programming |

## First Boot

1. Flash `contact_mic.ino` via Arduino IDE
2. Open Serial Monitor at 115200 baud
3. Send: `WIFI:your_ssid:your_password`
4. Send: `SERVER:your_server_ip:8000`
5. Send: `USER:user_a`
6. Send: `REBOOT`
7. LED lights solid = WebSocket connected
8. Send: `STATUS` to verify

Config persists across reboots (saved to NVS flash).
