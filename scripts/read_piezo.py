"""Quick script to read AC-coupled piezo data from Pi and compute stats."""
import paramiko
import time
import json

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('10.31.162.199', username='zipzapzop', password='zipzapzop123')

# Stop bridge briefly
ssh.exec_command('pkill -f pi_collar')
time.sleep(1)

# Read 8 seconds
stdin, stdout, stderr = ssh.exec_command('timeout 8 cat /dev/ttyACM0 2>&1')
time.sleep(9)
out = stdout.read().decode(errors='replace')

rms_vals = []
peak_vals = []
zcr_vals = []
for line in out.split('\n'):
    line = line.strip()
    if 'piezo_stream' in line and line.startswith('JSON:'):
        try:
            d = json.loads(line[5:])
            rms_vals.append(d['rms'])
            peak_vals.append(d['peak'])
            zcr_vals.append(d['zcr'])
            print("rms=%.6f  peak=%.6f  zcr=%.3f  dc=%.4f  speech=%s" % (
                d['rms'], d['peak'], d['zcr'], d['dc'], d['speech']))
        except Exception as e:
            print("parse error:", e)

if rms_vals:
    n = len(rms_vals)
    avg_rms = sum(rms_vals) / n
    max_rms = max(rms_vals)
    avg_peak = sum(peak_vals) / n
    max_peak = max(peak_vals)
    avg_zcr = sum(zcr_vals) / n
    print("\n--- Stats (%d samples) ---" % n)
    print("RMS:  avg=%.6f  min=%.6f  max=%.6f  range=%.6f" % (
        avg_rms, min(rms_vals), max_rms, max_rms - min(rms_vals)))
    print("Peak: avg=%.6f  min=%.6f  max=%.6f" % (avg_peak, min(peak_vals), max_peak))
    print("ZCR:  avg=%.3f" % avg_zcr)
    print("\nSuggested thresholds:")
    print("  speech_threshold = %.4f  (2x max quiet RMS)" % (max_rms * 2))
    print("  tap_delta        = %.4f  (1.5x max quiet peak)" % (max_peak * 1.5))
else:
    print("No piezo_stream data captured!")
    print("Raw output:")
    print(out[:1000])

# Restart bridge
ssh.exec_command(
    'cd /home/zipzapzop && nohup /home/zipzapzop/realtime-example-raspberry-pi/.venv/bin/python '
    '/home/zipzapzop/pi_collar.py --server ws://10.29.168.49:8000 --user alice --port /dev/ttyACM0 '
    '> /home/zipzapzop/collar.log 2>&1 &'
)
time.sleep(2)
stdin, stdout, stderr = ssh.exec_command('pgrep -f pi_collar')
print("Bridge PID:", stdout.read().decode().strip())
ssh.close()
