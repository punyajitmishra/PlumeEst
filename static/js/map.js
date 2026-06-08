// map.js — handles form submission, map rendering, and results display

let map = null;
let heatLayer = null;
let dangerCircle = null;
let sourceMarker = null;
let downwindChart = null;
let crosswindChart = null;

// WHO 24-hour thresholds in µg/m³ (CO in µg/m³ = mg/m³ * 1000)
const WHO_LIMITS = {
  'PM2.5': 15,
  'PM10':  45,
  'SO2':   40,
  'NOx':   25,
  'CO':    4000
};

const COMPASS = (deg) => {
  const dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE',
                'S','SSW','SW','WSW','W','WNW','NW','NNW'];
  return dirs[Math.round(deg / 22.5) % 16];
};

// ── Tab switching ────────────────────────────────────────────────────
window.switchTab = function(id, el) {
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + id).classList.add('active');
  el.classList.add('active');

  // Leaflet needs a size hint when its container becomes visible
  if (id === 'results' && map) {
    setTimeout(() => map.invalidateSize(), 200);
  }
};

// ── Form submit ──────────────────────────────────────────────────────
document.getElementById('sim-form').addEventListener('submit', async (e) => {
  e.preventDefault();

  const btn = document.getElementById('run-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Running simulation…';

  const payload = {
    lat:           parseFloat(document.getElementById('lat').value),
    lon:           parseFloat(document.getElementById('lon').value),
    emission_rate: parseFloat(document.getElementById('emission_rate').value),
    stack_height:  parseFloat(document.getElementById('stack_height').value),
    stack_radius:  parseFloat(document.getElementById('stack_radius').value),
    exit_velocity: parseFloat(document.getElementById('exit_velocity').value),
    stack_temp:    parseFloat(document.getElementById('stack_temp').value),
    pollutant:     document.getElementById('pollutant').value,
    wind_speed:    parseFloat(document.getElementById('wind_speed').value),
    wind_dir:      parseFloat(document.getElementById('wind_dir').value),
    stability:     parseInt(document.getElementById('stability').value),
    mixing_height: parseFloat(document.getElementById('mixing_height').value),
    ambient_temp:  parseFloat(document.getElementById('ambient_temp').value),
    grid_extent:   parseFloat(document.getElementById('grid_extent').value),
  };

  try {
    const res = await fetch('/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Server error');
    }

    const data = await res.json();
    renderResults(data, payload);

    // Switch to results tab
    switchTab('results', document.querySelectorAll('.tab')[1]);

  } catch (err) {
    alert('Simulation failed: ' + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = 'Run simulation →';
  }
});

// ── Render results ───────────────────────────────────────────────────
function renderResults(data, params) {
  document.getElementById('results-placeholder').style.display = 'none';
  document.getElementById('results-content').style.display = 'block';

  // Stat cards
  document.getElementById('stat-danger-radius').textContent =
    data.danger_radius_km !== null
      ? data.danger_radius_km.toFixed(1) + ' km'
      : 'Within safe limit';

  document.getElementById('stat-peak-conc').textContent =
    data.peak_concentration.toFixed(1) + ' µg/m³';

  document.getElementById('stat-eff-height').textContent =
    data.effective_height.toFixed(0) + ' m';

  document.getElementById('stat-wind-dir').textContent =
    COMPASS(params.wind_dir) + ' (' + params.wind_dir + '°)';

  // AI interpretation
  document.getElementById('ai-text').textContent = data.ai_interpretation;

  // Map
  switchTab('results', document.querySelectorAll('.tab')[1]);
  map.invalidateSize();
  renderMap(data, params);
  renderCharts(data);
}

// ── Leaflet map ──────────────────────────────────────────────────────
function renderMap(data, params) {
  const lat = params.lat;
  const lon = params.lon;

  if (!map) {
    map = L.map('map', { preferCanvas: true }).setView([lat, lon], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18
    }).addTo(map);
  } else {
    map.setView([lat, lon], 11);
    if (heatLayer)   { map.removeLayer(heatLayer);   heatLayer = null; }
    if (dangerCircle){ map.removeLayer(dangerCircle); dangerCircle = null; }
    if (sourceMarker){ map.removeLayer(sourceMarker); sourceMarker = null; }
  }

  map.invalidateSize()

  // Source marker
  sourceMarker = L.circleMarker([lat, lon], {
    radius: 8,
    color: '#E24B4A',
    fillColor: '#E24B4A',
    fillOpacity: 0.9,
    weight: 2
  }).addTo(map).bindPopup(`
    <strong>Emission source</strong><br/>
    Rate: ${params.emission_rate} g/s<br/>
    Stack: ${params.stack_height} m<br/>
    Pollutant: ${params.pollutant}
  `);

  // Danger radius circle
  if (data.danger_radius_km !== null) {
    dangerCircle = L.circle([lat, lon], {
      radius: data.danger_radius_km * 1000,
      color: '#E24B4A',
      fillColor: '#E24B4A',
      fillOpacity: 0.07,
      weight: 1.5,
      dashArray: '6 4'
    }).addTo(map).bindPopup(
      `WHO danger zone: ${data.danger_radius_km.toFixed(1)} km radius`
    );
  }

  // Heatmap points
  // data.heatmap_points: array of [lat, lon, intensity_0_to_1]
  if (data.heatmap_points && data.heatmap_points.length > 0) {
    heatLayer = L.heatLayer(data.heatmap_points, {
      radius: 18,
      blur: 20,
      maxZoom: 13,
      gradient: {
        0.0: 'blue',
        0.3: 'cyan',
        0.5: 'lime',
        0.7: 'yellow',
        1.0: 'red'
      }
    }).addTo(map);
  }
}

