# PlumeEst — Gaussian Atmospheric Dispersion Calculator
#### Video Demo: https://youtu.be/mdzinc5R9xs
#### Description:

## What is PlumeEst?

PlumeEst is a web-based atmospheric dispersion calculator that models how air pollutants travel and spread downwind from an industrial emission source such as a factory chimney, a power plant stack, or a chemical processing facility. Given a set of source parameters — how much the stack emits, how tall it is, the temperature of the exhaust gas — and a set of meteorological conditions — wind speed, wind direction, and atmospheric stability — the application computes a two-dimensional grid of ground-level pollutant concentration values and displays them on an interactive map as a colour-coded heatmap. It also produces downwind centreline and crosswind concentration profiles as charts, calculates a "danger radius" based on WHO air quality guidelines, and generates a short plain-English interpretation of the hazard using Claude, Anthropic's AI model.

The mathematical core is the **Gaussian plume model**, which is the industry-standard approach used by environmental regulatory agencies worldwide — including the US Environmental Protection Agency (EPA) and India's Central Pollution Control Board (CPCB) — for estimating steady-state pollutant concentrations downwind of a continuous point source. It is called "Gaussian" because concentrations in both the horizontal (crosswind) and vertical directions follow a normal (bell-curve) distribution centred on the plume centreline. Combined with the Briggs plume rise equations, which account for the fact that hot exhaust gases rise above the physical stack before dispersing, the model produces concentration estimates that are widely accepted for regulatory and risk-assessment purposes over flat or gently rolling terrain.

The motivation for building PlumeEst was accessibility. Existing tools that implement this science are either expensive commercial packages (AERMOD View, BREEZE) that cost thousands of dollars per licence, or legacy command-line programs (AERMOD, CALINE) that require days of setup, preprocessed meteorological files, and a detailed understanding of file formats. PlumeEst aims to make the same underlying physics usable by anyone with a browser, in under a minute, with no installation required. At the same time, it does not hide what it is doing: the Learn tab presents the full equations, parameter tables, and references so that a curious user can follow every step from input to output.

---

## Project Structure

```
plumeest/
├── app.py
├── engine/
│   ├── plume_core.cpp
│   ├── plume_core.h
│   ├── plume.pyx
│   └── setup.py
├── db/
│   ├── schema.sql
│   └── plumeest.db         (auto-created on first run)
├── static/
│   ├── css/style.css
│   └── js/map.js
└── templates/
    └── index.html
```

---

## File-by-File Description

### `app.py`

`app.py` is the Flask web application and the central coordinator of the entire project. It is responsible for initialising the database, serving the HTML page, processing simulation requests, and returning results.

**Database helpers.** Three small helper functions manage SQLite access. `get_db()` opens a connection with `row_factory = sqlite3.Row`, which means rows can be accessed by column name rather than index. `init_db()` reads `schema.sql` and executes it with `executescript`, which creates all tables and inserts the seed reference data if they do not already exist — this is called once at startup. `get_who_limit(pollutant)` queries the `who_thresholds` table and returns the WHO 24-hour safe limit in µg/m³ for the requested pollutant, returning `None` if the pollutant is not found (the caller falls back to 25 µg/m³, the PM2.5 interim target).

**`save_simulation(params, results)`** inserts a complete simulation record into the `simulations` table, merging the input parameter dictionary and the results dictionary into a single named-parameter SQL `INSERT`. It returns the `lastrowid` so the simulation ID can be included in the API response.

**`grid_to_heatmap(grid, src_lat, src_lon, grid_extent, max_val)`** converts the raw NumPy concentration array into a list of `[lat, lon, intensity]` triples suitable for the Leaflet heatmap plugin. The coordinate conversion uses the approximate relationships: one degree of latitude ≈ 111,320 m, and one degree of longitude ≈ 111,320 m × cos(latitude). Only points whose concentration exceeds 1% of the peak value are included — this threshold was chosen by experimentation to keep the JSON payload under ~50 KB while preserving all visually meaningful detail. Without the threshold, a large grid at low stability can produce over 100,000 points, most of which are essentially zero and invisible on the map.

