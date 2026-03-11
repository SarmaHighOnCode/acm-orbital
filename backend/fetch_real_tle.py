import sys
import urllib.request
import json
from datetime import datetime, timezone

try:
    from sgp4.api import Satrec, WGS84, jday
except ImportError:
    print("Error: The 'sgp4' package is required.")
    print("Please install it by running: pip install sgp4")
    sys.exit(1)

# Celestrak Active Satellites TLE
CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php?GROUP=active&FORMAT=tle"

def fetch_and_convert_tles(limit=2500):
    """Fetches real-time orbital elements and converts to ACM-Orbital JSON schema."""
    print(f"📡 Fetching live satellite TLEs from Celestrak...")
    
    req = urllib.request.Request(CELESTRAK_URL, headers={'User-Agent': 'ACM-Orbital-Auditor/1.0'})
    try:
        with urllib.request.urlopen(req) as response:
            lines = response.read().decode('utf-8').strip().split('\n')
    except Exception as e:
        print(f"Failed to download TLEs: {e}")
        sys.exit(1)

    print("✅ Download complete. Computing physical state vectors [r, v]...")
    
    telemetry_objects = []
    now = datetime.now(timezone.utc)
    
    # Calculate Julian date for rigorous SGP4 propagation
    jd, fr = jday(now.year, now.month, now.day, now.hour, now.minute, now.second + now.microsecond / 1e6)

    # TLE format generally has 3 lines per object (Name, Line 1, Line 2)
    for i in range(0, min(len(lines), limit * 3), 3):
        try:
            name = lines[i].strip()
            line1 = lines[i+1].strip()
            line2 = lines[i+2].strip()
            
            # Norad ID is stored in columns 2-7 of Line 1
            norad_id = line1[2:7].strip()
            
            # Initialize SGP4 Physics Engine parser
            satellite = Satrec.twoline2rv(line1, line2)
            
            # Propagate to exact current UTC time
            e, r, v = satellite.sgp4(jd, fr)
            
            if e == 0:  # e == 0 means successful propagation without decay
                telemetry_objects.append({
                    "id": f"NORAD-{norad_id}",
                    "type": "DEBRIS" if "DEB" in name or "PLATFORM" in name else "SATELLITE",
                    "r": {"x": r[0], "y": r[1], "z": r[2]},
                    "v": {"x": v[0], "y": v[1], "z": v[2]}
                })
        except Exception:
            # Skip invalid lines or decayed prop errors
            continue

    print(f"Processed {len(telemetry_objects)} valid physical objects into ECI frame.")
    
    # Save the JSON dump payload matching the ACM API contract
    output_payload = {
        "timestamp": now.isoformat().replace("+00:00", "Z"),
        "objects": telemetry_objects
    }
    
    output_file = "live_telemetry.json"
    with open(output_file, "w") as f:
        json.dump(output_payload, f, indent=2)
        
    print(f"\n🚀 Real-world telemetry successfully exported to '{output_file}'!")
    print(f"You can pipe this directly into the Engine API: POST /telemetry")

if __name__ == "__main__":
    fetch_and_convert_tles()
