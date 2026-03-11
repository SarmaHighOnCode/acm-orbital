import time
import uuid
import random
from datetime import datetime, timezone
from engine.simulation import SimulationEngine

engine = SimulationEngine()

objects = []
for i in range(15000):
    objects.append({
        "id": f"OBJ-{i}",
        "type": "DEBRIS" if i > 49 else "SATELLITE",
        "r": {"x": random.uniform(6000, 7000), "y": random.uniform(6000, 7000), "z": random.uniform(6000, 7000)},
        "v": {"x": random.uniform(-7, 7), "y": random.uniform(-7, 7), "z": random.uniform(-7, 7)}
    })

t0 = time.time()
engine.ingest_telemetry(datetime.now(timezone.utc).isoformat(), objects)
t1 = time.time()
print(f"Latency for 15,000 objects: {(t1 - t0) * 1000:.2f} ms")
