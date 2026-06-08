#include "plume_core.h"
#include <cmath>
#include <stdexcept>

// ---------------------------------------------------------------------------
// Pasquill-Gifford dispersion coefficients (Briggs rural formulas)
// sigma_y and sigma_z as functions of downwind distance x (metres)
// and stability class (0=A, 1=B, 2=C, 3=D, 4=E, 5=F)
// ---------------------------------------------------------------------------

static const double SY_A[2] = {0.22, 0.0001};   // sigma_y = a*x*(1+b*x)^-0.5
static const double SY_B[2] = {0.16, 0.0001};
static const double SY_C[2] = {0.11, 0.0001};
static const double SY_D[2] = {0.08, 0.0001};
static const double SY_E[2] = {0.06, 0.0001};
static const double SY_F[2] = {0.04, 0.0001};

static const double (*SY_PARAMS[6])[2] = {
    (const double(*)[2])SY_A,
    (const double(*)[2])SY_B,
    (const double(*)[2])SY_C,
    (const double(*)[2])SY_D,
    (const double(*)[2])SY_E,
    (const double(*)[2])SY_F
};

// sigma_z power-law coefficients: sigma_z = c * x^d  (capped at mixing height)
static const double SZ_PARAMS[6][2] = {
    {0.20, 0.89},   // A
    {0.12, 0.95},   // B
    {0.08, 0.90},   // C
    {0.06, 0.85},   // D
    {0.03, 0.85},   // E
    {0.016, 0.85}   // F
};

double sigma_y(double x, int stability) {
    if (stability < 0 || stability > 5)
        throw std::invalid_argument("stability class must be 0-5");
    double a = (*SY_PARAMS[stability])[0];
    double b = (*SY_PARAMS[stability])[1];
    return a * x * pow(1.0 + b * x, -0.5);
}

double sigma_z(double x, int stability, double mixing_height) {
    if (stability < 0 || stability > 5)
        throw std::invalid_argument("stability class must be 0-5");
    double c = SZ_PARAMS[stability][0];
    double d = SZ_PARAMS[stability][1];
    double sz = c * pow(x, d);
    // cap at 40% of mixing height (standard practice)
    double cap = 0.4 * mixing_height;
    return sz < cap ? sz : cap;
}

// ---------------------------------------------------------------------------
// Ground-level Gaussian plume concentration (µg/m³)
//
// C(x,y) = Q / (pi * u * sy * sz)
//         * exp(-y^2 / (2 * sy^2))
//         * exp(-H^2 / (2 * sz^2))
//
// x  : downwind distance (m)   — must be > 0
// y  : crosswind distance (m)
// Q  : emission rate (g/s) — converted to µg/s inside
// u  : wind speed at stack height (m/s)
// H  : effective stack height (m)
// ---------------------------------------------------------------------------

double gaussian_concentration(
    double x, double y,
    double Q, double u, double H,
    int stability, double mixing_height)
{
    if (x <= 0.0) return 0.0;
    if (u <= 0.0) throw std::invalid_argument("wind speed must be > 0");

    double sy = sigma_y(x, stability);
    double sz = sigma_z(x, stability, mixing_height);

    if (sy <= 0.0 || sz <= 0.0) return 0.0;

    double Q_ug = Q * 1e6;  // g/s → µg/s

    double C = (Q_ug / (M_PI * u * sy * sz))
             * exp(-0.5 * (y * y) / (sy * sy))
             * exp(-0.5 * (H * H) / (sz * sz));

    return C;
}

// ---------------------------------------------------------------------------
// Grid sweep — evaluates concentration at every (x,y) node on a 2D grid
// centred on the source, rotated to align with wind direction.
//
// Results written into flat row-major array: out[row*cols + col]
// Caller allocates out (size = rows*cols doubles).
//
// grid_extent : half-width/height of grid in metres (grid spans ±extent)
// rows, cols  : grid resolution
// wind_deg    : meteorological wind direction (degrees, 0=N, 90=E …)
//               plume travels IN that direction
// ---------------------------------------------------------------------------

void compute_grid(
    double Q, double u, double H,
    int stability, double mixing_height,
    double grid_extent,
    int rows, int cols,
    double wind_deg,
    double* out)
{
    // Convert met wind direction → math angle (radians)
    // Met: direction wind is COMING FROM. Plume goes the opposite way.
    double wind_rad = (270.0 - wind_deg) * M_PI / 180.0;
    double cos_w = cos(wind_rad);
    double sin_w = sin(wind_rad);

    double dx = (2.0 * grid_extent) / (cols - 1);
    double dy = (2.0 * grid_extent) / (rows - 1);

    for (int r = 0; r < rows; r++) {
        for (int c = 0; c < cols; c++) {
            // World coords centred on source
            double wx = -grid_extent + c * dx;
            double wy =  grid_extent - r * dy;  // top row = +y

            // Rotate into plume-aligned coords
            double px =  wx * cos_w + wy * sin_w;  // downwind
            double py = -wx * sin_w + wy * cos_w;  // crosswind

            out[r * cols + c] = gaussian_concentration(
                px, py, Q, u, H, stability, mixing_height);
        }
    }
}

// ---------------------------------------------------------------------------
// Briggs plume rise (buoyancy-dominated, neutral/unstable atmosphere)
// Returns delta-H (m) to add to physical stack height.
//
// v_s : stack exit velocity (m/s)
// r   : stack radius (m)
// T_s : stack gas temperature (K)
// T_a : ambient temperature (K)
// u   : wind speed (m/s)
// x   : downwind distance for incremental rise (use final-rise formula if 0)
// ---------------------------------------------------------------------------

double plume_rise(double v_s, double r, double T_s, double T_a, double u) {
    const double g = 9.81;
    if (T_s <= T_a) {
        // Momentum-dominated rise (cold or neutral stack)
        double Fm = v_s * r * r;
        return 3.0 * Fm / u;
    }
    // Buoyancy flux F (m^4/s^3)
    double F = g * v_s * r * r * (T_s - T_a) / T_s;
    // Final rise distance xf
    double xf = (F >= 55.0) ? 120.0 * pow(F, 0.4) : 49.0 * pow(F, 0.625);
    // Final rise delta-H
    double dH = 1.6 * pow(F, 1.0/3.0) * pow(xf, 2.0/3.0) / u;
    return dH;
}