**`estimate_danger_radius(grid, src_lat, src_lon, grid_extent, who_limit)`** scans every grid cell and finds the one that is farthest from the source while still exceeding the WHO guideline. It converts that distance from metres to kilometres and rounds to two decimal places. If no cell exceeds the limit, it returns `None`, which is displayed to the user as "Within safe limit".

**`build_ai_interpretation(params, results)`** is the function that calls the Anthropic Claude API. It constructs a detailed prompt that includes all simulation inputs (location, pollutant, emission rate, stack geometry, wind conditions, stability class) and all computed outputs (effective stack height, peak concentration, danger radius, WHO limit). The prompt instructs Claude to write 4–6 sentences in a flowing paragraph — no bullet points, no jargon, no clichéd openers — grounding the numbers in the human reality of living near the source. The model used is `claude-sonnet-4-6` with `max_tokens=300`. If the `ANTHROPIC_API_KEY` environment variable is absent, or if the API call raises any exception, `fallback_interpretation` is called instead, which assembles a factual summary from the same data using Python string formatting.

**The `/simulate` route** is where all of the above comes together. It validates that all 14 required JSON fields are present, then calls `effective_stack_height` from the Cython engine to compute how high the plume actually rises above the physical stack (accounting for buoyancy and momentum). It then calls `concentration_grid` to produce the 400×400 µg/m³ array. The grid resolution of 400×400 was chosen as a balance between visual smoothness and compute time — at this resolution, the C++ engine typically finishes in under 50 ms, which is imperceptible to the user. The route then computes the downwind centreline profile (60 points from the source to the grid edge at y=0) and the crosswind profile (60 points spanning ±40% of the grid extent at the downwind distance where the centreline peaks). Both profiles are sampled by calling the single-point `concentration_at_point` function from the engine. Finally, the route calls `build_ai_interpretation`, calls `save_simulation`, and assembles the JSON response.

**The `/history` route** queries the most recent 20 simulation records with a selection of summary columns and returns them as a JSON array. This is intended to power a future history tab in the UI.

---

### `engine/plume_core.cpp` and `engine/plume_core.h`

These two files form the performance-critical compute kernel of PlumeEst. They are written in C++17 and compiled with optimisation flags `-O3`, `-std=c++17`, and `-ffast-math`.

**`sigma_y(x, stability)`** computes the horizontal (crosswind) Pasquill-Gifford dispersion coefficient in metres at downwind distance `x` using the Briggs rural formula: σ_y = a·x·(1 + b·x)^(−0.5). The coefficients `a` and `b` are looked up from a static array indexed by stability class (0=A through 5=F). Class A (extremely unstable) gives the widest spread; class F (moderately stable) the narrowest.

**`sigma_z(x, stability, mixing_height)`** computes the vertical dispersion coefficient using the power-law formula σ_z = c·x^d, then caps the result at 40% of the mixing height. This cap is standard practice in Gaussian modelling: once the plume has spread vertically to fill a significant fraction of the boundary layer, the assumption of unlimited vertical Gaussian spread breaks down, and concentrations near the ground are actually higher than the uncapped formula would suggest (the plume "reflects" off the ground and the inversion layer). The 40% cap is a conservative approximation of this reflection effect.

**`gaussian_concentration(x, y, Q, u, H, stability, mixing_height)`** is the core equation. It returns zero for x ≤ 0 (there is no concentration upwind of a source in this model), raises an exception for non-positive wind speed, and otherwise evaluates:

```
C = (Q × 10⁶) / (π × u × σ_y × σ_z)
      × exp(−y² / (2 × σ_y²))
      × exp(−H² / (2 × σ_z²))
```

The factor of 10⁶ converts emission rate from g/s to µg/s so that the output is in µg/m³. The first exponential term describes the crosswind (lateral) spread; the second describes how concentrations decrease with effective stack height — a taller effective stack means the plume centre is higher above the ground, so ground-level concentrations are lower.

**`compute_grid(Q, u, H, stability, mixing_height, grid_extent, rows, cols, wind_deg, out)`** iterates over every (row, column) index of the output grid. For each cell it computes world coordinates (wx, wy) centred on the source, then rotates them into plume-aligned coordinates (px, py) using the wind direction angle. The wind direction follows meteorological convention: it is the direction the wind is *coming from*, so the plume travels in the opposite direction. The rotation is: px = wx·cos(θ) + wy·sin(θ), py = −wx·sin(θ) + wy·cos(θ), where θ is converted from meteorological degrees to a standard math angle. This is the most performance-sensitive function in the project: at 400×400 resolution it performs 160,000 calls to `gaussian_concentration`, each involving two `exp()` calls and several multiplications.

