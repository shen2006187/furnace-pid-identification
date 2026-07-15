"""Dynamic / steady-state performance indices used in the course."""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np


def compute_metrics(
    t: np.ndarray,
    y: np.ndarray,
    setpoint: float,
    y0: Optional[float] = None,
    band: float = 0.05,
) -> Dict[str, float]:
    """Compute decay ratio, max deviation, 5% recovery time, residual.

    Definitions aligned with process-control teaching materials:
    - 最大偏差: first peak deviation from setpoint (signed for overshoot
      above setpoint; reported as absolute peak error from setpoint).
    - 衰减比: |B|/|A| inverted form as A/B where A is first peak overshoot
      amplitude and B second peak overshoot amplitude relative to setpoint
      (course table uses values >1, i.e. first/second).
    - 5%回复时间: first time after which |y-setpoint| stays within
      5% of the step magnitude |setpoint - y0|.
    - 余差: y(infty) - setpoint (steady-state error; course shows residual
      of tracking, sometimes reported as setpoint - yss).
    """
    if y0 is None:
        y0 = float(y[0])
    step_mag = abs(setpoint - y0)
    if step_mag < 1e-9:
        step_mag = 1.0

    # find peaks relative to setpoint (overshoot side)
    # use simple local maxima on y
    peaks_idx = []
    for i in range(1, len(y) - 1):
        if y[i] >= y[i - 1] and y[i] > y[i + 1] and y[i] > setpoint:
            peaks_idx.append(i)
    # keep significant separated peaks
    filtered = []
    min_sep = max(5, int(0.02 * len(y)))
    for idx in peaks_idx:
        if not filtered or idx - filtered[-1] >= min_sep:
            filtered.append(idx)
    peaks_idx = filtered

    if len(peaks_idx) >= 1:
        y1 = float(y[peaks_idx[0]])
        max_dev = y1 - setpoint
        A = abs(y1 - setpoint)
    else:
        # maybe undershoot-only; use max abs error after rise
        max_dev = float(np.max(y) - setpoint)
        A = abs(max_dev)

    if len(peaks_idx) >= 2:
        y2 = float(y[peaks_idx[1]])
        B = abs(y2 - setpoint)
        decay_ratio = A / B if B > 1e-6 else float("inf")
    else:
        decay_ratio = float("inf") if A > 0 else float("nan")

    # 5% recovery / settling
    tol = band * step_mag
    within = np.abs(y - setpoint) <= tol
    settle_time = float("nan")
    # find first index such that all remaining samples are within band
    for i in range(len(y)):
        if np.all(within[i:]):
            settle_time = float(t[i])
            break

    y_inf = float(np.mean(y[int(0.9 * len(y)) :]))
    residual = y_inf - setpoint  # course example showed negative before tuning

    return {
        "衰减比": float(decay_ratio),
        "最大偏差": float(max_dev),
        "5%回复时间": float(settle_time),
        "余差": float(residual),
        "峰值温度": float(np.max(y)),
        "稳态温度": y_inf,
        "IAE": float(np.trapz(np.abs(y - setpoint), t)),
        "ISE": float(np.trapz((y - setpoint) ** 2, t)),
    }
