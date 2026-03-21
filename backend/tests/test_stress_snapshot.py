
import pytest
import time
from fastapi.testclient import TestClient
from main import app
from datetime import datetime, timezone

def test_api_snapshot_stress_10k():
    """
    Stress test GET /api/visualization/snapshot with 10,000 debris objects.
    Ensures vectorized coordinate conversion is efficient.
    """
    with TestClient(app) as client:
        # 1. Ingest 10,000 objects first
        objects = []
        for i in range(10000):
            objects.append({
                "id": f"DEB-{i:05d}",
                "type": "DEBRIS",
                "r": {"x": 7000.1 + (i * 0.0001), "y": 120.5, "z": -340.2},
                "v": {"x": -1.02, "y": 7.45, "z": 0.33}
            })
        
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "objects": objects
        }
        client.post("/api/telemetry", json=payload)
        
        # 2. Measure snapshot response time
        start_time = time.time()
        response = client.get("/api/visualization/snapshot")
        end_time = time.time()
        duration = end_time - start_time
        
    print(f"\n[Snapshot Stress Test] Response received in {duration:.4f} seconds")
    
    # 3. Assertions
    assert response.status_code == 200
    data = response.json()
    assert len(data["debris_cloud"]) >= 10000, (
        f"Expected at least 10K debris in snapshot, got {len(data['debris_cloud'])}"
    )
    # Snapshot should be very fast with vectorization
    assert duration < 1.0, f"Snapshot response too slow: {duration:.2f}s"

if __name__ == "__main__":
    test_api_snapshot_stress_10k()