**`plume_rise(v_s, r, T_s, T_a, u)`** implements the Briggs (1969) plume rise equations. If the stack gas temperature is at or below ambient (a cold or neutral stack), momentum-dominated rise is used: ΔH = 3·F_m / u, where F_m = v_s·r² is the momentum flux. Otherwise, the buoyancy flux F = g·v_s·r²·(T_s − T_a) / T_s is computed, then the final rise distance x_f is determined (x_f = 120·F^0.4 for large fluxes, 49·F^0.625 for small ones), and the final rise is ΔH = 1.6·F^(1/3)·x_f^(2/3) / u.

The reason for implementing this in C++ rather than in Python or NumPy is straightforward: a NumPy implementation of the grid sweep would require allocating several large intermediate arrays (one for σ_y, one for σ_z, one for each exponential term), consuming significant memory and cache bandwidth. The C++ implementation computes each cell's concentration in a tight loop with no heap allocation, which is dramatically faster and more cache-friendly.

---

### `engine/plume.pyx`

`plume.pyx` is the Cython source file that bridges the C++ kernel and Python. Cython is a language that is a superset of Python: it compiles to C, which is then compiled to a native shared library (`plume.so`) that Python can import like any other module.

The file begins by importing NumPy and declaring `cimport numpy` to get access to the C-level array type. It then declares `cdef extern from "plume_core.h"` to tell Cython about the C++ functions it will call, including their signatures and the `nogil` attribute that signals they do not need the Python GIL.

**`concentration_at_point`** is a thin Python wrapper around `gaussian_concentration`. It is used by `app.py` to sample the downwind and crosswind profiles one point at a time.

**`concentration_grid`** allocates a (rows, cols) float64 NumPy array, takes a raw pointer to its data buffer using `<double*>result.data`, and calls `compute_grid` inside a `with nogil:` block. Releasing the GIL during the grid sweep means that in a multi-threaded Flask deployment, other requests can be served while the compute is running. The function then returns the NumPy array to the caller.

**`effective_stack_height`** converts the stack gas and ambient temperatures from °C to Kelvin (by adding 273.15), calls `plume_rise`, and adds the result to the physical stack height.

**`dispersion_coefficients`** exposes `sigma_y` and `sigma_z` as a Python-callable pair, intended for the Learn tab's interactive coefficient explorer.

---

### `engine/setup.py`

`setup.py` uses `setuptools` and `cython.build.cythonize` to compile the extension. It defines a single `Extension` named `plume` with two source files (`plume.pyx` and `plume_core.cpp`), sets the include path to NumPy's header directory and the current directory (so `plume_core.h` can be found), specifies `language="c++"` so that the linker uses the C++ linker, and passes the compiler flags `-O3 -std=c++17 -ffast-math`. The `compiler_directives` passed to `cythonize` disable bounds checking and negative-index wraparound for the Cython layer, giving a small additional speed-up.

---

### `db/schema.sql`

This file defines the full database schema and seeds it with reference data. It uses `CREATE TABLE IF NOT EXISTS` and `INSERT OR IGNORE` throughout, so it is safe to run repeatedly — running it again on an already-initialised database is a no-op.

**`simulations`** is the main log table. It stores the latitude and longitude of the source, all 14 simulation input parameters, and the four computed outputs: effective height, peak concentration, danger radius (NULL if within safe limits), and the full AI interpretation text. The `created_at` column defaults to `CURRENT_TIMESTAMP`.

**`pg_sigma_y`** and **`pg_sigma_z`** store the Briggs rural Pasquill-Gifford dispersion coefficients for all six stability classes. Although these values are also hardcoded in `plume_core.cpp` for performance, keeping them in the database means they are inspectable and could be updated without recompiling the C++ engine — for example, to use urban or offshore coefficient sets. The `label` column in `pg_sigma_y` stores the human-readable class label (A through F) used in the Learn tab.

