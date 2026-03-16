
from datetime import datetime, timezone
import numpy as np
import sys
import os

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from engine.ground_stations import GroundStationNetwork

def test_los():
    gs_network = GroundStationNetwork()
    sat_pos = np.array([6778.0, 0.0, 0.0])
    ts = datetime.fromisoformat("2026-03-12T08:01:00.000Z".replace("Z", "+00:00"))
    
    # Check next 3600s
    found = False
    for i in range(0, 3600, 10):
        t = ts + (i * (ts.resolution * 0.000001 if hasattr(ts, 'resolution') else 1)) # dummy timestamp math
        t = ts + (datetime.now() - datetime.now()) # wait I'll just use timedelta
        from datetime import timedelta
        t = ts + timedelta(seconds=i)
        
        # We need to propagate the sat too, but let's assume it stays roughly at same pos for a while
        # Actually it moves at 7.6 km/s.
        # Let's just check the initial point first.
        
        has_los = gs_network.check_line_of_sight(sat_pos, t)
        if has_los:
            print(f"Found LOS at T+{i}s")
            # Log which station
            for gs in gs_network.stations:
                el = gs_network.compute_elevation(sat_pos, gs, t)
                if el >= gs["min_elev_deg"]:
                    print(f"  Station: {gs['name']}, Elevation: {el:.2f}")
            found = True
            break
    
    if not found:
        print("No LOS found in the first hour.")
        # Print elevations at T=0
        print("Elevations at T=0:")
        for gs in gs_network.stations:
            el = gs_network.compute_elevation(sat_pos, gs, ts)
            print(f"  {gs['name']}: {el:.2f} (min: {gs['min_elev_deg']})")

if __name__ == "__main__":
    test_los()
