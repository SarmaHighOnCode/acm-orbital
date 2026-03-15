import argparse
import subprocess
import time
import os
import urllib.error
import urllib.request
import json
import traceback
import sys

def check_server_running(url="http://localhost:8000/api/telemetry"):
    """Checks if the FastAPI server is responding."""
    try:
        # Send an empty POST request just to see if it responds with a 422 
        # (meaning the server is up and router is active)
        req = urllib.request.Request(url, method="POST")
        urllib.request.urlopen(req)
        return True
    except urllib.error.HTTPError as e:
        if e.code in [422, 500]: # Server is up but rejecting bad payload
            return True
        return False
    except Exception:
        return False

def inject_telemetry(file_path):
    print(f"\n🚀 Injecting telemetry from {file_path} into the running engine...")
    try:
        data = open(file_path, 'r', encoding='utf-8').read().encode('utf-8')
        req = urllib.request.Request(
            'http://localhost:8000/api/telemetry', 
            data=data, 
            headers={'Content-Type': 'application/json'}
        )
        res = urllib.request.urlopen(req)
        print(f"✅ Success! Engine Response: {res.read().decode('utf-8')}")
    except Exception as e:
        print(f"❌ Failed to inject telemetry: {e}")
        traceback.print_exc()

def main():
    parser = argparse.ArgumentParser(description="ACM-Orbital: Launch Simulation Engine with custom datasets")
    parser.add_argument(
        "--dataset", 
        type=str, 
        choices=["real", "worst-case", "none"], 
        default="none",
        help="The telemetry dataset to aggressively inject on startup."
    )
    args = parser.parse_args()

    # Step 1: Check if datasets exist
    if args.dataset == "real":
        if not os.path.exists("live_telemetry.json"):
            print("⚠️ 'live_telemetry.json' not found. We will generate it live from Celestrak...")
            subprocess.run([sys.executable, "backend/fetch_real_tle.py"], check=True)
    elif args.dataset == "worst-case":
        if not os.path.exists("backend/worst_case_telemetry.json"):
            print("❌ 'backend/worst_case_telemetry.json' not found. Please ensure it was generated.")
            sys.exit(1)

    # Step 2: Boot Uvicorn Server in Background
    print("\n⚙️ Booting ACM-Orbital Backend Orchestrator...")
    backend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend")
    server_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", "8000"],
        cwd=backend_dir,
        stdout=subprocess.DEVNULL,  # Keep logs clean
        stderr=subprocess.DEVNULL
    )

    # Step 3: Wait for server to physically spin up
    print("⏳ Waiting for FastAPI boundaries to initialize...")
    for _ in range(15):
        if check_server_running():
            print("📡 Connection Established!")
            break
        time.sleep(1)
    else:
        print("❌ Server failed to start in time.")
        server_process.kill()
        sys.exit(1)

    # Step 4: Inject requested payload
    if args.dataset == "real":
        inject_telemetry("live_telemetry.json")
    elif args.dataset == "worst-case":
        inject_telemetry("backend/worst_case_telemetry.json")

    print("\n🛡️ System is Online & Ready for Assessment.")
    print("Press CTRL+C to safely shutdown.")

    try:
        # Keep main python process alive so subprocess doesn't orphan
        server_process.wait()
    except KeyboardInterrupt:
        print("\n🛑 Shutting down server...")
        server_process.terminate()
        server_process.wait()

if __name__ == "__main__":
    main()