**`who_thresholds`** stores WHO 2021 Air Quality Guideline values for the five supported pollutants. Each row includes the safe limit (µg/m³), an interim target (a less stringent threshold for countries that cannot yet meet the guideline), and a brief `health_effect` string displayed in the Learn tab's reference table.

---

### `templates/index.html`

`index.html` is the only HTML template in the project. It is a single-page application with three tabs — Input, Results, and Learn — whose visibility is toggled by adding and removing the `active` CSS class via a JavaScript `switchTab` function.

The **Input tab** contains the simulation form with 14 fields grouped into three sections: Source Location (latitude and longitude), Emission Parameters (emission rate, stack height, stack radius, exit velocity, stack temperature, and pollutant type), and Meteorological Conditions (wind speed, wind direction, stability class, mixing height, ambient temperature, and grid extent). Each field has a `<label>`, an `<input>` or `<select>`, and in several cases a `<div class="hint">` that explains what the value means and what range is typical.

The **Results tab** contains four stat cards, a Leaflet map `<div id="map">`, an AI interpretation box, a concentration legend, and two `<canvas>` elements for the Chart.js charts. The stat cards show the danger radius, peak concentration, effective stack height, and wind direction (converted from degrees to a compass bearing string by the `COMPASS` helper in `map.js`).

The **Learn tab** is entirely static content: it presents the three model equations using KaTeX (a fast LaTeX renderer loaded from CDN), a Pasquill-Gifford stability class reference table with colour-coded badges, the WHO air quality guidelines table, and a references list citing Seinfeld & Pandis, the EPA workbook, Briggs (1969), and the WHO 2021 guidelines.

External libraries loaded from CDN include KaTeX, Leaflet 1.9.4, Chart.js 4.4, and the `leaflet.heat` heatmap plugin.

---

### `static/js/map.js`

`map.js` handles all dynamic frontend behaviour. It maintains module-level variables for the Leaflet map object, the heat layer, the danger radius circle, the source marker, and the two Chart.js chart instances — these are kept at module scope so they can be destroyed and re-created when a new simulation runs, rather than accumulating on the map.

The `WHO_LIMITS` object mirrors the database values and is used on the frontend for potential future in-browser limit checks.

The `COMPASS(deg)` helper converts a meteorological wind direction in degrees to a 16-point compass abbreviation (N, NNE, NE, … NNW) by dividing by 22.5 and indexing into a string array.

The **form submission handler** listens for the `submit` event on `#sim-form`, prevents the default browser submission, disables the run button and shows a spinner, collects all field values into a JavaScript object, POSTs it to `/simulate` as JSON, and on success calls `renderResults`. If the server returns an error status, or if the JSON contains an `error` field, it shows an `alert`. The button is re-enabled in a `finally` block regardless of outcome.

**`renderResults(data, params)`** populates the four stat cards, sets the AI interpretation text, switches to the Results tab, invalidates the Leaflet map size (necessary because Leaflet calculates its dimensions when its container is first visible, and it may have been hidden when the map was initialised), and calls `renderMap` and `renderCharts`.

**`renderMap(data, params)`** initialises the Leaflet map on the first call (centred on the source location, zoom level 11, with an OpenStreetMap tile layer), or pans to the new source and removes the previous layers on subsequent calls. It then adds a red `circleMarker` at the source with a popup showing the emission rate, stack height, and pollutant. If the danger radius is non-null, it draws a dashed red `L.circle` at the source with radius equal to the danger radius in metres. Finally, it calls `L.heatLayer` with the heatmap points and a colour gradient from blue (low) through cyan, lime, and yellow to red (high).

**`renderCharts(data)`** creates two Chart.js line charts. Both charts display concentration on the y-axis and distance on the x-axis, and both include a second dataset showing the WHO limit as a dashed red horizontal line. The downwind chart plots concentration from the source to the grid edge along the centreline; the crosswind chart plots concentration laterally at the peak downwind distance. Both charts destroy and replace any previously existing chart instance, preventing the "canvas is already in use" error that occurs if Chart.js tries to initialise on a canvas it already owns.

The final block in the file pre-initialises the Leaflet map on `DOMContentLoaded`, defaulting to Bhubaneswar, Odisha (20.2961°N, 85.8189°E), which is also the default value pre-filled in the form. This ensures the map tile layer loads in the background while the user fills in the form, so the Results tab feels instant when they first switch to it.

