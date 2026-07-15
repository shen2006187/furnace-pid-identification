# 推送到 GitHub / Gitee 说明

本机当前未检测到 `git` / `gh` 命令。请按下列步骤完成开源发布（任选 GitHub 或 Gitee）。

## GitHub

1. 安装 Git：https://git-scm.com/download/win
2. 在 GitHub 网站新建空仓库，例如 `furnace-pid-identification`（不要勾选自动添加 README）
3. 在本项目目录打开终端，执行：

```bash
cd furnace_pid_identification
git init
git add .
git commit -m "feat: furnace FOPDT identification and PSO-tuned PID control"
git branch -M main
git remote add origin https://github.com/<你的用户名>/furnace-pid-identification.git
git push -u origin main
```

4. 将仓库链接填入实验报告附录。

## Gitee

步骤相同，仅将 remote 改为：

```bash
git remote add origin https://gitee.com/<你的用户名>/furnace-pid-identification.git
```

## 仓库应包含

- `README.md` 运行说明
- `requirements.txt` 依赖
- `data/temperature.csv` 数据
- `src/` 全部源码
- `figures/` 实验结果图
- `report/` 实验报告
- `LICENSE` MIT 协议
