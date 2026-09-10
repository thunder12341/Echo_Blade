# 回响之刃 Echo Blade

一个使用 Python 3.12+ 和 Pygame 2 开发的 2D 像素动作 Roguelike 原型。

## 启动

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

如果 PowerShell 不允许执行脚本，也可以直接运行：

```powershell
.\.venv\Scripts\python.exe main.py
```

## 当前完成

- 1280x720 逻辑画布与可调整窗口
- 使用 `images/` 内像素素材搭建开始界面
- 键盘方向键/WASD 选择，Enter/Space/J 确认
- 鼠标悬停与点击菜单
- 本地排行榜占位窗口
- 设置窗口：音量与辅助模式
- 退出确认提示
- 预留 `save.json` 存档检测，存在有效成绩时启用“继续游戏”

## 依赖

依赖已写入 `requirements.txt`。重新安装时执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