---

### `static/css/style.css`

`style.css` contains all visual styling for the application — approximately 400 lines covering layout, typography, colour, form components, result cards, the map container, chart cards, the AI interpretation box, the Learn tab tables and formula cards, and a dark mode block.

The colour system is defined as CSS custom properties on `:root`: `--accent` (#1D9E75, a teal-green), `--accent-dark`, `--accent-light`, `--danger` (red, used for exceedance indicators), `--warn` (amber), four text shades, two background shades, a border colour, a border radius, a body font stack (system sans-serif), and a monospace font stack for formula symbols.

The topbar and tab bar are both `position: sticky` so they remain visible as the user scrolls the content below. The form uses a CSS Grid two-column layout that collapses to a single column below 600px via a `@media` query. Input focus states use a box-shadow ring in a translucent version of the accent colour. The run button has a hover darkening transition and a subtle `scale(0.99)` active state.

The `@media (prefers-color-scheme: dark)` block at the bottom overrides the background, border, and text colours for users whose operating system is in dark mode, adjusts the AI interpretation box to use a dark teal background, and ensures input fields use the dark background.

---

## Design Decisions

**Why a C++/Cython engine rather than pure Python?** The grid sweep at 400×400 resolution requires 160,000 evaluations of the concentration formula, each involving two calls to `exp()` (an expensive transcendental function). A pure Python loop over a NumPy grid takes 2–5 seconds on a typical laptop; the C++ kernel compiled at `-O3 -ffast-math` does it in under 50 ms. The `-ffast-math` flag allows the compiler to reorder floating-point operations and use approximate reciprocal and square root instructions, which is acceptable here because the Gaussian model itself has uncertainty of 30–50% compared to real measurements — sub-1% floating-point accuracy is more than sufficient.

**Why 400×400 and not higher?** At 400×400 the grid is smooth enough that the heatmap looks continuous on screen at zoom level 11. Doubling to 800×800 would quadruple the compute time and quadruple the heatmap payload size, for no perceptible visual improvement. The grid resolution is a parameter that could be increased for high-resolution printing use cases.

**Why SQLite?** The project needs persistent storage so that simulation history can be retrieved. SQLite requires no separate database server process, no configuration, and no credentials — it is a single file. For a project of this scale (a few hundred simulation records at most) it is entirely sufficient. If PlumeEst were deployed as a public multi-user service, migrating to PostgreSQL would be straightforward since the SQL is standard.

**Why the Gaussian model?** The Gaussian plume model is appropriate for flat or gently rolling terrain under steady-state meteorological conditions. More sophisticated models such as AERMOD use hourly meteorological time series, terrain elevation data, and land-use classifications. These models are more accurate but require data that a typical user cannot easily obtain. The Gaussian model needs only the seven parameters that a user can estimate from a weather report and a stack data sheet, making it practical for quick screening assessments, educational use, and sensitivity analysis.

**Why a Learn tab?** Dispersion modelling is not magic — the equations are well understood, publicly documented, and decades old. Including the Learn tab with the full equations, parameter definitions, stability class descriptions, and WHO guidelines makes the tool self-contained and teaches the user what the numbers mean, rather than asking them to trust a black box.

**Why Claude for the AI interpretation?** Numbers alone can be hard to interpret: "peak concentration 312 µg/m³, danger radius 2.3 km" is technically precise but emotionally distant. A well-prompted language model can translate those numbers into something that communicates urgency and human context — "within two kilometres of the stack, the air would carry more than seven times the concentration the WHO considers safe for a single day's breathing" — in a way that a template-generated string cannot. The fallback interpretation ensures the tool remains useful even without an API key.

---

## References

- Seinfeld, J.H. & Pandis, S.N., *Atmospheric Chemistry and Physics*, 3rd ed., Wiley, 2016
- US EPA, *Workbook of Atmospheric Dispersion Estimates*, Publication AP-26, 1970
- Briggs, G.A., *Plume Rise*, USAEC Critical Review Series, 1969
- WHO, *WHO Global Air Quality Guidelines*, 2021
- Claude Sonnet 4.6, Anthropic, 2026
