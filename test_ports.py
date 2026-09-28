import serial
import serial.tools.list_ports
import time
import sys

print("==================================================")
print("Quectel BC660K Direct Serial Port Probe Tool")
print("==================================================")

ports = list(serial.tools.list_ports.comports())
print(f"Found {len(ports)} system serial ports:\n")
for p in ports:
    print(f"  - {p.device}: {p.description} [{p.hwid}]")

target_ports = [p.device for p in ports]
bauds = [9600, 115200, 57600]

print("\n--------------------------------------------------")
print("Probing ports with AT commands...")
print("--------------------------------------------------\n")

for port in target_ports:
    print(f"Testing {port}...")
    for baud in bauds:
        try:
            s = serial.Serial(port, baud, timeout=1.2)
            s.reset_input_buffer()
            s.reset_output_buffer()
            
            # Send AT test
            s.write(b"AT\r\n")
            time.sleep(0.3)
            response = s.read_all().decode("ascii", errors="replace")
            
            if "OK" in response:
                print(f"  >>> SUCCESS ON {port} @ {baud} BAUD! <<<")
                print(f"  Response: {repr(response.strip())}\n")
                
                # Query ATI module details
                s.write(b"ATI\r\n")
                time.sleep(0.3)
                ati_resp = s.read_all().decode("ascii", errors="replace")
                print(f"  Module Info (ATI):\n  {ati_resp.strip()}\n")
                
                # Query AT+CSQ signal quality
                s.write(b"AT+CSQ\r\n")
                time.sleep(0.3)
                csq_resp = s.read_all().decode("ascii", errors="replace")
                print(f"  Signal Quality (AT+CSQ):\n  {csq_resp.strip()}\n")

                # Query AT+QENG="servingcell"
                s.write(b'AT+QENG="servingcell"\r\n')
                time.sleep(0.3)
                qeng_resp = s.read_all().decode("ascii", errors="replace")
                print(f"  Serving Cell (AT+QENG):\n  {qeng_resp.strip()}\n")

                s.close()
                sys.exit(0)
            else:
                if response:
                    print(f"  [{port} @ {baud}] RX: {repr(response.strip())}")
                else:
                    print(f"  [{port} @ {baud}] No response")
            s.close()
        except Exception as e:
            print(f"  [{port} @ {baud}] Error: {e}")

print("\nProbe finished.")
