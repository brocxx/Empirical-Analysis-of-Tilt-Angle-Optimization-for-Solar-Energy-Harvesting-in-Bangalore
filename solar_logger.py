#!/usr/bin/env python3
"""
solar_logger.py
────────────────
Reads solar panel telemetry CSV rows from Arduino serial port, logs them to session-specific
CSVs, and auto-generates comparative study graphs (power, normalised efficiency, temperature).
At the end of a day, it merges the sessions and creates intraday stitched curves.

Dependencies:
    pip install pyserial pandas matplotlib numpy

Usage:
    python solar_logger.py --port COM3
    python solar_logger.py --simulate
"""

import os
import sys
import time
import argparse
import datetime
import csv
import queue
import threading
import asyncio

# Third-party libraries
try:
    import serial
except ImportError:
    print("[Error] 'pyserial' is not installed. Please run: pip install pyserial")
    sys.exit(1)

try:
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
except ImportError:
    print("[Error] 'pandas', 'matplotlib', or 'numpy' is missing. Please run: pip install pandas matplotlib numpy")
    sys.exit(1)

try:
    import websockets
    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False


# ─── WebSocket Server & Broadcasting ──────────────────────────────────────────
ws_clients = set()
ws_loop = None

def start_ws_server(host='localhost', port=8765):
    """Starts the WebSocket server in a background thread."""
    global ws_loop
    if not HAS_WEBSOCKETS:
        print("[WS Server] Notice: 'websockets' library not found. Dashboard integration disabled.")
        return
    
    ws_loop = asyncio.new_event_loop()
    
    async def handler(websocket, path=None):
        ws_clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            ws_clients.discard(websocket)
            
    async def main_ws():
        async with websockets.serve(handler, host, port):
            await asyncio.Future()  # run forever
            
    def run_loop():
        asyncio.set_event_loop(ws_loop)
        try:
            ws_loop.run_until_complete(main_ws())
        except Exception:
            pass

    t = threading.Thread(target=run_loop, daemon=True)
    t.start()
    print(f"[WS Server] Broadcast server running on ws://{host}:{port}")

def broadcast_to_ws(message):
    """Broadcasts a message to all connected WebSocket clients in a thread-safe way."""
    if not ws_clients or ws_loop is None:
        return
    
    async def send_all():
        if ws_clients:
            clients_copy = list(ws_clients)
            dead = set()
            for client in clients_copy:
                try:
                    await client.send(message)
                except Exception:
                    dead.add(client)
            if dead:
                ws_clients.difference_update(dead)
                
    asyncio.run_coroutine_threadsafe(send_all(), ws_loop)


# ─── Configurable Constants ───────────────────────────────────────────────────
SERIAL_PORT = "COM5"          # Default serial port (can override via CLI)
BAUD_RATE = 115200            # Serial baud rate
SESSION_DURATION_MINS = 60    # Logging session length in minutes
GRAPHS_DIR = "graphs"         # Output directory for graphs

# Expected columns from the Arduino sketch
COLUMNS = [
    "timestamp_ms", "tilt_setting_deg", "lux", "temp_c", "voltage_v",
    "current_ma", "power_w", "power_corrected_w", "temp_correction_pct",
    "tilt_measured_deg", "cumulative_wh"
]


# ─── Plot Styling ─────────────────────────────────────────────────────────────
def apply_plot_style(ax, title, xlabel, ylabel):
    """Applies a clean, modern aesthetic to a Matplotlib axis."""
    ax.set_title(title, fontsize=13, fontweight="bold", pad=15, color="#1e293b")
    ax.set_xlabel(xlabel, fontsize=10, labelpad=8, color="#475569")
    ax.set_ylabel(ylabel, fontsize=10, labelpad=8, color="#475569")
    ax.tick_params(axis="both", colors="#475569", labelsize=9)
    ax.grid(True, linestyle="--", alpha=0.5, color="#cbd5e1")
    
    # Despine: remove top and right borders
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#cbd5e1")
    ax.spines["bottom"].set_color("#cbd5e1")
    
    # Styling legends if present
    legend = ax.legend(frameon=True, facecolor="#ffffff", edgecolor="#cbd5e1", fontsize=9, loc="upper right")
    if legend:
        legend.get_frame().set_boxstyle("round,pad=0.4")