function renderCharts(data) {
  // ── Downwind centreline chart ──────────────────────────────────
  const dwCtx = document.getElementById('chart-downwind').getContext('2d');
  if (downwindChart) downwindChart.destroy();

  downwindChart = new Chart(dwCtx, {
    type: 'line',
    data: {
      labels: data.downwind_profile.map(p => (p.x / 1000).toFixed(1) + ' km'),
      datasets: [{
        label: 'Concentration (µg/m³)',
        data: data.downwind_profile.map(p => p.c),
        borderColor: '#1D9E75',
        backgroundColor: 'rgba(29,158,117,0.08)',
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.4
      }, {
        label: 'WHO limit',
        data: data.downwind_profile.map(() => data.who_limit),
        borderColor: '#E24B4A',
        borderWidth: 1.5,
        borderDash: [6, 4],
        pointRadius: 0,
        fill: false
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: true, labels: { font: { size: 11 } } } },
      scales: {
        x: { ticks: { maxTicksLimit: 8, font: { size: 10 } } },
        y: { ticks: { font: { size: 10 } }, beginAtZero: true }
      }
    }
  });

  // ── Crosswind profile chart ────────────────────────────────────
  const cwCtx = document.getElementById('chart-crosswind').getContext('2d');
  if (crosswindChart) crosswindChart.destroy();

  crosswindChart = new Chart(cwCtx, {
    type: 'line',
    data: {
      labels: data.crosswind_profile.map(p => p.y.toFixed(0) + ' m'),
      datasets: [{
        label: 'Concentration (µg/m³)',
        data: data.crosswind_profile.map(p => p.c),
        borderColor: '#6366F1',
        backgroundColor: 'rgba(99,102,241,0.08)',
        borderWidth: 2,
        pointRadius: 0,
        fill: true,
        tension: 0.4
      }, {
        label: 'WHO limit',
        data: data.crosswind_profile.map(() => data.who_limit),
        borderColor: '#E24B4A',
        borderWidth: 1.5,
        borderDash: [6, 4],
        pointRadius: 0,
        fill: false
      }]
    },
    options: {
      responsive: true,
      plugins: { legend: { display: true, labels: { font: { size: 11 } } } },
      scales: {
        x: { ticks: { maxTicksLimit: 8, font: { size: 10 } } },
        y: { ticks: { font: { size: 10 } }, beginAtZero: true }
      }
    }
  });
}
// Pre-initialize map so container is ready before first simulation
document.addEventListener('DOMContentLoaded', () => {
    map = L.map('map', { preferCanvas: true }).setView([20.2961, 85.8189], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 18
    }).addTo(map);
});
