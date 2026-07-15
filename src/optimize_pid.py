"""Particle Swarm Optimization for PID parameters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, Optional, Tuple

import numpy as np

from fopdt import FOPDTParams
from metrics import compute_metrics
from pid_control import PIDGains, simulate_closed_loop


@dataclass
class PSOConfig:
    n_particles: int = 24
    n_iters: int = 35
    w: float = 0.72
    c1: float = 1.5
    c2: float = 1.5
    seed: int = 42


def pid_cost(
    gains: PIDGains,
    plant: FOPDTParams,
    setpoint: float = 35.0,
    t_final: float = 4000.0,
    dt: float = 1.0,
) -> Tuple[float, dict]:
    """Multi-objective scalarized cost for temperature regulation."""
    sim = simulate_closed_loop(plant, gains, setpoint=setpoint, t_final=t_final, dt=dt)
    m = compute_metrics(sim["t"], sim["y"], setpoint, y0=plant.T_room)
    # Soft constraints / preferred operating region
    overshoot = max(0.0, m["最大偏差"])
    settle = m["5%回复时间"]
    if np.isnan(settle):
        settle = t_final
    residual = abs(m["余差"])
    ise = m["ISE"]
    # Penalty if never settles or large residual
    # penalize control chatter
    du = np.diff(sim["u"])
    chatter = float(np.mean(du**2))
    cost = (
        1.0 * ise / 1e4
        + 35.0 * overshoot
        + 0.015 * settle
        + 250.0 * residual
        + 2.0 * chatter
    )
    return float(cost), m


def optimize_pid_pso(
    plant: FOPDTParams,
    bounds: Tuple[Tuple[float, float], Tuple[float, float], Tuple[float, float]],
    setpoint: float = 35.0,
    cfg: Optional[PSOConfig] = None,
    dt: float = 1.0,
    t_final: float = 4000.0,
    history_out: Optional[list] = None,
) -> Tuple[PIDGains, dict]:
    """PSO search over (Kp, Ki, Kd)."""
    cfg = cfg or PSOConfig()
    rng = np.random.default_rng(cfg.seed)
    lb = np.array([b[0] for b in bounds], dtype=float)
    ub = np.array([b[1] for b in bounds], dtype=float)

    pos = rng.uniform(lb, ub, size=(cfg.n_particles, 3))
    vel = rng.uniform(-0.1, 0.1, size=(cfg.n_particles, 3)) * (ub - lb)

    def eval_row(row):
        g = PIDGains(Kp=float(row[0]), Ki=float(row[1]), Kd=float(row[2]))
        return pid_cost(g, plant, setpoint=setpoint, t_final=t_final, dt=dt)

    pbest = pos.copy()
    pbest_val = np.array([eval_row(p)[0] for p in pos])
    g_idx = int(np.argmin(pbest_val))
    gbest = pbest[g_idx].copy()
    gbest_val = float(pbest_val[g_idx])
    gbest_metrics = eval_row(gbest)[1]

    if history_out is not None:
        history_out.clear()
        history_out.append(gbest_val)

    for _ in range(cfg.n_iters):
        r1 = rng.random((cfg.n_particles, 3))
        r2 = rng.random((cfg.n_particles, 3))
        vel = (
            cfg.w * vel
            + cfg.c1 * r1 * (pbest - pos)
            + cfg.c2 * r2 * (gbest - pos)
        )
        pos = np.clip(pos + vel, lb, ub)
        for i in range(cfg.n_particles):
            val, met = eval_row(pos[i])
            if val < pbest_val[i]:
                pbest_val[i] = val
                pbest[i] = pos[i].copy()
                if val < gbest_val:
                    gbest_val = val
                    gbest = pos[i].copy()
                    gbest_metrics = met
        if history_out is not None:
            history_out.append(gbest_val)

    best = PIDGains(Kp=float(gbest[0]), Ki=float(gbest[1]), Kd=float(gbest[2]))
    info = {"cost": gbest_val, "metrics": gbest_metrics}
    return best, info