# ─── Visualisation Functions ──────────────────────────────────────────────────
def generate_session_graphs(csv_path, angle, session, date_str):
    """Generates Graphs A, B, and C for a completed session CSV."""
    if not os.path.exists(csv_path):
        print(f"[Plotting] Error: CSV file not found at {csv_path}")
        return

    print(f"[Plotting] Generating session graphs from {csv_path}...")
    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"[Plotting] Error reading CSV: {e}")
        return

    if df.empty:
        print("[Plotting] CSV file is empty. Skipping graph generation.")
        return

    # Parse system time or fallback to relative elapsed minutes
    use_system_time = "system_time" in df.columns
    if use_system_time:
        df["time_axis"] = pd.to_datetime(df["system_time"])
        x_label = "Wall Clock Time"
    else:
        df["time_axis"] = (df["timestamp_ms"] - df["timestamp_ms"].iloc[0]) / 60000.0
        x_label = "Elapsed Time (minutes)"

    # Compute Normalized Efficiency: norm_eff = power_corrected_w / (lux / 1000)
    df["norm_eff"] = np.where(df["lux"] > 100, df["power_corrected_w"] / (df["lux"] / 1000.0), 0.0)

    os.makedirs(GRAPHS_DIR, exist_ok=True)
    session_title = session.capitalize()
    
    # ─── Graph A: Power vs Time ───────────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 5), facecolor="#f8fafc")
    ax.set_facecolor("#ffffff")
    ax.plot(df["time_axis"], df["power_w"], label="Raw Power (power_w)", color="#f97316", linestyle="--", linewidth=1.8)
    ax.plot(df["time_axis"], df["power_corrected_w"], label="Temp-Corrected Power (power_corrected_w)", color="#0ea5e9", linestyle="-", linewidth=2.0)
    
    if use_system_time:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate()
        
    apply_plot_style(ax, f"Power Output — {angle}° Tilt — {session_title} Session", x_label, "Power (W)")
    fig_path_a = os.path.join(GRAPHS_DIR, f"power_{angle}deg_{session}_{date_str}.png")
    plt.tight_layout()
    plt.savefig(fig_path_a, dpi=120)
    plt.close()
    print(f"  [Saved] Graph A: {fig_path_a}")

    # ─── Graph B: Normalised Efficiency vs Time ────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 5), facecolor="#f8fafc")
    ax.set_facecolor("#ffffff")
    ax.plot(df["time_axis"], df["norm_eff"], label="Normalised Efficiency", color="#10b981", linestyle="-", linewidth=2.0)
    
    if use_system_time:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate()

    apply_plot_style(ax, f"Normalised Efficiency — {angle}° — {session_title}", x_label, "Efficiency (W/klux)")
    fig_path_b = os.path.join(GRAPHS_DIR, f"efficiency_{angle}deg_{session}_{date_str}.png")
    plt.tight_layout()
    plt.savefig(fig_path_b, dpi=120)
    plt.close()
    print(f"  [Saved] Graph B: {fig_path_b}")

    # ─── Graph C: Panel Temperature vs Time ───────────────────────────────────
    fig, ax = plt.subplots(figsize=(9, 5), facecolor="#f8fafc")
    ax.set_facecolor("#ffffff")
    ax.plot(df["time_axis"], df["temp_c"], label="Measured Temperature", color="#ef4444", linestyle="-", linewidth=2.0)
    ax.axhline(25.0, color="#b91c1c", linestyle="--", linewidth=1.5, label="STC Reference (25°C)")
    
    if use_system_time:
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        fig.autofmt_xdate()

    apply_plot_style(ax, f"Panel Temperature — {angle}° — {session_title}", x_label, "Temperature (°C)")
    fig_path_c = os.path.join(GRAPHS_DIR, f"temp_{angle}deg_{session}_{date_str}.png")
    plt.tight_layout()
    plt.savefig(fig_path_c, dpi=120)
    plt.close()
    print(f"  [Saved] Graph C: {fig_path_c}")


