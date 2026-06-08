# plume.pyx
# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False

import numpy as np
cimport numpy as np
from libc.stdlib cimport malloc, free

cdef extern from "plume_core.h":
    double gaussian_concentration(
        double x, double y,
        double Q, double u, double H,
        int stability, double mixing_height) nogil

    void compute_grid(
        double Q, double u, double H,
        int stability, double mixing_height,
        double grid_extent,
        int rows, int cols,
        double wind_deg,
        double* out) nogil

    double plume_rise(
        double v_s, double r,
        double T_s, double T_a,
        double u) nogil

    double sigma_y(double x, int stability) nogil
    double sigma_z(double x, int stability, double mixing_height) nogil


def concentration_at_point(
        double x, double y,
        double Q, double u, double H,
        int stability, double mixing_height):
    """
    Ground-level concentration (µg/m³) at a single point.
    x          : downwind distance (m), must be > 0
    y          : crosswind distance (m)
    Q          : emission rate (g/s)
    u          : wind speed at stack height (m/s)
    H          : effective stack height (m)
    stability  : Pasquill-Gifford class  0=A ... 5=F
    mixing_height : boundary layer depth (m)
    """
    return gaussian_concentration(x, y, Q, u, H, stability, mixing_height)


def concentration_grid(
        double Q, double u, double H,
        int stability, double mixing_height,
        double grid_extent,
        int rows, int cols,
        double wind_deg):
    """
    Compute a 2-D concentration grid centred on the source.
    Returns a (rows, cols) float64 numpy array of µg/m³ values.
    Q            : emission rate (g/s)
    u            : wind speed (m/s)
    H            : effective stack height (m)
    stability    : 0=A ... 5=F
    mixing_height: boundary layer height (m)
    grid_extent  : half-width of grid (m) — grid spans ±grid_extent
    rows, cols   : grid resolution (e.g. 400x400)
    wind_deg     : meteorological wind direction (degrees, 0=N, 90=E)
    """
    cdef np.ndarray[np.float64_t, ndim=2] result = np.zeros(
        (rows, cols), dtype=np.float64)
    cdef double* ptr = <double*>result.data

    with nogil:
        compute_grid(Q, u, H, stability, mixing_height,
                     grid_extent, rows, cols, wind_deg, ptr)

    return result


def effective_stack_height(
        double physical_height,
        double v_s, double r,
        double T_s_celsius, double T_a_celsius,
        double u):
    """
    Effective stack height = physical height + Briggs plume rise (m).
    Temperatures in °C, converted internally to K.
    """
    cdef double T_s = T_s_celsius + 273.15
    cdef double T_a = T_a_celsius + 273.15
    cdef double dH = plume_rise(v_s, r, T_s, T_a, u)
    return physical_height + dH


def dispersion_coefficients(double x, int stability, double mixing_height):
    """
    Return (sigma_y, sigma_z) in metres for a given downwind distance.
    Useful for the Learn tab's interactive coefficient explorer.
    """
    cdef double sy = sigma_y(x, stability)
    cdef double sz = sigma_z(x, stability, mixing_height)
    return sy, sz

