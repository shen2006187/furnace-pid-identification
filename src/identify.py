"""Classical and numerical FOPDT identification methods."""
from __future__ import annotations

from typing import Dict, Tuple

import numpy as np
from scipy.optimize import curve_fit, differential_evolution

from fopdt import FOPDTParams, REFERENCE_FOPDT, fit_metrics, step_response


def load_step_data(csv_path: str) -> Tuple[np.ndarray, np.ndarray, float]:
    import pandas as pd

    df = pd.read_csv(csv_path)
    t = df["time"].to_numpy(dtype=float)
    y = df["temperature"].to_numpy(dtype=float)
    u = float(df["volte"].iloc[0])  # column name in dataset
    return t, y, u


def estimate_y0_yss(y: np.ndarray, n_start: int = 40, n_end: int = 200) -> Tuple[float, float]:
    y0 = float(np.mean(y[:n_start]))
    yss = float(np.mean(y[-n_end:]))
    return y0, yss


def identify_gain(y0: float, yss: float, u_step: float, y_fs: float = 100.0, u_fs: float = 10.0) -> float:
    """Normalized percentage gain used in the course notes."""
    return ((yss - y0) / y_fs) / (u_step / u_fs)


def _time_at_fraction(t: np.ndarray, y: np.ndarray, y0: float, dy: float, frac: float) -> float:
    target = y0 + frac * dy
    idx = int(np.searchsorted(y, target))
    idx = min(max(idx, 1), len(y) - 1)
    # linear interpolation
    y1, y2 = y[idx - 1], y[idx]
    if abs(y2 - y1) < 1e-12:
        return float(t[idx])
    alpha = (target - y1) / (y2 - y1)
    return float(t[idx - 1] + alpha * (t[idx] - t[idx - 1]))


def identify_two_point(
    t: np.ndarray,
    y: np.ndarray,
    u_step: float,
    frac1: float = 0.393,
    frac2: float = 0.632,
) -> FOPDTParams:
    """Classical two-point (两点法) FOPDT identification.

    With relative heights η1, η2 on the S-shaped step curve:
        T = 1.5 (t2 - t1)
        L = 1.5 t1 - 0.5 t2
    which follows from η1≈0.39, η2≈0.63 for FOPDT.
    """
    y0, yss = estimate_y0_yss(y)
    dy = yss - y0
    K = identify_gain(y0, yss, u_step)
    t1 = _time_at_fraction(t, y, y0, dy, frac1)
    t2 = _time_at_fraction(t, y, y0, dy, frac2)
    T = 1.5 * (t2 - t1)
    L = max(0.0, 1.5 * t1 - 0.5 * t2)
    return FOPDTParams(K=K, T=T, L=L, T_room=y0)


def identify_two_point_log(
    t: np.ndarray,
    y: np.ndarray,
    u_step: float,
    frac1: float = 0.393,
    frac2: float = 0.632,
) -> FOPDTParams:
    """Two-point method using the log form of the FOPDT response.

    For y(t) = y0 + K_phys*u*(1 - exp(-(t-L)/T)), eliminating L:
        T = (t2 - t1) / ln((1-η1)/(1-η2))
        L = t1 + T * ln(1 - η1)
    """
    y0, yss = estimate_y0_yss(y)
    dy = yss - y0
    K = identify_gain(y0, yss, u_step)
    t1 = _time_at_fraction(t, y, y0, dy, frac1)
    t2 = _time_at_fraction(t, y, y0, dy, frac2)
    T = (t2 - t1) / np.log((1.0 - frac1) / (1.0 - frac2))
    L = max(0.0, t1 + T * np.log(1.0 - frac1))
    return FOPDTParams(K=K, T=float(T), L=float(L), T_room=y0)


def identify_area_method(t: np.ndarray, y: np.ndarray, u_step: float) -> FOPDTParams:
    """Area / moments method for FOPDT.

    Using the normalized response w(t) = (y-y0)/(yss-y0):
        A0 = ∫(1-w) dt = T + L
        A1 related moments give separate T, L (simplified area form):
        L ≈ t(0.63) - T_est from inflection / area split.
    Here we use a robust practical area split:
        Ta = ∫_0^∞ (1 - w(t)) dt ≈ T + L
        Then find L by matching early area / 63.2% time.
    """
    y0, yss = estimate_y0_yss(y)
    dy = yss - y0
    K = identify_gain(y0, yss, u_step)
    w = (y - y0) / dy
    # truncate where nearly settled
    settled = np.where(w >= 0.995)[0]
    end = int(settled[0]) if len(settled) else len(t) - 1
    tt, ww = t[: end + 1], w[: end + 1]
    # A = ∫(1-w)dt from 0 to ts
    A = float(np.trapz(1.0 - ww, tt))
    t63 = _time_at_fraction(t, y, y0, dy, 0.632)
    # For FOPDT: t63 ≈ L + T, and A ≈ L + T  (exactly A = L+T for infinite horizon)
    # Use tangent-like split: L from 5%~28% rise relative timing
    t28 = _time_at_fraction(t, y, y0, dy, 0.283)
    # Smith: T = 1.5*(t63 - t28), L = t63 - T
    T = 1.5 * (t63 - t28)
    L = max(0.0, t63 - T)
    # Blend with area consistency: T+L should ≈ A
    scale = A / (T + L) if (T + L) > 1e-9 else 1.0
    # mild correction toward area constraint
    T = T * (0.7 + 0.3 * scale)
    L = max(0.0, A - T)
    return FOPDTParams(K=K, T=float(T), L=float(L), T_room=y0)


