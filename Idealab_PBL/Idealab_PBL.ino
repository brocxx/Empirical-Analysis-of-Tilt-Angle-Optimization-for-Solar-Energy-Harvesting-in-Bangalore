#include <Wire.h>
#include <Adafruit_INA219.h>
#include <BH1750.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

// CRITICAL FIX: DS18B20 Data pin is connected to Digital Pin 2
#define ONE_WIRE_BUS 2

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature tempSensor(&oneWire);
Adafruit_INA219 ina219;
BH1750 lightMeter;
Adafruit_MPU6050 mpu;

void setup() {
  // High-speed baud rate for smooth data transmission
  Serial.begin(115200);
  Wire.begin();

  Serial.println("Initializing sensors...");

  // 1. Initialize INA219 (Power Monitor)
  if (ina219.begin()) {
    ina219.setCalibration_32V_2A();
    Serial.println("INA219 OK");
  } else {
    Serial.println("INA219 FAILED - Check I2C wiring");
  }

  // 2. Initialize BH1750 (Lux Sensor)
  if (lightMeter.begin()) {
    Serial.println("BH1750 OK");
  } else {
    Serial.println("BH1750 FAILED - Check I2C wiring");
  }

  // 3. Initialize DS18B20 (Temperature)
  tempSensor.begin();
  Serial.print("DS18B20 devices found: ");
  Serial.println(tempSensor.getDeviceCount());

  // 4. Initialize MPU6050 (Angle Sensor)
  if (mpu.begin()) {
    mpu.setAccelerometerRange(MPU6050_RANGE_2_G);
    mpu.setFilterBandwidth(MPU6050_BAND_21_HZ);
    Serial.println("MPU6050 OK");
  } else {
    Serial.println("MPU6050 FAILED - Check I2C wiring");
  }

  Serial.println("------------------------");
}

void loop() {
  // --- DATA ACQUISITION ---
  
  // 1. Read Power Telemetry
  float voltage_V  = ina219.getBusVoltage_V();
  float current_mA = ina219.getCurrent_mA();
  float power_mW   = ina219.getPower_mW();

  // 2. Read Ambient Light
  float lux = lightMeter.readLightLevel();

  // 3. Read Panel Temperature
  tempSensor.requestTemperatures();
  float tempC = tempSensor.getTempCByIndex(0);

  // 4. Read Acceleration and Compute Tilt Angle
  sensors_event_t a, g, t;
  mpu.getEvent(&a, &g, &t);
  float tiltAngle = abs(atan2(a.acceleration.y, a.acceleration.z) * 180.0 / M_PI);

  // --- DATA TRANSMISSION ---
  
  Serial.print("Voltage (V): ");     Serial.println(voltage_V);
  Serial.print("Current (mA): ");    Serial.println(current_mA);
  Serial.print("Power (mW): ");      Serial.println(power_mW);
  Serial.print("Lux: ");             Serial.println(lux);
  Serial.print("Temperature (C): "); Serial.println(tempC);
  Serial.print("Tilt (deg): ");      Serial.println(tiltAngle);
  Serial.println("------------------------");

  // Wait 1 second before the next reading
  delay(1000);
}