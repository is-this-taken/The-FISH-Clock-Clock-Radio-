# Animal-Themed Clock Radio (ECE 299)

Firmware for the Raspberry Pi Pico 2 W using MicroPython, controlling an FM radio, OLED display, and configurable alarm.

As per course instruction by P. Drissen, Claude Code was used for integrated development.

## Hardware Summary
* **MCU:** Raspberry Pi Pico 2 W
* **Display:** SSD1309 OLED (SPI)
* **Radio:** RDA5807 FM Module (I2C)
* **Inputs:** Rotary Encoder (with switch), Cycle Button, Alarm/Snooze Button
* **Audio:** PWM-driven buzzer mixed with FM radio output (LM386)

## Features
* **Radio:** Tune via rotary encoder, volume control, and preset support.
* **Clock:** Time tracking with 12/24H format and adjustable time-zone offset display.
* **Alarm:** Configurable alarm time, volume (independent of radio), and tone patterns.
* **UI:** Single-loop architecture for stability; Cycle-based adjustment via rotary encoder.

## Controls
| Input | Action | Function |
| :--- | :--- | :--- |
| **Rotary Encoder** | Rotate | Adjust currently selected Cycle value |
| **Encoder Button** | Short Press | Jump to next FM station preset |
| **Cycle Button** | Short Press | Cycle through adjustable settings |
| **Cycle Button** | Long Press | Arm/Disarm alarm |
| **Alarm Button** | Short Press | Snooze (when ringing) or Mute/Unmute radio |
| **Alarm Button** | Long Press | Stop alarm |

---
*For pinouts and detailed interface definitions, refer to the Project Report.*