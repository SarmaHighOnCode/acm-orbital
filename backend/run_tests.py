import subprocess
import sys

with open("test_out.txt", "w", encoding="utf-8") as f:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "backend/tests", "-v"],
        capture_output=True,
        text=True
    )
    f.write(result.stdout)
    f.write(result.stderr)
