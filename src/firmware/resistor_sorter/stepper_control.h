// stepper_control.h
// Pin map, motion constants and the resistance -> bin lookup table of the resistor sorter.
//
// Mechanics (see docs/hardware_and_bom.md):
//   M1, M2, M3 : the three stacked, rotating storage discs (layer 1 = top, layer 3 = bottom)
//   M4         : fan / paddle on the recognition platform (pushes the resistor down, feeds the next one)
//
// Each layer has 10 slots, 36 degrees apart. Slot 0 (0 deg) is an OPEN pass-through hole:
// every layer rests at 0 deg, so a resistor dropped onto the top layer falls straight through
// all of the layers above its target. To sort into layer N, only layer N is rotated to the
// target slot; the layers above it stay on their 0 deg pass-through hole. After the push, all
// layers are commanded back by opposite steps (open-loop return, not sensor homing).
//
// Do not change the numeric values below without re-testing on hardware.
#ifndef STEPPER_CONTROL_H
#define STEPPER_CONTROL_H

#include <Arduino.h>
#include <Stepper.h>

// ---------------------------------------------------------------- serial protocol
#define SERIAL_BAUD 9600  // must match serial_bridge.py (BAUDRATE)
#define CMD_ADJUST "MOTOR_ADJUST"
#define CMD_NONE "NONE"

// ---------------------------------------------------------------- motors
#define STEPS_PER_REV 2048  // steps per output revolution for the 28BYJ-48 stepper motor

// Stepper(STEPS, IN1, IN3, IN2, IN4) - coil order as wired in the prototype (Arduino Mega pins)
#define M1_PINS 22, 26, 24, 28  // layer 1 (top storage disc)
#define M2_PINS 34, 38, 36, 40  // layer 2
#define M3_PINS 46, 50, 48, 52  // layer 3 (bottom)
#define M4_PINS 31, 35, 33, 37  // platform fan

#define STORAGE_SPEED_RPM 12
#define FAN_SPEED_RPM 6

// ---------------------------------------------------------------- angles (degrees)
#define SLOT_ANGLE 36            // 360 / 10 slots
#define PASS_THROUGH_ANGLE 0     // slot 0: open hole, rest position of every layer

#define FAN_PUSH_CW_DEG 46       // sweep forward: pushes the resistor off / feeds the next one
#define FAN_PUSH_CCW_DEG -10     // small return
#define FAN_ADJUST_1_DEG -20     // nominal -20, +30, -10; net +1 step after integer truncation
#define FAN_ADJUST_2_DEG 30
#define FAN_ADJUST_3_DEG -10

// ---------------------------------------------------------------- bin table
// 26 values + unknown. layer: 1..3, angle: target slot angle of that layer.
struct SortEntry {
  const char *value;  // resistance in ohms, exactly as sent by Python
  uint8_t layer;      // 1..3
  int16_t angle;      // degrees
};

const SortEntry SORT_TABLE[] = {
  // ---- layer 1 (8 values; slot 324 deg is the "unknown" bin, see UNKNOWN_ENTRY)
  {"12", 1, 36},     {"5600", 1, 72},   {"24000", 1, 108}, {"300", 1, 144},
  {"75000", 1, 180}, {"15", 1, 216},    {"56000", 1, 252}, {"4700", 1, 288},
  // ---- layer 2 (9 values)
  {"6200000", 2, 36}, {"9600", 2, 72},   {"4700000", 2, 108}, {"510", 2, 144},
  {"7300", 2, 180},   {"750", 2, 216},   {"2800", 2, 252},    {"560", 2, 288},
  {"3300000", 2, 324},
  // ---- layer 3 (9 values)
  {"3900", 3, 36},    {"1000", 3, 72},   {"240000", 3, 108},  {"720000", 3, 144},
  {"360000", 3, 180}, {"2200000", 3, 216}, {"820", 3, 252},   {"16000", 3, 288},
  {"420", 3, 324},
};
const uint8_t SORT_TABLE_SIZE = sizeof(SORT_TABLE) / sizeof(SORT_TABLE[0]);

// Anything not in the table (including "NONE") goes here.
const SortEntry UNKNOWN_ENTRY = {"unknown", 1, 324};

// ---------------------------------------------------------------- helpers
// Look up a command string; returns &UNKNOWN_ENTRY when it is not one of the 26 values.
inline const SortEntry *findEntry(const String &command) {
  for (uint8_t i = 0; i < SORT_TABLE_SIZE; i++) {
    if (command.equals(SORT_TABLE[i].value)) return &SORT_TABLE[i];
  }
  return &UNKNOWN_ENTRY;
}

// Degrees -> steps with integer map(); truncates toward zero and is symmetric for +/-.
inline long degToSteps(int angle) { return map(angle, 0, 360, 0, STEPS_PER_REV); }

#endif  // STEPPER_CONTROL_H
