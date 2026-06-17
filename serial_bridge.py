"""
serial_bridge.py
────────────────
Reads Arduino serial output and relays it over WebSocket so the
Solar Tilt Dashboard (dashboard.html) can receive live sensor data.

USAGE:
    pip install pyserial websockets
    python serial_bridge.py --port COM3 --baud 115200

    # Linux/Mac:
    python serial_bridge.py --port /dev/ttyUSB0 --baud 115200

Then open dashboard.html in a browser. The default WebSocket URL
is ws://localhost:8765 — matches what the dashboard expects.

HOW IT WORKS:
    Arduino → USB Serial → this script → WebSocket → browser dashboard

The Arduino sketch (Idealab_PBL.ino) prints lines like:
    Voltage (V): 5.12
    Current (mA): 83.40
    Power (mW): 425.7
    Lux: 32100.00
    Temperature (C): 31.4
    Tilt (deg): 13.2
    ------------------------

This bridge forwards those lines verbatim to all connected dashboard clients.
"""

import asyncio
import argparse
import sys
import threading
import queue
import time

try:
    import serial
except ImportError:
    print("ERROR: pyserial not installed. Run:  pip install pyserial")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("ERROR: websockets not installed. Run:  pip install websockets")
    sys.exit(1)

# ─── Globals ────────────────────────────────────────────────────────────────
data_queue = queue.Queue()
connected_clients = set()
args = None

# ─── Serial Reader (runs in background thread) ───────────────────────────────
def serial_reader(port, baud):
    """Continuously reads lines from Arduino serial and puts them in the queue."""
    print(f"[Serial]  Opening {port} at {baud} baud…")
    while True:
        try:
            with serial.Serial(port, baud, timeout=2) as ser:
                print(f"[Serial]  ✓ Connected to {port}")
                buffer = ""
                while True:
                    raw = ser.readline()
                    if raw:
                        try:
                            line = raw.decode('utf-8', errors='replace').strip()
                            if line:
                                data_queue.put(line + "\n")
                        except Exception as e:
                            print(f"[Serial]  Decode error: {e}")
        except serial.SerialException as e:
            print(f"[Serial]  ✗ {e} — retrying in 3s…")
            time.sleep(3)
        except Exception as e:
            print(f"[Serial]  Unexpected error: {e} — retrying in 3s…")
            time.sleep(3)

# ─── WebSocket Broadcaster ───────────────────────────────────────────────────
async def broadcast_loop():
    """Drains the queue and broadcasts each line to all connected clients."""
    while True:
        await asyncio.sleep(0.05)
        messages = []
        try:
            while True:
                messages.append(data_queue.get_nowait())
        except queue.Empty:
            pass

        if messages and connected_clients:
            payload = "".join(messages)
            dead = set()
            for ws in connected_clients:
                try:
                    await ws.send(payload)
                except Exception:
                    dead.add(ws)
            connected_clients -= dead

# ─── WebSocket Handler ───────────────────────────────────────────────────────
async def ws_handler(websocket, path=None):
    client_addr = websocket.remote_address
    print(f"[WS]      ✓ Client connected: {client_addr}")
    connected_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        connected_clients.discard(websocket)
        print(f"[WS]      ✗ Client disconnected: {client_addr}")

# ─── Main ────────────────────────────────────────────────────────────────────
async def main_async(host, port_ws):
    # Start broadcaster
    asyncio.create_task(broadcast_loop())

    # Start WS server
    print(f"[WS]      Listening on ws://{host}:{port_ws}")
    print(f"[WS]      Open dashboard.html and set URL to ws://{host}:{port_ws}")
    print()

    async with websockets.serve(ws_handler, host, port_ws):
        await asyncio.Future()  # run forever

def main():
    global args
    parser = argparse.ArgumentParser(
        description="Arduino → WebSocket bridge for Solar Tilt Dashboard"
    )
    parser.add_argument('--port',    default='COM3',   help='Serial port (e.g. COM3 or /dev/ttyUSB0)')
    parser.add_argument('--baud',    default=115200,   type=int, help='Baud rate (default 115200)')
    parser.add_argument('--ws-host', default='localhost', help='WebSocket host (default localhost)')
    parser.add_argument('--ws-port', default=8765,     type=int, help='WebSocket port (default 8765)')
    args = parser.parse_args()

    # Serial reader runs in a daemon thread
    t = threading.Thread(
        target=serial_reader,
        args=(args.port, args.baud),
        daemon=True
    )
    t.start()

    print("=" * 55)
    print("  Solar Tilt Dashboard — Serial Bridge")
    print("=" * 55)
    print(f"  Serial Port : {args.port} @ {args.baud} baud")
    print(f"  WebSocket   : ws://{args.ws_host}:{args.ws_port}")
    print("=" * 55)
    print("  Press Ctrl+C to stop.")
    print()

    try:
        asyncio.run(main_async(args.ws_host, args.ws_port))
    except KeyboardInterrupt:
        print("\n[Bridge]  Stopped.")

if __name__ == '__main__':
    main()
