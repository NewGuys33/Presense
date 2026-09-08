# Presense — PreSense V0

Understand before they finish speaking.

这是按照《第一版代码-realtime-caption.txt》开始实现的 PC 软件原型。
当前版本为 **0.1.0 开发版**，已经实现预测层与底座接线，尚未完成 Windows 实机验收。

## 当前成果

- `Confirmed / Live / Prediction` 三种状态及对应中文翻译。
- 30–60 秒滚动原文上下文（默认 60 秒；另设条数上限控制请求体积）。
- 冷启动时只翻译，具备历史原文且超过 5 秒后才允许预测。
- OpenAI 语义预测调用、推测主题/关键概念/近期观点、保守空预测。
- 输入变化后丢弃旧模型响应；预测 4 秒过期；Live 15 秒无更新清空。
- 最终 ASR 到来立即清除预测，Confirmed 只取最终识别原文。
- 保留原项目 WASAPI 音频采集、Whisper 最终识别与 OpenAI/DeepL 翻译。
- 独立三栏桌面窗口；沿用 8765 端口输出 WebSocket；重连发送最新状态。
- 演示模式、14 项自动测试、Windows 安装和启动脚本。

**演示是固定脚本，不代表真正提前预测成功。** 已经写好真实模型接口，但本次没有使用真实 API key，也没有 Windows 音频设备。

## 底座与源码组织

