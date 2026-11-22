// motor_control.ino - manual stepper jog tool (assembly / calibration helper, NOT the production firmware)
//
// Purpose: move one stepper at a time by a given angle from the Arduino IDE Serial Monitor
// (9600 baud) to check wiring, rotation direction, slot alignment of the storage discs and the
// fan sweep before running resistor_sorter.ino.
//
// Commands (one per line):
//   <motor>,<angle>   motor 1-3 = storage layers 1-3 (M1-M3), 4 = platform fan (M4); angle in degrees,
//                     negative = reverse. Example: "2,36" turns layer 2 by one slot (36 deg).
//   reset             turns every motor one full revolution backwards (relative open-loop move;
//                     align the storage discs manually to 0 deg before running resistor_sorter.ino).
//
// Pin numbers and speeds below intentionally duplicate src/firmware/resistor_sorter/stepper_control.h
// for this standalone utility. The fan runs at 15 RPM here
// (6 RPM in the production firmware) so it is quicker to jog.
#include <Stepper.h>

#define STEPS 2048  // Steps per full revolution.

// Initialize the four stepper motors.
Stepper stepper1(STEPS, 22, 26, 24, 28);
Stepper stepper2(STEPS, 34, 38, 36, 40);
Stepper stepper3(STEPS, 46, 50, 48, 52);
Stepper fanStepper(STEPS, 31, 35, 33, 37);  // Platform fan stepper.

void setup() {
  Serial.begin(9600);  // Start serial communication.
  stepper1.setSpeed(12);
  stepper2.setSpeed(12);
  stepper3.setSpeed(12);
  fanStepper.setSpeed(15);

  Serial.println("Enter motor number (1-4) and relative angle in degrees, e.g. 1,90");
  Serial.println("Enter 'reset' to turn every motor one full revolution backwards");
}

void moveStepper(Stepper& stepper, int angle) {
  int steps = map(angle, 0, 360, 0, STEPS);
  stepper.step(steps);
}

void resetAllSteppers() {
  Serial.println("Turning all motors one full revolution backwards...");
  stepper1.step(-STEPS);
  stepper2.step(-STEPS);
  stepper3.step(-STEPS);
  fanStepper.step(-STEPS);
  Serial.println("Reverse rotation complete.");
}

void loop() {
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');  // Read the command line.
    input.trim();  // Remove leading and trailing whitespace.

    if (input == "reset") {  // Handle the reverse-revolution command.
      resetAllSteppers();
      return;
    }

    int motorNumber = 0;
    int angle = 0;

    // Parse a motor number and relative angle, e.g. "1,90".
    int commaIndex = input.indexOf(',');
    if (commaIndex > 0) {
      motorNumber = input.substring(0, commaIndex).toInt();
      angle = input.substring(commaIndex + 1).toInt();

      if (motorNumber >= 1 && motorNumber <= 4) {
        switch (motorNumber) {
          case 1:
            moveStepper(stepper1, angle);
            break;
          case 2:
            moveStepper(stepper2, angle);
            break;
          case 3:
            moveStepper(stepper3, angle);
            break;
          case 4:
            moveStepper(fanStepper, angle);
            break;
        }
        Serial.print("Motor ");
        Serial.print(motorNumber);
        Serial.print(" moved by degrees: ");
        Serial.println(angle);
      } else {
        Serial.println("Invalid motor number; enter 1-4");
      }
    } else {
      Serial.println("Invalid format; enter motor_number,angle_degrees");
    }
  }
}
