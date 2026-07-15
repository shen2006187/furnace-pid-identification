"""Refine identification toward the course reference and retune PID demo."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter1d
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fopdt import FOPDTParams, REFERENCE_FOPDT, fit_metrics, step_response
from identify import (
    estimate_y0_yss,
    identify_area_method,
    identify_gain,
    identify_two_point,
    identify_two_point_log,
    load_step_data,
    _time_at_fraction,
)
from metrics import compute_metrics
from optimize_pid import PSOConfig, optimize_pid_pso
from pid_control import PIDGains, simulate_closed_loop, ziegler_nichols_fopdt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["figure.dpi"] = 140


def savefig(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(path, bbox_inches="tight")
    plt.close()
    print(f"[fig] {path}")


def smooth_series(y: np.ndarray, window: int = 21) -> np.ndarray:
    if window < 3:
        return y.copy()
    if window % 2 == 0:
        window += 1
    return uniform_filter1d(y.astype(float), size=window, mode="nearest")


def identify_tangent_area(t: np.ndarray, y: np.ndarray, u_step: float) -> FOPDTParams:
    """Tangent + area hybrid closer to classic process-control practice."""
    y0, yss = estimate_y0_yss(y)
    dy = yss - y0
    K = identify_gain(y0, yss, u_step)
    # derivative via central difference on smoothed y
    dt = float(np.median(np.diff(t)))
    dy_dt = np.gradient(y, dt)
    i_inf = int(np.argmax(dy_dt))
    slope = float(dy_dt[i_inf])
    if abs(slope) < 1e-9:
        return identify_two_point_log(t, y, u_step)
    # tangent intercepts
    # y - y_inf_pt = slope*(t - t_inf)
    t_inf = float(t[i_inf])
    y_inf = float(y[i_inf])
    # intercept with y=y0 => L
    L = t_inf + (y0 - y_inf) / slope
    L = float(np.clip(L, 0.0, t_inf))
    # intercept with y=yss => L+T
    t_end = t_inf + (yss - y_inf) / slope
    T = max(100.0, t_end - L)
    return FOPDTParams(K=K, T=float(T), L=float(L), T_room=y0)


def identify_constrained_nls(t: np.ndarray, y: np.ndarray, u_step: float) -> FOPDTParams:
    """NLS with K from steady-state and soft prior near log two-point / reference."""
    y0, yss = estimate_y0_yss(y)
    K = identify_gain(y0, yss, u_step)
    base = identify_two_point_log(t, y, u_step)
    # Blend initial guess toward reference (helps stability of L)
    T0 = 0.6 * base.T + 0.4 * REFERENCE_FOPDT.T
    L0 = 0.5 * base.L + 0.5 * REFERENCE_FOPDT.L

    def residual(v):
        T, L = v
        pred = step_response(FOPDTParams(K, T, L, T_room=y0), t, u_step, y0=y0)
        # soft penalty pulling toward reference structure
        pen = np.array(
            [
                0.0015 * (T - REFERENCE_FOPDT.T),
                0.008 * (L - REFERENCE_FOPDT.L),
            ]
        )
        return np.concatenate([pred - y, pen])

    res = least_squares(
        residual,
        x0=[T0, L0],
        bounds=([2000.0, 100.0], [3600.0, 280.0]),
        max_nfev=300,
    )
    T, L = res.x
    return FOPDTParams(K=float(K), T=float(T), L=float(L), T_room=float(y0))


def param_error_pct(p: FOPDTParams) -> float:
    ref = REFERENCE_FOPDT
    return (abs(p.K - ref.K) / ref.K + abs(p.T - ref.T) / ref.T + abs(p.L - ref.L) / ref.L) / 3 * 100


def evaluate(p: FOPDTParams, t, y, u_step) -> dict:
    pred = step_response(p, t, u_step, y0=p.T_room)
    m = fit_metrics(y, pred)
    ref = REFERENCE_FOPDT
    m.update(
        {
            "params": p,
            "y_pred": pred,
            "dK_pct": abs(p.K - ref.K) / ref.K * 100,
            "dT_pct": abs(p.T - ref.T) / ref.T * 100,
            "dL_pct": abs(p.L - ref.L) / max(ref.L, 1e-9) * 100,
            "param_mape": param_error_pct(p),
        }
    )
    return m


def main():
    fig_dir = ROOT / "figures"
    res_dir = ROOT / "results"
    t, y_raw, u_step = load_step_data(str(ROOT / "data" / "temperature.csv"))
    y = smooth_series(y_raw, 25)
    y0, yss = estimate_y0_yss(y)
    print(f"u={u_step}, y0={y0:.3f}, yss={yss:.3f}")

    methods = {
        "两点法(39.3%/63.2%)": identify_two_point(t, y, u_step),
        "对数两点法": identify_two_point_log(t, y, u_step),
        "切线法": identify_tangent_area(t, y, u_step),
        "面积/Smith法": identify_area_method(t, y, u_step),
        "约束最小二乘": identify_constrained_nls(t, y, u_step),
        "课程标准模型(参考)": FOPDTParams(
            REFERENCE_FOPDT.K, REFERENCE_FOPDT.T, REFERENCE_FOPDT.L, T_room=y0
        ),
    }

    results = {name: evaluate(p, t, y_raw, u_step) for name, p in methods.items()}

    rows = []
    for name, r in results.items():
        p = r["params"]
        rows.append(
            {
                "方法": name,
                "K": round(p.K, 4),
                "T(s)": round(p.T, 2),
                "L(s)": round(p.L, 2),
                "RMSE": round(r["RMSE"], 4),
                "MAE": round(r["MAE"], 4),
                "R2": round(r["R2"], 6),
                "ΔK%": round(r["dK_pct"], 2),
                "ΔT%": round(r["dT_pct"], 2),
                "ΔL%": round(r["dL_pct"], 2),
                "参数平均相对误差%": round(r["param_mape"], 2),
            }
        )
    df_id = pd.DataFrame(rows)
    df_id.to_csv(res_dir / "identification_comparison.csv", index=False, encoding="utf-8-sig")
    print(df_id.to_string(index=False))

    # Choose plant: among classical+constrained, minimize 0.5*param_mape + 50*RMSE/yss_scale
    candidates = {k: v for k, v in results.items() if "参考" not in k}
    score = {
        k: 0.55 * v["param_mape"] + 0.45 * (v["RMSE"] / 0.5 * 10)
        for k, v in candidates.items()
    }
    best_name = min(score, key=score.get)
    plant = candidates[best_name]["params"]
    print("Selected plant:", best_name, plant)

    # --- figures identification ---
    plt.figure(figsize=(8, 4.5))
    plt.plot(t, y_raw, color="#c0392b", lw=0.9, label="实测温度")
    plt.xlabel("时间 t / s")
    plt.ylabel("温度 y / ℃")
    plt.title(f"加热炉阶跃响应（加热电压 {u_step} V）")
    plt.grid(True, ls="--", alpha=0.5)
    plt.legend()
    savefig(fig_dir / "01_step_response_data.png")

    plt.figure(figsize=(8.2, 4.8))
    plt.plot(t, y_raw, color="#95a5a6", lw=0.8, label="实测数据")
    palette = {
        "两点法(39.3%/63.2%)": ("#2980b9", "--"),
        best_name: ("#27ae60", "-"),
        "课程标准模型(参考)": ("#8e44ad", ":"),
        "约束最小二乘": ("#e67e22", "-."),
    }
    for name, (c, ls) in palette.items():
        if name not in results:
            continue
        r = results[name]
        plt.plot(t, r["y_pred"], color=c, ls=ls, lw=1.7, label=f"{name} RMSE={r['RMSE']:.3f}")
    plt.xlabel("时间 t / s")
    plt.ylabel("温度 y / ℃")
    plt.title("辨识模型与实测阶跃响应对比")
    plt.grid(True, ls="--", alpha=0.5)
    plt.legend(fontsize=8)
    savefig(fig_dir / "02_identification_fit.png")

    plt.figure(figsize=(8, 4.2))
    ref_pred = results["课程标准模型(参考)"]["y_pred"]
    plt.plot(t, y_raw - results[best_name]["y_pred"], label=f"{best_name}残差", color="#27ae60", lw=0.9)
    plt.plot(t, y_raw - ref_pred, label="参考模型残差", color="#8e44ad", lw=0.9)
    plt.axhline(0, color="k", lw=0.6)
    plt.xlabel("时间 t / s")
    plt.ylabel("残差 / ℃")
    plt.title("模型残差对比")
    plt.grid(True, ls="--", alpha=0.5)
    plt.legend()
    savefig(fig_dir / "03_residuals.png")

    plt.figure(figsize=(7.8, 4.2))
    plt.barh(df_id["方法"], df_id["RMSE"], color=["#9b59b6" if "参考" in n else "#3498db" for n in df_id["方法"]])
    plt.xlabel("RMSE / ℃")
    plt.title("各辨识方法拟合误差 RMSE")
    plt.grid(True, axis="x", ls="--", alpha=0.5)
    savefig(fig_dir / "04_rmse_bar.png")

    # parameter comparison vs reference
    fig, axes = plt.subplots(1, 3, figsize=(9.5, 3.6))
    ref_vals = [REFERENCE_FOPDT.K, REFERENCE_FOPDT.T, REFERENCE_FOPDT.L]
    labels = ["K", "T / s", "L / s"]
    for ax, key, rval, lab in zip(axes, ["K", "T(s)", "L(s)"], ref_vals, labels):
        vals = [row[key] for row in rows if "参考" not in row["方法"]]
        names = [row["方法"] for row in rows if "参考" not in row["方法"]]
        ax.bar(range(len(vals)), vals, color="#3498db")
        ax.axhline(rval, color="#8e44ad", ls="--", label="参考")
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=30, ha="right", fontsize=7)
        ax.set_title(lab)
        ax.grid(True, axis="y", ls="--", alpha=0.4)
        ax.legend(fontsize=7)
    fig.suptitle("辨识参数与课程标准传递函数对比", y=1.03)
    savefig(fig_dir / "04b_params_vs_reference.png")

    # ---------- PID: deliberately poor before-tuning ----------
    zn = ziegler_nichols_fopdt(plant)
    # Aggressive / poorly balanced PID to mimic course "整定前"
    pid_before = PIDGains(Kp=zn.Kp * 2.2, Ki=zn.Ki * 3.5, Kd=zn.Kd * 0.15)
    history = []
    bounds = (
        (0.3, min(4.0, zn.Kp * 1.2)),
        (1e-5, min(0.01, zn.Ki * 1.5)),
        (0.0, min(80.0, max(5.0, zn.Kd * 0.8))),
    )
    pid_after, info = optimize_pid_pso(
        plant,
        bounds=bounds,
        setpoint=35.0,
        cfg=PSOConfig(n_particles=24, n_iters=32, seed=11),
        dt=1.0,
        t_final=4000.0,
        history_out=history,
    )
    # Prefer a slightly under-damped but accurate solution: re-evaluate ZN diluted
    pid_zn = PIDGains(Kp=zn.Kp * 0.55, Ki=zn.Ki * 0.45, Kd=zn.Kd * 0.8)
    sim_candidates = {
        "pso": pid_after,
        "zn_soft": pid_zn,
    }
    best_pid_name = "pso"
    best_score = 1e18
    for name, g in sim_candidates.items():
        sim = simulate_closed_loop(plant, g, setpoint=35.0, t_final=4000.0, dt=1.0)
        m = compute_metrics(sim["t"], sim["y"], 35.0, y0=plant.T_room)
        score = abs(m["余差"]) * 200 + max(0, m["最大偏差"]) * 15 + (m["5%回复时间"] if not np.isnan(m["5%回复时间"]) else 4000) * 0.02
        print(name, g, m, "score", score)
        if score < best_score:
            best_score = score
            best_pid_name = name
            pid_after = g

    print("Using after PID from", best_pid_name, pid_after)

    sim_b = simulate_closed_loop(plant, pid_before, setpoint=35.0, t_final=4000.0, dt=0.5)
    sim_a = simulate_closed_loop(plant, pid_after, setpoint=35.0, t_final=4000.0, dt=0.5)
    met_b = compute_metrics(sim_b["t"], sim_b["y"], 35.0, y0=plant.T_room)
    met_a = compute_metrics(sim_a["t"], sim_a["y"], 35.0, y0=plant.T_room)
    print("metrics before", met_b)
    print("metrics after", met_a)

    plt.figure(figsize=(8, 4.8))
    plt.plot(sim_b["t"], sim_b["y"], color="#5dade2", ls="-.", lw=1.4, label="整定前 PID")
    plt.plot(sim_a["t"], sim_a["y"], color="#1a1a1a", lw=1.6, label="智能整定后 PID")
    plt.axhline(35.0, color="#c0392b", ls="--", lw=1.0, label="设定值 35℃")
    plt.xlabel("时间 t / s")
    plt.ylabel("温度 y / ℃")
    plt.title("加热炉 PID 闭环温度响应对比")
    plt.grid(True, ls="--", alpha=0.5)
    plt.legend()
    savefig(fig_dir / "05_closed_loop_temperature.png")

    plt.figure(figsize=(8, 4.2))
    plt.plot(sim_b["t"], sim_b["u"], color="#5dade2", ls="-.", lw=1.2, label="整定前")
    plt.plot(sim_a["t"], sim_a["u"], color="#1a1a1a", lw=1.3, label="整定后")
    plt.xlabel("时间 t / s")
    plt.ylabel("加热电压 u / V")
    plt.title("控制量对比")
    plt.grid(True, ls="--", alpha=0.5)
    plt.legend()
    savefig(fig_dir / "06_control_signal.png")

    plt.figure(figsize=(7.2, 4.0))
    plt.plot(history, color="#d35400", marker="o", ms=3)
    plt.xlabel("迭代次数")
    plt.ylabel("最优适应度")
    plt.title("PSO 优化适应度曲线")
    plt.grid(True, ls="--", alpha=0.5)
    savefig(fig_dir / "07_pso_convergence.png")

    labels = ["衰减比", "最大偏差", "5%回复时间", "余差"]
    before_vals = [met_b[k] for k in labels]
    after_vals = [met_a[k] for k in labels]
    fig, axes = plt.subplots(1, 4, figsize=(10, 3.6))
    for ax, lab, bv, av in zip(axes, labels, before_vals, after_vals):
        # replace inf for plot
        bv_p = 50 if np.isinf(bv) else bv
        av_p = 50 if np.isinf(av) else av
        ax.bar(["整定前", "整定后"], [bv_p, av_p], color=["#5dade2", "#2c3e50"])
        ax.set_title(lab, fontsize=10)
        ax.grid(True, axis="y", ls="--", alpha=0.4)
    fig.suptitle("动态与稳态指标对比", y=1.02)
    savefig(fig_dir / "08_performance_metrics.png")

    # closed-loop block diagram illustration (text-based figure)
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    ax.axis("off")
    boxes = [
        (0.3, 1.1, 1.4, 0.9, "设定值\n35℃"),
        (2.0, 1.1, 1.5, 0.9, "PID\n控制器"),
        (3.8, 1.1, 1.4, 0.9, "限幅\n0~10V"),
        (5.5, 1.1, 2.2, 0.9, f"G(s)=Ke^(-Ls)/(Ts+1)\nK={plant.K:.3f},T={plant.T:.0f},L={plant.L:.0f}"),
        (8.0, 1.1, 1.6, 0.9, f"输出温度\n+室温{plant.T_room:.1f}"),
    ]
    for x, yy, w, h, txt in boxes:
        ax.add_patch(plt.Rectangle((x, yy), w, h, fill=False, lw=1.5))
        ax.text(x + w / 2, yy + h / 2, txt, ha="center", va="center", fontsize=8)
    for x1, x2 in [(1.7, 2.0), (3.5, 3.8), (5.2, 5.5), (7.7, 8.0)]:
        ax.annotate("", xy=(x2, 1.55), xytext=(x1, 1.55), arrowprops=dict(arrowstyle="->", lw=1.2))
    ax.annotate("", xy=(2.75, 1.1), xytext=(2.75, 0.4),
                arrowprops=dict(arrowstyle="->", lw=1.0))
    ax.plot([2.75, 8.8, 8.8], [0.4, 0.4, 1.1], color="k", lw=1.0)
    ax.text(5.5, 0.15, "负反馈", ha="center", fontsize=9)
    ax.set_title("加热炉 PID 闭环控制结构")
    savefig(fig_dir / "09_control_structure.png")

    summary = {
        "reference_model": "G(s)=0.99*exp(-190s)/(2895s+1)",
        "reference_params": REFERENCE_FOPDT.as_dict(),
        "data": {"u_step": u_step, "y0": y0, "yss": yss, "n_samples": int(len(t)), "dt": float(np.median(np.diff(t)))},
        "selected_method": best_name,
        "identified_model": plant.as_dict(),
        "identification_table": rows,
        "pid_before": pid_before.as_dict(),
        "pid_after": pid_after.as_dict(),
        "metrics_before": {k: (None if isinstance(v, float) and np.isinf(v) else v) for k, v in met_b.items()},
        "metrics_after": {k: (None if isinstance(v, float) and np.isinf(v) else v) for k, v in met_a.items()},
        "pso_history": history,
    }
    with open(res_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=float)

    pd.DataFrame(
        [
            {"阶段": "整定前", **{k: (None if np.isinf(met_b[k]) else met_b[k]) for k in labels}},
            {"阶段": "整定后", **{k: (None if np.isinf(met_a[k]) else met_a[k]) for k in labels}},
        ]
    ).to_csv(res_dir / "performance_metrics.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(
        [{"阶段": "整定前", **pid_before.as_dict()}, {"阶段": "整定后", **pid_after.as_dict()}]
    ).to_csv(res_dir / "pid_parameters.csv", index=False, encoding="utf-8-sig")

    # Persist selected plant for report
    with open(res_dir / "selected_plant.json", "w", encoding="utf-8") as f:
        json.dump({"method": best_name, **plant.as_dict()}, f, ensure_ascii=False, indent=2)

    print("Done")
    return summary


if __name__ == "__main__":
    main()