def check_and_generate_stitched_graphs(angle, date_str):
    """Checks if all 3 session CSVs exist for an angle/date, and if so, merges them to plot Graphs D, E, F."""
    sessions = ["morning", "midday", "afternoon"]
    csv_paths = {s: f"solar_{angle}deg_{s}_{date_str}.csv" for s in sessions}
    
    missing = [s for s, path in csv_paths.items() if not os.path.exists(path)]
    if missing:
        print(f"\n[Stitching] Notice: Cannot stitch end-of-day curves yet. Missing sessions: {', '.join(missing)}")
        return False

    print(f"\n[Stitching] Found all 3 sessions for {angle} deg Tilt on {date_str}. Generating end-of-day graphs...")
    
    # Read and merge dataframes
    dfs = []
    session_bounds = [] # Store boundary times for visualization
    
    for s in sessions:
        try:
            df_s = pd.read_csv(csv_paths[s])
            if df_s.empty:
                print(f"[Stitching] Error: {csv_paths[s]} is empty.")
                return False
            df_s["session"] = s
            # Ensure chronological order
            df_s["system_time_dt"] = pd.to_datetime(df_s["system_time"])
            df_s = df_s.sort_values("system_time_dt")
            dfs.append(df_s)
            
            # Record bounds: (start_dt, end_dt, name)
            session_bounds.append((df_s["system_time_dt"].iloc[0], df_s["system_time_dt"].iloc[-1], s.capitalize()))
        except Exception as e:
            print(f"[Stitching] Error loading {csv_paths[s]}: {e}")
            return False

    df_combined = pd.concat(dfs, ignore_index=True)
    df_combined = df_combined.sort_values("system_time_dt")
    df_combined["norm_eff"] = np.where(df_combined["lux"] > 100, df_combined["power_corrected_w"] / (df_combined["lux"] / 1000.0), 0.0)

    x_values = df_combined["system_time_dt"]
    os.makedirs(GRAPHS_DIR, exist_ok=True)

    # Helper function to add vertical boundary lines and text annotations
    def add_session_markers(ax):
        # Draw boundaries
        for idx, (start, end, label) in enumerate(session_bounds):
            # Draw vertical dashed boundary lines
            ax.axvline(start, color="#64748b", linestyle=":", linewidth=1.2)
            ax.axvline(end, color="#64748b", linestyle=":", linewidth=1.2)
            
            # Position label in the middle of session time window
            mid_point = start + (end - start) / 2
            # Add text label at the top of the plot
            y_lim = ax.get_ylim()
            y_pos = y_lim[0] + (y_lim[1] - y_lim[0]) * 0.85
            ax.text(mid_point, y_pos, label, color="#475569", fontsize=9.5,
                    fontweight="bold", ha="center", va="center",
                    bbox=dict(facecolor="#f1f5f9", edgecolor="#cbd5e1", boxstyle="round,pad=0.3", alpha=0.9))

    # ─── Graph D: Intraday Power Curve ────────────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5.5), facecolor="#f8fafc")
    ax.set_facecolor("#ffffff")
    ax.plot(x_values, df_combined["power_w"], label="Raw Power (power_w)", color="#f97316", linestyle="--", linewidth=1.8)
    ax.plot(x_values, df_combined["power_corrected_w"], label="Temp-Corrected Power (power_corrected_w)", color="#0ea5e9", linestyle="-", linewidth=2.2)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    
    # Set y limits nicely
    ax.set_ylim(bottom=0)
    add_session_markers(ax)
    apply_plot_style(ax, f"Intraday Power Curve — {angle}° Tilt — {date_str}", "Wall Clock Time", "Power (W)")
    
    fig_path_d = os.path.join(GRAPHS_DIR, f"intraday_power_{angle}deg_{date_str}.png")
    plt.tight_layout()
    plt.savefig(fig_path_d, dpi=120)
    plt.close()
    print(f"  [Saved] Graph D: {fig_path_d}")

    # ─── Graph E: Intraday Normalised Efficiency Curve ─────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5.5), facecolor="#f8fafc")
    ax.set_facecolor("#ffffff")
    ax.plot(x_values, df_combined["norm_eff"], label="Normalised Efficiency", color="#10b981", linestyle="-", linewidth=2.2)
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    
    ax.set_ylim(bottom=0)
    add_session_markers(ax)
    apply_plot_style(ax, f"Intraday Normalised Efficiency — {angle}° Tilt — {date_str}", "Wall Clock Time", "Efficiency (W/klux)")
    
    fig_path_e = os.path.join(GRAPHS_DIR, f"intraday_efficiency_{angle}deg_{date_str}.png")
    plt.tight_layout()
    plt.savefig(fig_path_e, dpi=120)
    plt.close()
    print(f"  [Saved] Graph E: {fig_path_e}")

    # ─── Graph F: Intraday Temperature Curve ──────────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 5.5), facecolor="#f8fafc")
    ax.set_facecolor("#ffffff")
    ax.plot(x_values, df_combined["temp_c"], label="Measured Temp", color="#ef4444", linestyle="-", linewidth=2.2)
    ax.axhline(25.0, color="#b91c1c", linestyle="--", linewidth=1.5, label="STC Reference (25°C)")
    
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.autofmt_xdate()
    
    add_session_markers(ax)
    apply_plot_style(ax, f"Intraday Temperature — {angle}° Tilt — {date_str}", "Wall Clock Time", "Temperature (°C)")
    
    fig_path_f = os.path.join(GRAPHS_DIR, f"intraday_temp_{angle}deg_{date_str}.png")
    plt.tight_layout()
    plt.savefig(fig_path_f, dpi=120)
    plt.close()
    print(f"  [Saved] Graph F: {fig_path_f}")
    
    print("[Stitching] Successfully generated all intraday combined plots.")
    return True


