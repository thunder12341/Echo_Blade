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
- 完成新手教程后进入灰塔大厅；大厅通过远征城门、铸刃师、远征档案和回响中枢提供交互入口
- 每局结算后返回大厅并获得回响遗晶，可在回响中枢激活带前置条件的局外强化节点
- 回响中枢支持键盘和鼠标选择节点，展示解锁门槛、消耗、效果和激活状态
- `generate_gameplay_assets.py` 可生成战斗原型所需玩家、敌人、首领、投射物、HUD 和奖励素材
- `sounds/` 内含大厅与战斗两首循环背景音乐，以及脚步、跳跃、冲刺、挥刀、命中、敌人起手、受击、弹刀等 16 个音效
- 进入关卡（含新手教学关卡）自动交叉淡化到战斗音乐，返回菜单、大厅与结算界面恢复大厅音乐
- 音乐与音效分总线混音：战斗音乐让出确认感频段，弹刀、命中、受击会短暂压低音乐
- `generate_audio_assets.py` 可重新生成全部音乐与音效（纯 Python 标准库），支持 `--preview` 试听
- 音频规格与触发映射见 `audio_design.md`
- 闪避（`L` / `Shift`）：约 70px 位移，0.3 秒内置冷却，冲刺期间无敌，并留下青色残影拖尾
- 完美弹刀提示：近战敌人命中前 0.3 秒亮起金色闪光，闪光期间按 `K` 即为完美弹刀
- 远程弹刀：子弹进入角色身边约 170px 范围内按 `K` 即可弹开，未弹开则命中扣血

## 依赖

依赖已写入 `requirements.txt`。重新安装时执行：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
