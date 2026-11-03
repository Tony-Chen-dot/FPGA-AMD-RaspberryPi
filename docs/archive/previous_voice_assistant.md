> 历史资料：保留当时的记录，目录和控制方式可能已过时。当前操作请以根目录 README.md 和 docs/project_structure.md 为准。

# Voice Dashboard Assistant

这里已经替换成桌面 `voice_chain_debug` 中跑通的连续待机语音链路，并补上了 DeepSeek 联网数据库增强问答。

当前主流程是：

1. 监听唤醒词
2. 录音并转写问题
3. 从转写结果里提取关键词
4. 读取 `dashboard.sqlite3` 全部检测记录和缺陷明细
5. 把数据库全量数据、语音转写和对话上下文一起交给统一 AI 服务
6. 输出中文答案并用 TTS 播报

当数据库内容超过单次模型上下文限制时，系统会按表和记录分片，先逐片分析，再汇总回答。这样每次对话仍会把所有检测记录送入模型，而不是只取最近几条。

## 目录说明

- `app/main.py`：连续待机主入口
- `app/wake_word.py`：唤醒词监听
- `app/stt_module.py`：录音转写
- `app/db_context.py`：数据库全量导出和上下文构建
- `app/llm_module.py`：DeepSeek 联网调用
- `app/prompt.py`：铝片智能分拣系统背景提示词
- `app/conversation_store.py`：SQLite 对话历史
- `app/assistant_service.py`：网页和语音共用的对话服务
- `app/tts_module.py`：本地播报
- `app/status.py`：终端实时状态输出
- `scripts/start_voice_assistant.sh`：统一启动脚本

## 默认参数

- 唤醒词：`小助手`
- 录音设备：`plughw:3,0`
- 播放设备：`plughw:CARD=vc4hdmi1,DEV=0`
- 联网模型：`deepseek-v4-flash`
- 数据库：`~/Database/vision-dashboard/dashboard.sqlite3`
- Vosk 模型：`~/models/vosk-model-small-cn-0.22`
- TTS 优先级：`piper -> edge-tts -> espeak-ng`

## 可视化 AI 助手

启动 `vision-dashboard` 后，打开页面顶部的“AI 分拣助手”视图即可使用网页对话。左侧是持久化的历史会话，中间是当前对话，右侧会为每个用户问题生成快速定位点。勾选“回答后播报”时，回答会在树莓派的本地播放设备上通过现有 TTS 链路播报。

网页 API 与连续待机语音助手使用同一套提示词、数据库上下文构建器和 DeepSeek 调用逻辑。AI 背景固定为铝片智能分拣系统，并优先直接回答用户当前问题：问候和身份问题简短回答，明确数据查询只返回相关事实，只有分析、诊断或优化请求才展开全库分析并给出不超过三条与证据对应的工艺建议。

页面最右侧提供 `当前良率 / 缺陷排行 / 近期异常 / 问题排查 / 工艺优化 / 识别可靠性` 六个快捷问题。点击后只填入当前输入框并聚焦，允许先调整问题再发送。

提示词中的生产背景采用真实的工业铝板带与圆形铝片生产路线：熔炼合金化 -> 精炼除气过滤 -> 半连续铸锭与热轧或连续铸轧 -> 多道次冷轧 -> 退火 -> 脱脂清洗与矫直 -> 分切或圆片冲裁 -> 去毛刺、堆叠和输送 -> 视觉检测与分拣。缺陷和工序之间只建立待验证的排查关系，不能替代现场工艺参数和批次追溯数据。

新增配置：

```bash
export DEEPSEEK_DB_CHUNK_CHARS="160000"
export DEEPSEEK_CHUNK_MAX_TOKENS="900"
```

## 推荐启动方式

整套工程默认通过 `config/site_config.sh` 中的 `VOICE_WAKE_ENABLED=0` 关闭 Vosk 持续唤醒，以节省树莓派 CPU；需要启用时改为 `1` 后重新启动。

如果你是在整套 `raspberry` 工程里使用，优先执行顶层：

```bash
cd ~/raspberry
./scripts/start/system.sh
```

如果你只想单独启动语音助手：

```bash
cd ~/raspberry
./scripts/start/voice.sh
```

## 实时输出

启动后终端日志里会持续打印：

- 当前实时状态
- 唤醒识别内容
- 问题转写
- 关键词
- 命中的缺陷标签
- AI 回答

## 常用环境变量

```bash
export VOICE_WAKE_ENABLED="1"
export VOICE_WAKE_WORD="小助手"
export VOICE_RECORD_DEVICE="plughw:3,0"
export VOICE_SAMPLE_RATE="16000"
export VOICE_VOSK_MODEL_PATH="$HOME/models/vosk-model-small-cn-0.22"
export VOICE_PLAYBACK_DEVICE="plughw:CARD=vc4hdmi1,DEV=0"
export VOICE_QUESTION_SECONDS="5"
export DASHBOARD_DB_PATH="$HOME/Database/vision-dashboard/dashboard.sqlite3"
export DASHBOARD_URL="http://172.20.10.12:8000"
export LLM_PROVIDER="deepseek"
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_API_KEY="你的 deepseek key"
export DEEPSEEK_MODEL="deepseek-v4-flash"
export TTS_PROVIDER="piper"
export PIPER_DATA_DIR="$HOME/piper_voices"
```
