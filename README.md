# 游戏助手 · Game Assistant

一个常驻桌面的 AI 游戏助手。游戏里喊一声，它**看见你的画面**、查攻略、答疑，然后**说给你听**。

[![CI](https://github.com/longxiansheng0/game-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/longxiansheng0/game-assistant/actions/workflows/ci.yml)

![悬浮球](docs/images/orb.png)

## 它能做什么

- **语音对话**：按 `F8` 说一句话，说完静音自动结束，识别 → 截图 → 回答 → 朗读一条龙。
- **通话模式**：麦克风常开，喊「小助手，这 BOSS 怎么打」一句话就能触发，先回你一句「主人，我在」再答题。
- **看得见画面**：抓当前窗口所在屏幕，压缩后交给视觉模型；同时用 OCR 把原分辨率下的小字（任务名、装备属性、BOSS 全名）认出来，避免模型猜。
- **会查攻略**：不确定的时候自己调 DeepSeek 搜索接口查，答案带来源。
- **随时打断**：它还在念的时候按一次热键，立刻闭嘴听你说。
- **桌宠**：眼睛跟着鼠标转，会眨眼、发呆瞟人，悬停会睁大，按下有回弹。
- **对话记录**：每次问答存本地，右键能翻、能清空。
- **配置全在界面里**：Key、音色、语速、快捷键、球大小，改完立即生效。

![悬浮球状态](docs/images/pet.png)

## 快速开始

### 系统要求

- Windows 10 / 11（用到 Win32 全局热键和抓屏，暂不支持其他系统）
- 不需要独立显卡：识别跑在 CPU，模型推理在云端

### 方式一：安装包

从 [Releases](https://github.com/longxiansheng0/game-assistant/releases/latest) 下载 `GameAssistant-Setup-1.0.0.exe`，双击安装。

按用户装到 `%LOCALAPPDATA%\Programs\GameAssistant`，不需要管理员权限，安装包内含离线语音模型。

装完第一次打开会弹设置窗，填上 DeepSeek 的 API Key 就能用。

### 方式二：从源码跑

```bash
git clone https://github.com/longxiansheng0/game-assistant.git
cd 游戏助手
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
双击 启动.bat        # 或 .venv\Scripts\python run.py
```

首次使用语音时会下载 whisper 模型（约 250MB，走 hf-mirror 镜像），只需一次。

Key 在 [platform.deepseek.com](https://platform.deepseek.com) 申请。推荐 `deepseek-flash`，它是目前唯一支持读图的模型。

## 怎么用

| 操作 | 说明 |
|---|---|
| `F8` / 右键球「对话」 | 说一句话，静音 0.8 秒后自动结束 |
| `Ctrl+F2` | 打开文字输入框 |
| 说话中再按 `F8` | 提前结束，立刻开始识别 |
| 它朗读时按 `F8` | 打断播报 |
| 拖球 | 换位置，退出时记住 |
| 拖气泡边框 / 右下角 | 改气泡大小 |
| 右键小球 | 对话 / 历史记录 / 设置 / 语音输入 / 朗读回答 / 通话模式 / 开机自启 / 退出 |
| 托盘图标 | 双击打开对话，右键同一套菜单 |

快捷键可以在「设置 → 快捷键」里改，点进输入框直接按组合键（支持 Ctrl / Alt / Shift / Win + 字母 / 数字 / F1~F24）。

![设置](docs/images/settings.png)

## 它是怎么工作的

```
热键/唤醒词 ──► 麦克风 ──► VAD 断句 ──► whisper 识别
                  │                        │
                  └─► 抓屏 ──► OCR          │
                              │            │
                              ▼            ▼
                    图 + 屏幕文字 + 问题 → DeepSeek
                                          │
                              ┌───────────┴───────────┐
                              ▼                       ▼
                         气泡逐字显示             按句合成 → 播放
```

关键设计：**抓屏和 OCR 跟你说话并行**，所以它们再慢也不占等待时间。实测 3.3 秒的提问，说完到第一声约 5.2 秒。

更细的线程模型、启动顺序、延迟分解见 [docs/运行说明.md](docs/运行说明.md)，选型取舍见 [docs/架构设计.md](docs/架构设计.md)。

## 配置

全部在「右键小球 → 设置」里，改完立即生效。也可以直接改 `config/settings.json`，字段说明见 [config/settings.example.json](config/settings.example.json)。

## 打包

```bash
# 单目录程序（onedir），不是单文件：单文件每次启动要解压 900MB，冷启动十几秒
.venv\Scripts\pyinstaller --noconfirm build.spec
cp -r config models dist/GameAssistant/
cp packaging/使用说明.txt dist/GameAssistant/

# 安装包（需要 Inno Setup 6）
"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" installer.iss
```

## 项目结构

```
app/
  main.py        装配 + 状态机 + 后台线程
  core/          提示词、工具循环、对话记录
  llm/           DeepSeek 客户端（对话 / 流式 / 搜索 / 抓取）
  vision/        抓屏、OCR、游戏识别
  voice/         录音、ASR、TTS、唤醒词
  ui/            悬浮球、气泡、设置窗、历史窗、热键
docs/            架构、运行说明、功能介绍
tools/           自测和预览脚本（不参与运行）
```

## 已知限制

- **独占全屏的游戏盖不上任何窗口**，请把游戏设成「无边框窗口 / 窗口化全屏」。
- 识别跑在 CPU，RTF ≈ 0.42：问 10 秒的话要等 4 秒左右。
- 通话模式的唤醒词靠 whisper 判断，游戏声外放会误触发，建议戴耳机。
- 只有单帧视觉，没有连续画面跟踪。

## 免责声明

本项目**只做只读截屏**，不注入 DLL、不 hook、不模拟键鼠。
但部分竞技游戏（无畏契约、CS2、三角洲等）对任何形式的覆盖层都敏感，**使用前请自行评估账号风险**，作者不承担任何后果。

## 致谢

- [DeepSeek](https://platform.deepseek.com/) 提供视觉理解和联网搜索
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 本地语音识别
- [RapidOCR](https://github.com/RapidAI/RapidOCR) 屏幕文字识别
- [edge-tts](https://github.com/rany2/edge-tts) 语音合成
- [Inno Setup](https://jrsoftware.org/isinfo.php) 简体中文语言包来自 [jrsoftware/issrc](https://github.com/jrsoftware/issrc)

## License

[MIT](LICENSE)