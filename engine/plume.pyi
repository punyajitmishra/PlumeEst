import numpy as np

def concentration_at_point(
    x: float, y: float,
    Q: float, u: float, H: float,
    stability: int, mixing_height: float
) -> float: ...

def concentration_grid(
    Q: float, u: float, H: float,
    stability: int, mixing_height: float,
    grid_extent: float,
    rows: int, cols: int,
    wind_deg: float
) -> np.ndarray: ...

def effective_stack_height(
    physical_height: float,
    v_s: float, r: float,
    T_s_celsius: float, T_a_celsius: float,
    u: float
) -> float: ...

def dispersion_coefficients(
    x: float, stability: int, mixing_height: float
) -> tuple[float, float]: ...
