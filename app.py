import os
import sys
import math
import sqlite3
import numpy as np
import anthropic
from flask import Flask, render_template, request, jsonify

# ── Engine import ────────────────────────────────────────────────────
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'engine'))
from plume import concentration_grid, effective_stack_height

app = Flask(__name__)

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
DB_PATH  = os.path.join(BASE_DIR, 'db', 'plumeest.db')
SCHEMA   = os.path.join(BASE_DIR, 'db', 'schema.sql')

# ── Database helpers ─────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create tables and seed reference data if not already present."""
    with get_db() as conn:
        with open(SCHEMA, 'r') as f:
            conn.executescript(f.read())

def get_who_limit(pollutant: str) -> float:
    """Return WHO 24-hr safe limit in µg/m³ for a pollutant."""
    with get_db() as conn:
        row = conn.execute(
            'SELECT safe_limit_ugm3 FROM who_thresholds WHERE pollutant = ?',
            (pollutant,)
        ).fetchone()
    return row['safe_limit_ugm3'] if row else None

def save_simulation(params: dict, results: dict) -> int:
    """Persist a simulation run and return its id."""
    with get_db() as conn:
        cur = conn.execute('''
            INSERT INTO simulations (
                lat, lon,
                emission_rate, stack_height, stack_radius,
                exit_velocity, stack_temp, pollutant,
                wind_speed, wind_dir, stability,
                mixing_height, ambient_temp, grid_extent,
                effective_height, peak_concentration,
                danger_radius_km, ai_interpretation
            ) VALUES (
                :lat, :lon,
                :emission_rate, :stack_height, :stack_radius,
                :exit_velocity, :stack_temp, :pollutant,
                :wind_speed, :wind_dir, :stability,
                :mixing_height, :ambient_temp, :grid_extent,
                :effective_height, :peak_concentration,
                :danger_radius_km, :ai_interpretation
            )
        ''', {**params, **results})
        return cur.lastrowid

# ── Heatmap helpers ──────────────────────────────────────────────────

def grid_to_heatmap(grid: np.ndarray, src_lat: float, src_lon: float,
                    grid_extent: float, max_val: float) -> list:
    """
    Convert concentration grid to Leaflet heatmap points.
    Returns list of [lat, lon, intensity] where intensity is 0–1.
    Only includes points above 1% of peak to keep payload small.
    """
    rows, cols = grid.shape
    points = []
    threshold = max_val * 0.01

    # metres per degree (approximate)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(src_lat))

    dx = (2 * grid_extent) / (cols - 1)
    dy = (2 * grid_extent) / (rows - 1)

    for r in range(rows):
        for c in range(cols):
            val = grid[r, c]
            if val < threshold:
                continue
            # offset in metres from source
            wx = -grid_extent + c * dx
            wy =  grid_extent - r * dy
            pt_lat = src_lat + wy / m_per_deg_lat
            pt_lon = src_lon + wx / m_per_deg_lon
            intensity = min(val / max_val, 1.0)
            points.append([round(pt_lat, 5), round(pt_lon, 5),
                           round(intensity, 3)])

    return points

def estimate_danger_radius(grid: np.ndarray, src_lat: float,
                           src_lon: float, grid_extent: float,
                           who_limit: float) -> float | None:
    """
    Find the furthest point from source that exceeds the WHO limit.
    Returns distance in km, or None if everything is within safe limits.
    """
    rows, cols = grid.shape
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(src_lat))

    dx = (2 * grid_extent) / (cols - 1)
    dy = (2 * grid_extent) / (rows - 1)

    max_dist = 0.0
    found = False

    for r in range(rows):
        for c in range(cols):
            if grid[r, c] > who_limit:
                wx = -grid_extent + c * dx
                wy =  grid_extent - r * dy
                dist = math.sqrt(wx**2 + wy**2)
                if dist > max_dist:
                    max_dist = dist
                    found = True

    return round(max_dist / 1000, 2) if found else None