采用与需求中功能描述吻合的候选底座：
[ShigetoshiMizuno/realtime-caption](https://github.com/ShigetoshiMizuno/realtime-caption)。
需求及可检索历史没有完整 owner/repo；如果你之前下载的是另一个同名项目，需要更换适配器。

固定源码提交：`225454eb44f1ab6d5468e978b256b8767e5b760b`。

本项目作为增量层保存；不把上游完整源码混入本项目压缩包。
`bootstrap.py` 会下载固定提交到 `vendor/realtime-caption/`，校验 `main.py` 的 Git blob SHA，
然后生成 `presense_upstream.py`。原始 `main.py` 保留供基线测试。
生成文件唯一的源码补丁位于 recorder 初始化参数：启用实时识别，设置 Live 模型、刷新间隔和回调。
`presense/runtime.py` 子类接收最终 ASR 与 Live 事件，并接入预测层。

基于 [RealtimeSTT 官方实时转录接口](https://github.com/KoljaB/RealtimeSTT/blob/master/RealtimeSTT/audio_recorder.py)，
使用 `on_realtime_transcription_update` 获取未完成字幕。

## 先看演示（无需 API key）

电脑安装 Python 3.11 x64，解压后在 Presense 文件夹打开 PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-demo.txt
.\.venv\Scripts\python.exe run_presense.py --demo
```

你会看到：已确认上下文 → 当前未完成句 → 灰色推测 → 实际内容到来并替换推测。
该脚本故意让最后说出的内容与预测不同，以验证删除和替换路径。

无界面运行：

```powershell
.\.venv\Scripts\python.exe run_presense.py --demo --headless --seconds 8
```

## Windows 真实音频模式

1. 安装 Python 3.11 x64。项目路径建议 `C:\Projects\Presense`。
2. 双击 `setup_presense.bat`。它创建虚拟环境、下载固定版本底座并安装上游依赖。
   初次下载模型和依赖可能较大；看到明确的完成提示后再继续。
3. 编辑新生成的 `config.yaml`，在自己的电脑填写 `openai.api_key`。
   预测使用 OpenAI，因此只填 DeepL key 不足以开启预测。
   默认是英语输入、中文翻译、CPU int8、small 最终模型和 tiny.en Live 模型。
   API key 只保存在你的本地配置，不需要发到聊天。
4. **先验收原版基线**：从本项目根目录执行下方命令，按原版 CLI 选择输出设备对应的 Loopback。
   确认电脑播放的视频能产生原文和中文，再进行下一步。

```powershell
.\.venv\Scripts\python.exe vendor\realtime-caption\main.py
```

5. 原版关闭后，双击 `start_presense.bat`，在控制台输入对应 Loopback 的设备编号。
   选择实际播放声音的耳机/扬声器设备，不要选择麦克风。
   或先列出设备，再指定编号启动：

```powershell
.\.venv\Scripts\python.exe run_presense.py --list-devices
.\.venv\Scripts\python.exe run_presense.py --device 25
```

`25` 只是命令格式示例，必须改成当前电脑列出的设备编号。

6. 播放一段英语课程，等到“系统音频已就绪”。确认 Live 在一句话结束前更新。
7. 播放数句建立上下文，观察 Prediction 是否在后半句说出前出现。
8. 点击“停止 / Stop”关闭；换设备或跳转到新主题后重启程序清空会话。

OpenAI 与 DeepL 的调用会把相应文本发送给选择的服务。Whisper 音频识别留在本机。
无需音频上传到预测接口；它只接收最近原文与当前 Live。

## 验收清单

| 目标 | 本次状态 | Windows 实机验收 |
|---|---|---|
| G1 系统音频 | 保留上游 WASAPI，未实测 | 连续播放视频 5 分钟，确认原文稳定产生 |
| G2 未完成 ASR | 已启用回调；真实源码回调契约测试通过 | 句子结束前出现 Live，记录延迟 |
| G3 中文翻译 | 保留原文翻译；新增 Live 翻译调用 | 术语、否定词、数字及未完成句翻译正确 |
| G4 提前语义预测 | 代码接口完成；真实模型未验收 | 记录预测显示时间与实际后半句开始时间 |
| G5 修正/删除 | 状态测试、异步旧结果测试及脚本演示通过 | 后续说出不同内容时，旧预测及时消失 |

V0 的全部验收尚未完成。下一步优先进行 G1→G2 实机测试，再验证 G3→G5。

## 当前限制

- 必须 Windows 10/11 才能使用真实 WASAPI 音频路径。
- 本次未执行依赖完整安装、模型下载、真实 OpenAI/DeepL 请求或桌面窗口视觉测试。
- 原始上游依赖使用版本范围；固定了源码提交，但还没有形成 Windows 实测依赖锁文件。
- Live 更新快于模型返回时，该结果会因过期而丢弃，可能暂时没有预测。这是目前优先保证字幕状态正确的取舍，后续需实测调整模型与刷新间隔。
- G5 当前使用“最终 ASR 覆盖并清空预测”，不输出模型猜测的准确率，也不声称已实现语义等价自动评分。
- 主题和概念来自模型临时推断；预测和推断摘要不会回流为确认原文。
- 仅展示最近一条 Confirmed；上下文仍保留最近窗口内的真实原文。
- 暂不包含 OCR、画面、ESP32、PCB、手机 App、账号或云后端。

## WebSocket 协议

地址默认 `ws://127.0.0.1:8765`。`confirmed/live/prediction` 始终是英文原文层；
三个 `*_translation` 字段为中文翻译层。`original/translated` 是兼容原版输出的最新 Confirmed 对。
客户端按会话 `session_id` 和递增 `sequence` 接收最新完整快照，不累加相同句子。
网络断开时客户端应清空 Prediction。V0 默认仅限本机，未来接 ESP32 时再增加局域网配置。

```json
{
  "protocol": "presense.v0",
  "session_id": "session-id",
  "sequence": 4,
  "revision": 2,
  "confirmed": "Increasing alpha delays conduction.",
  "confirmed_translation": "增大 α 会延迟导通。",
  "live": "When the firing angle increases",
  "live_translation": "当触发角增大时",
  "prediction": "the average voltage may decrease.",
  "prediction_translation": "平均电压可能降低。"
}
```

## 开发与测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

目录：`presense/state.py` 状态与上下文；`pipeline.py` 有界异步调度；`predictor.py` 语义预测；
`runtime.py` 底座适配；`broadcast.py` WebSocket；`demo.py` 固定演示；`run_presense.py` 桌面入口。

## GitHub 项目

代码仓库：[NewGuys33/Presense](https://github.com/NewGuys33/Presense)。
本仓库保存 PreSense V0 增量源码与启动说明，底座由 bootstrap.py 下载固定提交。
忽略规则排除本地配置、下载的上游源码、模型、虚拟环境和日志。
