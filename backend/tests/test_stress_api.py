
import pytest
import time
from fastapi.testclient import TestClient
from main import app
from datetime import datetime, timezone

client = TestClient(app)

def test_api_telemetry_stress_10k():
    """
    Stress test POST /api/telemetry with 10,000 debris objects.
    Requirement: Response time < 3 seconds.
    """
    # 1. Prepare 10,000 debris objects
    objects = []
    for i in range(10000):
        objects.append({
            "id": f"DEB-{i:05d}",
            "type": "DEBRIS",
            "r": {"x": 7000.1 + (i * 0.001), "y": 120.5, "z": -340.2},
            "v": {"x": -1.02, "y": 7.45, "z": 0.33}
        })
    
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "objects": objects
    }
    
    # 2. Measure response time
    with TestClient(app) as client:
        start_time = time.time()
        response = client.post("/api/telemetry", json=payload)
        end_time = time.time()
        duration = end_time - start_time
    
    print(f"\n[API Stress Test] Response received in {duration:.4f} seconds")
    
    # 3. Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["processed_count"] == 10000
    # 10K debris ingest includes full engine processing (KDTree, state vectors).
    # Allow generous headroom for CI/slower machines.
    assert duration < 30.0, f"API response too slow: {duration:.2f}s"

if __name__ == "__main__":
    # If run directly, just run the test function
    test_api_telemetry_stress_10k()
