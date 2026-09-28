import serial
import time

print("==================================================")
print("Quectel BC660K Direct Board Validation Script")
print("Connecting to COM3 @ 115200 baud...")
print("==================================================\n")

try:
    with serial.Serial("COM3", 115200, timeout=2.0) as ser:
        print("Connected to COM3!\n")

        commands = [
            ("AT", "Ping Check"),
            ("ATI", "Module Information"),
            ("AT+GMR", "Firmware Revision"),
            ("AT+CPIN?", "SIM PIN Status"),
            ("AT+QCCID", "SIM Card ICCID"),
            ("AT+CIMI", "SIM IMSI Subscriber ID"),
            ("AT+CSQ", "Signal Quality (CSQ)"),
            ("AT+CBC", "Supply Voltage (mV)"),
            ("AT+QTEMP", "Module Temperature (°C)"),
            ('AT+QENG="servingcell"', "Serving Cell Parameters"),
            ("AT+COPS?", "Current Registered Operator"),
            ("AT+CEREG?", "Network Registration Status")
        ]

        for cmd, desc in commands:
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            
            print(f"--- Sending {cmd} ({desc}) ---")
            ser.write(f"{cmd}\r\n".encode("ascii"))
            time.sleep(0.4)
            
            response = ser.read_all().decode("ascii", errors="replace")
            print(response.strip())
            print("-" * 50)
            time.sleep(0.2)

except Exception as e:
    print(f"Error opening COM3: {e}")

print("\nValidation Complete!")