# ── AI interpretation ────

STABILITY_LABELS = ['A (extremely unstable)', 'B (moderately unstable)',
                    'C (slightly unstable)', 'D (neutral)',
                    'E (slightly stable)', 'F (moderately stable)']

def build_ai_interpretation(params: dict, results: dict) -> str:
    """Call Claude to generate a short poetic interpretation of the simulation."""

    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        # Graceful fallback if key not set
        return fallback_interpretation(params, results)

    pollutant     = params['pollutant']
    wind_speed    = params['wind_speed']
    wind_dir      = params['wind_dir']
    stability_lbl = STABILITY_LABELS[params['stability']]
    emission_rate = params['emission_rate']
    stack_height  = params['stack_height']
    lat           = params['lat']
    lon           = params['lon']

    eff_h       = results['effective_height']
    peak        = results['peak_concentration']
    danger_km   = results['danger_radius_km']
    who_limit   = results['who_limit']

    danger_str = (
        f"{danger_km:.1f} km radius around the source exceeds the WHO "
        f"24-hour safe limit of {who_limit:.0f} µg/m³"
        if danger_km
        else
        f"concentrations remain within WHO safe limits ({who_limit:.0f} µg/m³) "
        f"across the entire simulation area"
    )

    prompt = f"""You are given the results of a Gaussian atmospheric dispersion simulation.
Your task is to write a SHORT, poignant, human passage — 4 to 6 sentences — that
translates these numbers into something a non-scientist can feel and understand.

Do NOT use bullet points, headers, or technical jargon. Write as a single flowing paragraph.
Do NOT start with "The simulation shows" or "The data indicates". Be vivid and direct.
Ground it in the human reality of living near this source. Make the numbers breathe.

SIMULATION INPUTS:
- Location: {lat:.4f}°N, {lon:.4f}°E
- Pollutant: {pollutant}
- Emission rate: {emission_rate} g/s
- Stack height: {stack_height} m (effective height after plume rise: {eff_h:.0f} m)
- Wind: {wind_speed} m/s from {wind_dir}°
- Atmospheric stability: Class {stability_lbl}

COMPUTED RESULTS:
- Peak ground-level concentration: {peak:.1f} µg/m³
- WHO safe limit for {pollutant}: {who_limit:.0f} µg/m³
- Danger zone: {danger_str}

Write the passage now."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        return fallback_interpretation(params, results)


def fallback_interpretation(params: dict, results: dict) -> str:
    pollutant      = params['pollutant']
    wind_speed     = params['wind_speed']
    stability_lbl  = STABILITY_LABELS[params['stability']]
    eff_h          = results['effective_height']
    peak           = results['peak_concentration']
    danger_km      = results['danger_radius_km']
    who_limit      = results['who_limit']

    danger_str = (
        f"concentrations exceed the WHO 24-hour guideline of "
        f"{who_limit:.0f} µg/m³ within a {danger_km:.1f} km radius "
        f"of the source"
        if danger_km
        else
        f"concentrations remain within the WHO 24-hour guideline of "
        f"{who_limit:.0f} µg/m³ across the entire simulation area"
    )

    return (
        f"Under Class {stability_lbl} atmospheric stability and a "
        f"{wind_speed:.1f} m/s wind, {pollutant} {danger_str}. "
        f"The Briggs plume rise equations give an effective stack height "
        f"of {eff_h:.0f} m (accounting for buoyancy and momentum). "
        f"Peak ground-level concentration is {peak:.1f} µg/m³. "
        f"{'Sensitive populations including children and the elderly '
           'are at elevated risk in the affected zone. '
           if danger_km else ''}"
        f"Increasing stack height or reducing emission rate would "
        f"significantly reduce ground-level exposure."
    )

# ── Routes ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/simulate', methods=['POST'])
def simulate():
    try:
        p = request.get_json(force=True)

        # Validate required fields
        required = ['lat','lon','emission_rate','stack_height','stack_radius',
                    'exit_velocity','stack_temp','pollutant','wind_speed',
                    'wind_dir','stability','mixing_height','ambient_temp',
                    'grid_extent']
        for field in required:
            if field not in p:
                return jsonify({'error': f'Missing field: {field}'}), 400

        # ── Compute effective stack height ───────────────────────────
        eff_h = effective_stack_height(
            p['stack_height'],
            p['exit_velocity'],
            p['stack_radius'],
            p['stack_temp'],
            p['ambient_temp'],
            p['wind_speed']
        )

        # ── Run the Gaussian grid ────────────────────────────────────
        GRID_RES = 400   # 400×400 — fast and smooth enough
        grid = concentration_grid(
            p['emission_rate'],
            p['wind_speed'],
            eff_h,
            p['stability'],
            p['mixing_height'],
            p['grid_extent'],
            GRID_RES, GRID_RES,
            p['wind_dir']
        )

        # ── Downwind centreline profile (y=0, x from 100m to grid_extent) ──
        downwind_profile = []
        x_steps = 60
        for i in range(1, x_steps + 1):
            x = (p['grid_extent'] / x_steps) * i
            from plume import concentration_at_point
            c = concentration_at_point(x, 0.0, p['emission_rate'],
                                    p['wind_speed'], eff_h,
                                    p['stability'], p['mixing_height'])
            downwind_profile.append({'x': round(x, 1), 'c': round(float(c), 2)})

        # ── Crosswind profile at peak downwind distance ─────────────────────
        peak_x = max(downwind_profile, key=lambda p: p['c'])['x']
        crosswind_profile = []
        y_steps = 60
        y_extent = p['grid_extent'] * 0.4
        for i in range(-y_steps // 2, y_steps // 2 + 1):
            y = (y_extent / (y_steps // 2)) * i
            c = concentration_at_point(peak_x, y, p['emission_rate'],
                                    p['wind_speed'], eff_h,
                                    p['stability'], p['mixing_height'])
            crosswind_profile.append({'y': round(y, 1), 'c': round(float(c), 2)})

        peak = float(grid.max())

        # ── WHO limit lookup ─────────────────────────────────────────
        who_limit = get_who_limit(p['pollutant']) or 25.0

        # ── Danger radius ────────────────────────────────────────────
        danger_km = estimate_danger_radius(
            grid, p['lat'], p['lon'], p['grid_extent'], who_limit
        )

        # ── Heatmap points ───────────────────────────────────────────
        heatmap_points = grid_to_heatmap(
            grid, p['lat'], p['lon'], p['grid_extent'], peak
        )

        results = {
            'effective_height':    round(eff_h, 1),
            'peak_concentration':  round(peak, 2),
            'danger_radius_km':    danger_km,
            'who_limit':           who_limit,
        }

        # ── AI interpretation ────────────────────────────────────────
        ai_text = build_ai_interpretation(p, results)
        results['ai_interpretation'] = ai_text

        # ── Save to DB ───────────────────────────────────────────────
        sim_id = save_simulation(p, results)

        return jsonify({
            'sim_id':             sim_id,
            'effective_height':   results['effective_height'],
            'peak_concentration': results['peak_concentration'],
            'danger_radius_km':   results['danger_radius_km'],
            'ai_interpretation':  ai_text,
            'heatmap_points':     heatmap_points,
            'downwind_profile':  downwind_profile,
            'crosswind_profile': crosswind_profile,
            'who_limit':         who_limit,
        })

    except Exception as ex:
        return jsonify({'error': str(ex)}), 500


@app.route('/history')
def history():
    """Return last 20 simulation runs — useful for future history tab."""
    with get_db() as conn:
        rows = conn.execute('''
            SELECT id, created_at, lat, lon, pollutant,
                   peak_concentration, danger_radius_km
            FROM simulations
            ORDER BY created_at DESC
            LIMIT 20
        ''').fetchall()
    return jsonify([dict(r) for r in rows])


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
