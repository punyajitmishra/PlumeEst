#pragma once

double sigma_y(double x, int stability);
double sigma_z(double x, int stability, double mixing_height);

double gaussian_concentration(
    double x, double y,
    double Q, double u, double H,
    int stability, double mixing_height);

void compute_grid(
    double Q, double u, double H,
    int stability, double mixing_height,
    double grid_extent,
    int rows, int cols,
    double wind_deg,
    double* out);

double plume_rise(double v_s, double r, double T_s, double T_a, double u);