def identify_nls(
    t: np.ndarray,
    y: np.ndarray,
    u_step: float,
    bounds: Tuple[Tuple[float, float], ...] | None = None,
) -> FOPDTParams:
    """Nonlinear least-squares fit of FOPDT parameters (K, T, L, T_room)."""
    y0_guess, yss = estimate_y0_yss(y)
    K0 = identify_gain(y0_guess, yss, u_step)
    t63 = _time_at_fraction(t, y, y0_guess, yss - y0_guess, 0.632)
    L0 = max(50.0, _time_at_fraction(t, y, y0_guess, yss - y0_guess, 0.05))
    T0 = max(500.0, t63 - L0)

    def model(tt, K, T, L, T_room):
        p = FOPDTParams(K=K, T=T, L=L, T_room=T_room)
        return step_response(p, tt, u_step, y0=T_room)

    if bounds is None:
        bounds = (
            [0.5, 500.0, 0.0, y0_guess - 2.0],
            [1.5, 6000.0, 800.0, y0_guess + 2.0],
        )
    popt, _ = curve_fit(
        model,
        t,
        y,
        p0=[K0, T0, L0, y0_guess],
        bounds=bounds,
        maxfev=20000,
    )
    return FOPDTParams(K=float(popt[0]), T=float(popt[1]), L=float(popt[2]), T_room=float(popt[3]))


def identify_de(t: np.ndarray, y: np.ndarray, u_step: float) -> FOPDTParams:
    """Global search (differential evolution) for FOPDT parameters."""
    y0_guess, yss = estimate_y0_yss(y)

    def cost(vec):
        K, T, L, T_room = vec
        pred = step_response(FOPDTParams(K, T, L, T_room=T_room), t, u_step, y0=T_room)
        return np.mean((pred - y) ** 2)

    bounds = [
        (0.7, 1.2),
        (1500.0, 4500.0),
        (50.0, 500.0),
        (y0_guess - 1.5, y0_guess + 1.5),
    ]
    res = differential_evolution(cost, bounds, seed=42, maxiter=40, polish=True, workers=1)
    K, T, L, T_room = res.x
    return FOPDTParams(K=float(K), T=float(T), L=float(L), T_room=float(T_room))


def evaluate_model(params: FOPDTParams, t: np.ndarray, y: np.ndarray, u_step: float) -> dict:
    pred = step_response(params, t, u_step, y0=params.T_room)
    m = fit_metrics(y, pred)
    # relative error vs reference parameters
    ref = REFERENCE_FOPDT
    m["dK_pct"] = abs(params.K - ref.K) / ref.K * 100.0
    m["dT_pct"] = abs(params.T - ref.T) / ref.T * 100.0
    m["dL_pct"] = abs(params.L - ref.L) / ref.L * 100.0 if ref.L else float("nan")
    m["params"] = params
    m["y_pred"] = pred
    return m


def run_all_identifications(t: np.ndarray, y: np.ndarray, u_step: float) -> Dict[str, dict]:
    methods = {
        "两点法(39.3%/63.2%)": identify_two_point(t, y, u_step),
        "对数两点法": identify_two_point_log(t, y, u_step),
        "面积/Smith法": identify_area_method(t, y, u_step),
        "非线性最小二乘": identify_nls(t, y, u_step),
        "差分进化全局拟合": identify_de(t, y, u_step),
        "课程标准模型(参考)": REFERENCE_FOPDT,
    }
    # use measured room temp for reference comparison curve
    y0, _ = estimate_y0_yss(y)
    methods["课程标准模型(参考)"] = FOPDTParams(
        K=REFERENCE_FOPDT.K, T=REFERENCE_FOPDT.T, L=REFERENCE_FOPDT.L, T_room=y0
    )

    results = {}
    for name, p in methods.items():
        results[name] = evaluate_model(p, t, y, u_step)
    return results
