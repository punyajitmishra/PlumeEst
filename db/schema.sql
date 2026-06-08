-- PlumeEst database schema

-- ── Simulations ───────────────────────────────────────────────────────
-- Every run gets saved here with all inputs and key outputs
CREATE TABLE IF NOT EXISTS simulations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Source location
    lat               REAL NOT NULL,
    lon               REAL NOT NULL,

    -- Emission parameters
    emission_rate     REAL NOT NULL,   -- g/s
    stack_height      REAL NOT NULL,   -- m (physical)
    stack_radius      REAL NOT NULL,   -- m
    exit_velocity     REAL NOT NULL,   -- m/s
    stack_temp        REAL NOT NULL,   -- °C
    pollutant         TEXT NOT NULL,

    -- Meteorological inputs
    wind_speed        REAL NOT NULL,   -- m/s
    wind_dir          REAL NOT NULL,   -- degrees
    stability         INTEGER NOT NULL, -- 0=A ... 5=F
    mixing_height     REAL NOT NULL,   -- m
    ambient_temp      REAL NOT NULL,   -- °C
    grid_extent       REAL NOT NULL,   -- m

    -- Computed outputs
    effective_height  REAL,            -- m (after plume rise)
    peak_concentration REAL,           -- µg/m³
    danger_radius_km  REAL,            -- NULL if within safe limit
    ai_interpretation TEXT
);

-- ── Pasquill-Gifford stability parameters ─────────────────────────────
-- Briggs rural sigma_y coefficients: sigma_y = a*x*(1+b*x)^-0.5
CREATE TABLE IF NOT EXISTS pg_sigma_y (
    stability_class   INTEGER PRIMARY KEY,  -- 0=A ... 5=F
    label             TEXT NOT NULL,
    a                 REAL NOT NULL,
    b                 REAL NOT NULL
);

-- Briggs rural sigma_z coefficients: sigma_z = c*x^d
CREATE TABLE IF NOT EXISTS pg_sigma_z (
    stability_class   INTEGER PRIMARY KEY,
    c                 REAL NOT NULL,
    d                 REAL NOT NULL
);

-- ── WHO pollutant thresholds ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS who_thresholds (
    pollutant         TEXT PRIMARY KEY,
    safe_limit_ugm3   REAL NOT NULL,    -- WHO 24-hr guideline
    interim_ugm3      REAL,             -- WHO interim target
    health_effect     TEXT
);

-- ── Seed: PG sigma_y ─────────────────────────────────────────────────
INSERT OR IGNORE INTO pg_sigma_y VALUES (0, 'A', 0.22, 0.0001);
INSERT OR IGNORE INTO pg_sigma_y VALUES (1, 'B', 0.16, 0.0001);
INSERT OR IGNORE INTO pg_sigma_y VALUES (2, 'C', 0.11, 0.0001);
INSERT OR IGNORE INTO pg_sigma_y VALUES (3, 'D', 0.08, 0.0001);
INSERT OR IGNORE INTO pg_sigma_y VALUES (4, 'E', 0.06, 0.0001);
INSERT OR IGNORE INTO pg_sigma_y VALUES (5, 'F', 0.04, 0.0001);

-- ── Seed: PG sigma_z ─────────────────────────────────────────────────
INSERT OR IGNORE INTO pg_sigma_z VALUES (0, 0.20, 0.89);
INSERT OR IGNORE INTO pg_sigma_z VALUES (1, 0.12, 0.95);
INSERT OR IGNORE INTO pg_sigma_z VALUES (2, 0.08, 0.90);
INSERT OR IGNORE INTO pg_sigma_z VALUES (3, 0.06, 0.85);
INSERT OR IGNORE INTO pg_sigma_z VALUES (4, 0.03, 0.85);
INSERT OR IGNORE INTO pg_sigma_z VALUES (5, 0.016, 0.85);

-- ── Seed: WHO thresholds ─────────────────────────────────────────────
INSERT OR IGNORE INTO who_thresholds VALUES ('PM2.5', 15,   25,   'Cardiovascular and respiratory disease');
INSERT OR IGNORE INTO who_thresholds VALUES ('PM10',  45,   75,   'Respiratory irritation');
INSERT OR IGNORE INTO who_thresholds VALUES ('SO2',   40,   125,  'Asthma and lung damage');
INSERT OR IGNORE INTO who_thresholds VALUES ('NOx',   25,   50,   'Airway inflammation');
INSERT OR IGNORE INTO who_thresholds VALUES ('CO',    4000, NULL, 'Oxygen displacement (expressed as µg/m³)');
