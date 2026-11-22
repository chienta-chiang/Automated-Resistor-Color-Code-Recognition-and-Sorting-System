// resistor_sorter.ino
// Arduino (Mega) firmware of the Automated Resistor Color-Code Recognition and Sorting System.
//
// Receives one text command per line at 9600 baud from the Python vision program (or typed by
// hand in the Arduino IDE Serial Monitor, line ending "Newline" or "Both NL & CR"):
//
//   <ohms>         e.g. 4700, 75000      -> sort into the bin assigned to that value
//   MOTOR_ADJUST                         -> wiggle the platform fan (M4) to re-seat the resistor
//   NONE (or any value not in the table) -> sort into the "unknown" bin
//
// Pin map, speeds, angles and the 26-value + unknown table live in stepper_control.h.
//
// Sorting sequence:
//   1. Rotate the storage layers to the target angles. Layers above the target stay on their
//      0 deg pass-through hole, so the resistor falls through them by gravity.
//   2. Sweep the platform fan (M4) to push the recognised resistor down and feed the next one.
//   3. Rotate every layer back by the same steps (open-loop return by opposite commanded steps).

#include <Stepper.h>
#include "stepper_control.h"

Stepper stepper1(STEPS_PER_REV, M1_PINS);  // layer 1 (top)
Stepper stepper2(STEPS_PER_REV, M2_PINS);  // layer 2
Stepper stepper3(STEPS_PER_REV, M3_PINS);  // layer 3 (bottom)
Stepper fanStepper(STEPS_PER_REV, M4_PINS);  // platform fan

void setup() {
  stepper1.setSpeed(STORAGE_SPEED_RPM);
  stepper2.setSpeed(STORAGE_SPEED_RPM);
  stepper3.setSpeed(STORAGE_SPEED_RPM);
  fanStepper.setSpeed(FAN_SPEED_RPM);

  Serial.begin(SERIAL_BAUD);
  Serial.println(F("Resistor sorter ready. Send an ohm value (e.g. 4700), MOTOR_ADJUST or NONE."));
}

// Rotate the three storage layers by the given angles (negative = back toward home).
void moveLayers(int angle1, int angle2, int angle3) {
  stepper1.step(degToSteps(angle1));
  stepper2.step(degToSteps(angle2));
  stepper3.step(degToSteps(angle3));
  Serial.println(F("Layer rotation done"));
  delay(1000);
}

// Sweep the fan: push the resistor down and bring the next one under the camera.
void pushWithFan() {
  fanStepper.step(degToSteps(FAN_PUSH_CW_DEG));
  delay(100);
  fanStepper.step(degToSteps(FAN_PUSH_CCW_DEG));
  Serial.println(F("Fan push done"));
  delay(1000);
}

// MOTOR_ADJUST: nominal -20, +30, -10 degrees; integer conversion gives net +1 step.
void adjustWithFan() {
  fanStepper.step(degToSteps(FAN_ADJUST_1_DEG));
  delay(1000);
  fanStepper.step(degToSteps(FAN_ADJUST_2_DEG));
  delay(1000);
  fanStepper.step(degToSteps(FAN_ADJUST_3_DEG));
  Serial.println(F("MOTOR_ADJUST done"));
}

void sortResistor(const String &command) {
  const SortEntry *entry = findEntry(command);
  if (entry == &UNKNOWN_ENTRY) {
    Serial.println(F("Value not in table -> unknown bin"));
  } else {
    Serial.print(F("Sorting "));
    Serial.print(entry->value);
    Serial.print(F(" ohm -> layer "));
    Serial.print(entry->layer);
    Serial.print(F(", "));
    Serial.print(entry->angle);
    Serial.println(F(" deg"));
  }

  // Only the target layer leaves 0 deg; the layers above stay on their pass-through hole.
  int angle1 = PASS_THROUGH_ANGLE, angle2 = PASS_THROUGH_ANGLE, angle3 = PASS_THROUGH_ANGLE;
  if (entry->layer == 1) angle1 = entry->angle;
  else if (entry->layer == 2) angle2 = entry->angle;
  else angle3 = entry->angle;

  moveLayers(angle1, angle2, angle3);        // 1. align the target slot under the drop path
  pushWithFan();                             // 2. drop the resistor
  moveLayers(-angle1, -angle2, -angle3);     // 3. return active layer to 0 deg pass-through position
  Serial.println(F("Homing done"));
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();  // tolerate "\r" from Serial Monitor
    if (command.length() == 0) return;

    if (command == CMD_ADJUST) {
      adjustWithFan();
    } else {
      sortResistor(command);  // includes "NONE" -> unknown bin
    }
  }
}