# ─── Serial Logging Worker ────────────────────────────────────────────────────
def print_summary(csv_path):
    """Computes and prints a summary of the recorded session."""
    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            print("\n--- Session Empty ---")
            return
        
        # Calculate stats
        duration_mins = len(df) * 30 / 60.0
        avg_power = df["power_w"].mean()
        avg_power_corr = df["power_corrected_w"].mean()
        max_power = df["power_w"].max()
        avg_temp = df["temp_c"].mean()
        final_cum_wh = df["cumulative_wh"].iloc[-1] if not df["cumulative_wh"].empty else 0.0
        
        print("\n" + "=" * 50)
        print(f"   SESSION SUMMARY: {os.path.basename(csv_path)}")
        print("=" * 50)
        print(f"  Total Data Rows Recorded  : {len(df)}")
        print(f"  Effective Session Time    : {duration_mins:.1f} minutes")
        print(f"  Average Power (Raw)       : {avg_power:.3f} W")
        print(f"  Average Power (Corrected) : {avg_power_corr:.3f} W")
        print(f"  Maximum Power Peak        : {max_power:.3f} W")
        print(f"  Average Panel Temp        : {avg_temp:.1f} C")
        print(f"  Cumulative Energy Yield   : {final_cum_wh:.4f} Wh")
        print("=" * 50 + "\n")
    except Exception as e:
        print(f"\n[Summary] Error printing session stats: {e}")


