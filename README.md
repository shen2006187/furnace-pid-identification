# 加热炉系统辨识与 PID 智能整定

控制系统的智能辨识与参数优化（任务2）完整开源实现。

## 标准参考模型（仅作对比）

课程给出的加热炉对象参考传递函数为：

$$
G(s)=\frac{0.99\,e^{-190s}}{2895s+1}
$$

其中增益按百分比信号定义（$y_{F.S}=100$，$u_{F.S}=10$）。**本仓库不直接使用该模型作为控制对象**，而是从 `temperature.csv` 进行系统辨识，再与该标准模型对比验证。

## 功能

1. **系统辨识**：两点法、对数两点法、切线法、面积/Smith 法、约束最小二乘
2. **模型验证**：RMSE / MAE / R²、残差曲线、相对标准传递函数的参数误差
3. **PID 闭环控制**：设定值 35℃，控制量限幅 0~10 V
4. **智能整定**：粒子群算法（PSO）优化 $K_p,K_i,K_d$
5. **指标分析**：衰减比、最大偏差、5% 回复时间、余差
6. **实验报告**：自动生成 Word 报告

## 环境

- Python 3.9+
- 依赖见 `requirements.txt`

```bash
pip install -r requirements.txt
```

## 快速复现

```bash
# 1) 运行辨识 + PID 优化 + 出图
python src/run_experiment.py

# 2) 生成 Word 实验报告
python src/generate_report.py
```

结果输出：

- `figures/` 全部实验图片
- `results/` CSV / JSON 数值结果
- `report/` 实验报告 `.docx`

## 数据说明

`data/temperature.csv` 字段：

| 列名 | 含义 | 单位 |
|------|------|------|
| time | 时间 | s |
| temperature | 炉温 | ℃ |
| volte | 加热电压（数据集原始拼写） | V |

阶跃电压为 3.5 V，采样约 0.5 s。

## 目录结构

```
furnace_pid_identification/
├── data/temperature.csv
├── src/
│   ├── fopdt.py            # FOPDT 模型与仿真
│   ├── identify.py         # 辨识算法
│   ├── pid_control.py      # PID 与闭环
│   ├── optimize_pid.py     # PSO 整定
│   ├── metrics.py          # 动/稳态指标
│   ├── run_experiment.py   # 主实验入口
│   └── generate_report.py  # 报告生成
├── figures/
├── results/
├── report/
├── requirements.txt
└── README.md
```

## 典型辨识结果（相对参考模型）

在提供的数据集上，约束最小二乘辨识结果通常满足：

- $\Delta K \approx 1\%$
- $\Delta T \approx 5\sim8\%$
- $\Delta L \approx 5\sim15\%$
- 平均参数相对误差约 **5%** 量级
- 对实测曲线 RMSE 低于直接使用参考模型的 RMSE

具体数值以 `results/identification_comparison.csv` 为准。

## License

MIT
