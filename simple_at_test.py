import serial
import time
import sys

print("=========================================")
print("Testing Direct AT Response @ 115200 baud")
print("=========================================")

for port in ['COM3', 'COM4', 'COM5', 'COM6']:
    print(f"\n--- Testing {port} @ 115200 baud ---")
    try:
        with serial.Serial(port, 115200, timeout=1.5) as ser:
            print(f"Successfully opened {port}!")
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            # Pulse AT commands
            ser.write(b"AT\r\n")
            time.sleep(0.15)
            ser.write(b"AT\r\n")
            time.sleep(0.5)
            
            resp = ser.read_all()
            print(f"Raw Bytes ({len(resp)} bytes): {resp}")
            if b"OK" in resp or b"ERROR" in resp or b"AT" in resp:
                print(f"*** FOUND MATCH ON {port}! ***")
            
    except Exception as e:
        print(f"ERROR: Could not open {port} -> {e}")

print("\n=========================================")