def serial_logging_session(port, baud, angle, session, date_str, simulate=False, sim_speedup=True):
    """Handles the 60-minute logging session, reading either from serial or mock generator."""
    csv_filename = f"solar_{angle}deg_{session}_{date_str}.csv"
    
    print(f"\n[Logging] Starting session: Angle={angle} deg, Session={session}, Date={date_str}")
    print(f"[Logging] Data will be recorded in: {csv_filename}")
    
    # Total samples needed for exactly 60 minutes with 30s intervals
    # 60 * 2 samples/min = 120 samples
    total_samples = 120
    
    if simulate and sim_speedup:
        # Simulation speedup: 0.1 second = 30 seconds (12 seconds total runtime)
        sim_step_delay = 0.1
        print("[Logging] Running in ACCELERATED simulation mode (120 rows in ~12 seconds).")
    elif simulate:
        sim_step_delay = 30
        print("[Logging] Running in REAL-TIME simulation mode (data every 30 seconds).")
    else:
        print(f"[Logging] Connecting to Serial Port: {port} at {baud} baud.")
    
    # Initialize file and write header
    try:
        f = open(csv_filename, "w", newline="", encoding="utf-8")
        writer = csv.writer(f)
        writer.writerow(COLUMNS + ["system_time"])
        f.flush()
    except Exception as e:
        print(f"[Logging] Error creating CSV file: {e}")
        return

    ser = None
    if not simulate:
        try:
            ser = serial.Serial(port, baud, timeout=3)
            # Flush buffers
            ser.reset_input_buffer()
            print(f"[Serial] Port opened. Waiting for data...")
        except serial.SerialException as e:
            print(f"[Serial] Error: Could not open {port}. {e}")
            f.close()
            return

    count = 0
    serial_packet = {}   # accumulates key:value fields between Arduino separator lines

    # Base datetime for mock wall clock simulation if simulating
    sim_base_times = {
        "morning":   datetime.datetime.strptime(f"{date_str} 08:00:00", "%Y%m%d %H:%M:%S"),
        "midday":    datetime.datetime.strptime(f"{date_str} 11:30:00", "%Y%m%d %H:%M:%S"),
        "afternoon": datetime.datetime.strptime(f"{date_str} 15:00:00", "%Y%m%d %H:%M:%S")
    }
    sim_current_dt = sim_base_times.get(session, datetime.datetime.now())
    cumulative_wh_sum = 0.0

    try:
        while count < total_samples:
            row_data = None
            sys_time_str = None
            
            if simulate:
                # ─── Mock Data Generation ─────────────────────────────────────
                time.sleep(sim_step_delay)
                
                # Mock timestamp_ms
                ts_ms = count * 30000
                
                # Increment simulated wall clock time
                sim_current_dt += datetime.timedelta(seconds=30)
                sys_time_str = sim_current_dt.strftime("%Y-%m-%d %H:%M:%S")
                
                # Physics models based on session and time
                i_factor = count / float(total_samples) # 0.0 to 1.0
                
                if session == "morning":
                    lux = 15000 + i_factor * 45000 + np.random.normal(0, 1000)
                    temp = 22.0 + i_factor * 5.5 + np.random.normal(0, 0.2)
                elif session == "midday":
                    # Peaking in the middle of midday session
                    peak = np.sin(i_factor * np.pi)
                    lux = 80000 + peak * 12000 + np.random.normal(0, 1500)
                    temp = 31.0 + i_factor * 7.5 + np.random.normal(0, 0.3)
                else: # afternoon
                    lux = 55000 - i_factor * 48000 + np.random.normal(0, 1200)
                    temp = 33.5 - i_factor * 6.5 + np.random.normal(0, 0.25)
                
                lux = max(0.0, lux)
                
                # Voltage & current models
                voltage = 17.6 + np.random.normal(0, 0.15)
                # Current proportional to light
                current_ma = (lux / 1000.0) * 8.5 + np.random.normal(0, 8.0)
                current_ma = max(0.0, current_ma)
                
                power_w = (voltage * current_ma) / 1000.0
                
                # Temp correction: -0.4% per deg above 25°C STC
                temp_corr_pct = (temp - 25.0) * -0.004
                power_corr_w = power_w * (1.0 + temp_corr_pct)
                
                # Measure tilt (simulate realistic minor sensor noise/errors)
                tilt_meas = float(angle) + np.random.normal(0, 0.08)
                
                # Accumulate energy yield: power * (30s / 3600s/h)
                cumulative_wh_sum += power_w * (30.0 / 3600.0)
                
                row_data = [
                    ts_ms, angle, round(lux, 2), round(temp, 2), round(voltage, 3),
                    round(current_ma, 2), round(power_w, 4), round(power_corr_w, 4),
                    round(temp_corr_pct, 4), round(tilt_meas, 2), round(cumulative_wh_sum, 6)
                ]
            else:
                # ─── Physical Serial Port Read (key:value packet format) ────────
                # Arduino sends blocks like:
                #   Voltage (V): 17.61
                #   Current (mA): 320.5
                #   Power (W): 5.64
                #   Lux: 45200.00
                #   Temperature (C): 30.87
                #   Tilt (deg): 13.05
                #   ------------------------
                # Accumulate fields; flush one row when separator arrives.

                line = ser.readline()
                if not line:
                    continue  # timeout, try again

                try:
                    decoded = line.decode("utf-8", errors="replace").strip()
                except Exception as e:
                    print(f"\n[Serial] Decode error: {e}")
                    continue

                if not decoded:
                    continue

                # Separator line → flush the accumulated packet as one CSV row
                if decoded.startswith("---") or decoded.startswith("==="):
                    pkt = serial_packet  # alias for readability
                    if not pkt:
                        if count == 0:
                            print(f"\n[Serial] Waiting for first data packet (at separator #{count})...")
                        continue  # empty packet before first separator

                    # DEBUG: Print what we found
                    if count < 3:  # Only debug first few rows
                        print(f"\n[Serial] Separator found. Accumulated fields: {pkt}")

                    # Extract values with fallbacks
                    voltage  = pkt.get("voltage",  0.0)
                    current  = pkt.get("current",  0.0)
                    lux      = pkt.get("lux",      0.0)
                    temp     = pkt.get("temp",     25.0)
                    tilt_mea = pkt.get("tilt",     float(angle))
                    # Power: Arduino sends Power (mW), so convert to W
                    # If power_w is in packet, it's in mW — convert to W
                    power_mw = pkt.get("power_w",  (voltage * current))  # fallback: calculate from V*I in mW
                    power_w  = power_mw / 1000.0  # Convert mW to W

                    # Derived columns
                    temp_corr_pct   = (temp - 25.0) * -0.004
                    power_corr_w    = power_w * (1.0 + temp_corr_pct)
                    ts_ms           = count * 30000
                    cumulative_wh_sum += power_w * (30.0 / 3600.0)

                    row_data = [
                        ts_ms, int(angle), round(lux, 2), round(temp, 2),
                        round(voltage, 3), round(current, 2),
                        round(power_w, 4), round(power_corr_w, 4),
                        round(temp_corr_pct, 4), round(tilt_mea, 2),
                        round(cumulative_wh_sum, 6)
                    ]
                    sys_time_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    serial_packet = {}  # reset for next packet

                else:
                    # Parse "Key (unit): value" lines into the running dict
                    m = decoded.split(":", 1)
                    if len(m) == 2:
                        key_raw = m[0].strip().lower()
                        try:
                            val = float(m[1].strip())
                        except ValueError:
                            if count < 2:
                                print(f"[Serial] Could not parse value from: {decoded}")
                            continue
                        if "voltage"     in key_raw: serial_packet["voltage"]  = val
                        elif "current"   in key_raw: serial_packet["current"]  = val
                        elif "power"     in key_raw: 
                            serial_packet["power_w"]  = val   # Store as-is (mW from Arduino)
                            if count < 2:
                                print(f"[Serial] Parsed Power: {val} mW")
                        elif "lux"       in key_raw: serial_packet["lux"]      = val
                        elif "temp"      in key_raw: serial_packet["temp"]     = val
                        elif "tilt"      in key_raw: serial_packet["tilt"]     = val
                    elif count < 2:
                        print(f"[Serial] Could not parse line: {decoded}")
                    continue  # not a separator → keep reading lines

                if row_data is None:
                    continue

            # ─── Write Row to CSV ─────────────────────────────────────────────
            writer.writerow(row_data + [sys_time_str])
            f.flush()
            
            # Broadcast to WebSocket for live Dashboard integration (JSON)
            try:
                import json as _json
                ws_msg = _json.dumps({
                    "voltage": round(float(row_data[4]), 3),
                    "current": round(float(row_data[5]), 2),
                    "power":   round(float(row_data[6]) * 1000.0, 2),  # convert W -> mW
                    "lux":     round(float(row_data[2]), 1),
                    "temp":    round(float(row_data[3]), 2),
                    "tilt":    round(float(row_data[9]), 2)
                })
                broadcast_to_ws(ws_msg)
            except Exception:
                pass
            
            count += 1
            
            # Print live console update
            percent = (count / total_samples) * 100
            bar = "#" * int(percent // 5) + "-" * (20 - int(percent // 5))
            
            # Display stats
            lux_val = row_data[2]
            temp_val = row_data[3]
            p_val = row_data[6]
            cum_wh = row_data[10]
            
            sys.stdout.write(
                f"\rProgress: [{bar}] {percent:5.1f}% | Row {count:3d}/{total_samples} | "
                f"Power: {p_val:5.3f}W | Temp: {temp_val:4.1f} C | Lux: {lux_val:7.1f} | Wh: {cum_wh:7.5f}"
            )
            sys.stdout.flush()

        print("\n\n[Logging] Session completed successfully.")
        
    except KeyboardInterrupt:
        print("\n\n[Logging] Session interrupted by user (Ctrl+C). Saving partial records...")
    finally:
        f.close()
        if ser and ser.is_open:
            ser.close()

    # Print summary & generate graphs
    print_summary(csv_filename)
    generate_session_graphs(csv_filename, angle, session, date_str)
    
    # Try end of day stitching
    check_and_generate_stitched_graphs(angle, date_str)


# ─── Interactive CLI Menu ─────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Solar Panel Tilt Angle Logging and Analysis Tool")
    parser.add_argument("--port", default=SERIAL_PORT, help=f"Serial port for Arduino (default: {SERIAL_PORT})")
    parser.add_argument("--simulate", "-s", action="store_true", help="Run script in simulated/mock data mode")
    parser.add_argument("--real-time", action="store_true", help="If simulating, run in real-time (30s intervals) instead of fast speed")
    args = parser.parse_args()

    port = args.port
    simulate = args.simulate
    real_time = args.real_time

    # Start WebSocket Broadcast Server for Dashboard integration
    start_ws_server()

    print("=" * 60)
    print("   SOLAR PANEL TILT ANGLE STUDY — LOGGING & ANALYSIS")
    print("=" * 60)
    print(f"  Workspace Port Target : {port} @ {BAUD_RATE} baud")
    print(f"  Simulation Mode       : {'ENABLED' if simulate else 'DISABLED (Connect Arduino)'}")
    print("=" * 60)

    while True:
        print("\nMENU OPTIONS:")
        print("  1. Start Logging Session (Morning, Midday, or Afternoon)")
        print("  2. Manually Stitch Sessions and Generate End-of-Day Graphs")
        print("  3. Toggle Simulation Mode (Currently: " + ("ON" if simulate else "OFF") + ")")
        print("  4. Exit")
        
        choice = input("\nSelect option (1-4): ").strip()
        
        if choice == "1":
            # 1. Ask for angle
            angle = ""
            while angle not in ["13", "36"]:
                angle = input("Enter tilt angle (13 or 36): ").strip()
                if angle not in ["13", "36"]:
                    print("Invalid choice. Please enter either 13 or 36.")
            
            # 2. Ask for session
            session = ""
            while session not in ["morning", "midday", "afternoon"]:
                session = input("Enter session name (morning, midday, afternoon): ").strip().lower()
                if session not in ["morning", "midday", "afternoon"]:
                    print("Invalid choice. Select morning, midday, or afternoon.")
            
            # 3. Ask for date
            default_date = datetime.datetime.now().strftime("%Y%m%d")
            date_str = input(f"Enter date YYYYMMDD (default: {default_date}): ").strip()
            if not date_str:
                date_str = default_date
            
            # Validate date format
            try:
                datetime.datetime.strptime(date_str, "%Y%m%d")
            except ValueError:
                print("Invalid date format. Using default date instead.")
                date_str = default_date
            
            # 4. Ready trigger
            print(f"\nConfigure Setup: Angle={angle} deg | Session={session} | Date={date_str}")
            if simulate:
                print("Simulation configuration ready.")
            else:
                print(f"Ensure Arduino is wired and sending data to serial port '{port}'.")
            
            input("Press Enter to begin logging...")
            
            # Run session (60 mins)
            serial_logging_session(
                port=port,
                baud=BAUD_RATE,
                angle=int(angle),
                session=session,
                date_str=date_str,
                simulate=simulate,
                sim_speedup=not real_time
            )
            
        elif choice == "2":
            angle = ""
            while angle not in ["13", "36"]:
                angle = input("Enter tilt angle (13 or 36) to stitch: ").strip()
                if angle not in ["13", "36"]:
                    print("Invalid choice. Please enter either 13 or 36.")
            
            default_date = datetime.datetime.now().strftime("%Y%m%d")
            date_str = input(f"Enter date YYYYMMDD (default: {default_date}): ").strip()
            if not date_str:
                date_str = default_date
                
            success = check_and_generate_stitched_graphs(int(angle), date_str)
            if success:
                print(f"[Stitching] Done! Combined curves saved in {GRAPHS_DIR}/ folder.")
            else:
                print("[Stitching] Failed to stitch files. Ensure all three session CSVs exist for that date.")
                
        elif choice == "3":
            simulate = not simulate
            print(f"Simulation Mode toggled. Now: " + ("ON" if simulate else "OFF"))
            
        elif choice == "4":
            print("\nExiting. Thank you!")
            break
        else:
            print("Invalid selection. Please choose an option from 1 to 4.")


if __name__ == "__main__":
    main()
