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
- `game.entities.enemies` 提供敌人基类与 5 种普通敌人子类，房间生成可直接实例化具体敌人
- `game.entities.player` 提供按时间步更新的移动、跳跃与三段普通攻击
- 操作：`A/D` 移动、`Space` 跳跃、`J` 攻击；配合 `W/↑` 或 `S/↓` 可使用上劈与下劈
- 下劈命中敌人后会向上弹起，连续命中可维持滞空
- 初始关卡包含移动、跳跃、基础攻击、上劈、下劈与弹刀的新手引导，完成教学后才会开启房间结算
- `generate_gameplay_assets.py` 可生成战斗原型所需玩家、敌人、首领、投射物、HUD 和奖励素材

## 依赖

依赖已写入 `requirements.txt`。重新安装时执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
