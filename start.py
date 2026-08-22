#!/usr/bin/env python3
"""
XAUUSD Technical Analysis Application
Starts both the FastAPI backend and Dash frontend.
"""

import sys
import os
import subprocess
import time
import signal
import atexit

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def _get_env():
    """Get environment with PYTHONPATH set to project root."""
    env = os.environ.copy()
    project_root = os.path.dirname(os.path.abspath(__file__))
    env["PYTHONPATH"] = project_root + os.pathsep + env.get("PYTHONPATH", "")
    return env

def start_backend():
    """Start the FastAPI backend server."""
    print("Starting FastAPI backend on port 8051...")
    backend_process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8051"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=_get_env(),
    )
    return backend_process

def start_frontend():
    """Start the Dash frontend server."""
    print("Starting Dash frontend on port 8050...")
    frontend_process = subprocess.Popen(
        [sys.executable, "frontend/app.py"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=_get_env(),
    )
    return frontend_process

def main():
    print("=" * 60)
    print("XAUUSD Technical Analysis Application")
    print("=" * 60)
    print()
    print("Requirements:")
    print("  - MetaTrader 5 must be running on your local machine")
    print("  - Python packages: fastapi, uvicorn, dash, plotly, MetaTrader5, pandas, numpy")
    print()
    print("URLs:")
    print("  - Frontend: http://127.0.0.1:8050")
    print("  - Backend API: http://127.0.0.1:8051")
    print("  - API Docs: http://127.0.0.1:8051/docs")
    print()
    print("=" * 60)
    print()
    
    backend = start_backend()
    time.sleep(3)  # Wait for backend to start
    frontend = start_frontend()
    
    processes = [backend, frontend]
    
    def cleanup():
        print("\nShutting down servers...")
        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=5)
            except:
                p.kill()
    
    atexit.register(cleanup)
    
    try:
        print("\nServers are running. Press Ctrl+C to stop.")
        print()
        
        # Wait for processes
        while True:
            backend_status = backend.poll()
            frontend_status = frontend.poll()
            
            if backend_status is not None:
                print(f"Backend exited with code {backend_status}")
                break
            if frontend_status is not None:
                print(f"Frontend exited with code {frontend_status}")
                break
            
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\nReceived interrupt signal.")
    finally:
        cleanup()

if __name__ == "__main__":
    main()