"""FOPDT plant model and discrete-time simulation utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np


@dataclass
class FOPDTParams:
    """First-order-plus-dead-time in percentage (normalized) form.

    G(s) = K * exp(-L*s) / (T*s + 1)

    Physical mapping:
        u_pct = u_volt / u_fs * 100
        dy_pct = G * u_pct
        temperature = dy_pct * (y_fs / 100) + T_room
                   = dy_pct + T_room   when y_fs == 100
    """

    K: float
    T: float
    L: float
    y_fs: float = 100.0
    u_fs: float = 10.0
    T_room: float = 16.85

    @property
    def K_phys(self) -> float:
        """Gain from volts to °C."""
        return self.K * self.y_fs / self.u_fs

    def as_dict(self) -> dict:
        return {"K": self.K, "T": self.T, "L": self.L, "T_room": self.T_room}


# Official reference model from the course slides (for comparison only).
REFERENCE_FOPDT = FOPDTParams(K=0.99, T=2895.0, L=190.0, T_room=16.85)


def step_response(
    params: FOPDTParams,
    t: np.ndarray,
    u_volt: float,
    y0: float | None = None,
) -> np.ndarray:
    """Analytic open-loop step response of an FOPDT plant."""
    if y0 is None:
        y0 = params.T_room
    amp = params.K_phys * u_volt
    y = np.full_like(t, y0, dtype=float)
    mask = t >= params.L
    tau = t[mask] - params.L
    y[mask] = y0 + amp * (1.0 - np.exp(-tau / params.T))
    return y


class FOPDTSimulator:
    """Discrete FOPDT simulator with input delay buffer (physical units)."""

    def __init__(self, params: FOPDTParams, dt: float):
        self.params = params
        self.dt = float(dt)
        delay_steps = max(0, int(round(params.L / dt)))
        self.delay_steps = delay_steps
        self.buffer = np.zeros(delay_steps + 1, dtype=float)
        self.x = 0.0  # first-order state = temperature deviation from room

    def reset(self, y0: float | None = None):
        self.buffer[:] = 0.0
        if y0 is None:
            self.x = 0.0
        else:
            self.x = float(y0) - self.params.T_room

    def step(self, u_volt: float) -> float:
        """Advance one sample with voltage input; return temperature (°C)."""
        self.buffer = np.roll(self.buffer, -1)
        self.buffer[-1] = u_volt
        u_delayed = self.buffer[0]
        # Forward Euler / exact discrete equivalent for 1/(Ts+1)
        a = np.exp(-self.dt / self.params.T)
        self.x = a * self.x + (1.0 - a) * self.params.K_phys * u_delayed
        return self.x + self.params.T_room

    def simulate(self, u: np.ndarray, y0: float | None = None) -> np.ndarray:
        self.reset(y0)
        y = np.empty_like(u, dtype=float)
        for i, ui in enumerate(u):
            y[i] = self.step(float(ui))
        return y


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y_true - y_pred) ** 2)))


def mae(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    return float(np.mean(np.abs(y_true - y_pred)))


def fit_metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    err = y_true - y_pred
    ss_res = float(np.sum(err**2))
    ss_tot = float(np.sum((y_true - np.mean(y_true)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return {
        "RMSE": rmse(y_true, y_pred),
        "MAE": mae(y_true, y_pred),
        "MaxAbsErr": float(np.max(np.abs(err))),
        "R2": r2,
    }
