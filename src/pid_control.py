"""Discrete PID controller and closed-loop simulation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

import numpy as np

from fopdt import FOPDTParams, FOPDTSimulator


@dataclass
class PIDGains:
    Kp: float
    Ki: float
    Kd: float

    def as_dict(self) -> dict:
        return {"Kp": self.Kp, "Ki": self.Ki, "Kd": self.Kd}


class DiscretePID:
    """Parallel-form PID with anti-windup and filtered derivative."""

    def __init__(
        self,
        gains: PIDGains,
        dt: float,
        u_min: float = 0.0,
        u_max: float = 10.0,
        deriv_filter_n: float = 10.0,
    ):
        self.gains = gains
        self.dt = dt
        self.u_min = u_min
        self.u_max = u_max
        self.deriv_filter_n = deriv_filter_n
        self.integral = 0.0
        self.prev_err = 0.0
        self.d_state = 0.0

    def reset(self):
        self.integral = 0.0
        self.prev_err = 0.0
        self.d_state = 0.0

    def update(self, error: float) -> float:
        # filtered derivative: Kd * N / (1 + N/s) approximation
        n = self.deriv_filter_n
        raw_d = (error - self.prev_err) / self.dt
        alpha = n * self.dt / (1.0 + n * self.dt)
        self.d_state += alpha * (raw_d - self.d_state)
        derivative = self.d_state
        self.prev_err = error
        u_unsat = (
            self.gains.Kp * error
            + self.gains.Ki * self.integral
            + self.gains.Kd * derivative
        )
        u = float(np.clip(u_unsat, self.u_min, self.u_max))
        will_worsen = (u != u_unsat) and (np.sign(error) == np.sign(u_unsat))
        if not will_worsen:
            self.integral += error * self.dt
            u_unsat = (
                self.gains.Kp * error
                + self.gains.Ki * self.integral
                + self.gains.Kd * derivative
            )
            u = float(np.clip(u_unsat, self.u_min, self.u_max))
        return u


def simulate_closed_loop(
    plant: FOPDTParams,
    pid: PIDGains,
    setpoint: float = 35.0,
    t_final: float = 4000.0,
    dt: float = 0.5,
    y0: Optional[float] = None,
    u_min: float = 0.0,
    u_max: float = 10.0,
) -> Dict[str, np.ndarray]:
    if y0 is None:
        y0 = plant.T_room
    n = int(round(t_final / dt)) + 1
    t = np.arange(n) * dt
    y = np.empty(n)
    u = np.empty(n)
    e = np.empty(n)

    sim = FOPDTSimulator(plant, dt)
    sim.reset(y0)
    controller = DiscretePID(pid, dt, u_min=u_min, u_max=u_max)
    controller.reset()

    yi = y0
    for i in range(n):
        err = setpoint - yi
        ui = controller.update(err)
        yi = sim.step(ui)
        t[i] = i * dt
        y[i] = yi
        u[i] = ui
        e[i] = err
    return {"t": t, "y": y, "u": u, "e": e, "setpoint": np.full(n, setpoint)}


def ziegler_nichols_fopdt(params: FOPDTParams) -> PIDGains:
    """Ziegler–Nichols step-response tuning on FOPDT (physical gain).

    Classic reaction-curve (physical units):
        Kp = 1.2 * T / (K_phys * L)
        Ti = 2 L, Td = 0.5 L
        Ki = Kp/Ti, Kd = Kp*Td
    """
    Kp = 1.2 * params.T / (params.K_phys * max(params.L, 1.0))
    Ti = 2.0 * params.L
    Td = 0.5 * params.L
    return PIDGains(Kp=Kp, Ki=Kp / Ti, Kd=Kp * Td)
