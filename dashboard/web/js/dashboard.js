window.addEventListener("DOMContentLoaded", () => {
  const { createApp, markRaw, nextTick } = Vue;
  const { createPinia, defineStore } = Pinia;
  const requestedView = new URLSearchParams(window.location.search).get("view");
  const initialView = ["main", "history", "assistant"].includes(requestedView) ? requestedView : "main";
  const ASSISTANT_QUICK_PROMPTS = [
    {
      category: "数据概况",
      label: "当前良率",
      prompt: "当前数据库中的良率是多少？请给出 OK 数、总检测数、计算公式和实际数据时间范围。",
    },
    {
      category: "缺陷统计",
      label: "缺陷排行",
      prompt: "当前数据库中哪一种缺陷最多？请给出各缺陷数量、占缺陷明细的比例，并说明统计口径。",
    },
    {
      category: "趋势诊断",
      label: "近期异常",
      prompt: "请分析最近一段有效数据中的缺陷变化和异常集中时段，并明确说明使用的数据时间范围。",
    },
    {
      category: "现场处置",
      label: "问题排查",
      prompt: "请结合当前数据库分析最需要优先排查的问题，并按数据证据、可能工序、现场检查方法给出不超过三项排查建议。",
    },
    {
      category: "生产工艺",
      label: "工艺优化",
      prompt: "请结合当前缺陷分布，分析熔铸、轧制、退火清洗、矫直分切、冲裁和输送环节中最值得核查的工艺点，并给出验证方法。",
    },
    {
      category: "模型质量",
      label: "识别可靠性",
      prompt: "请分析各缺陷类型的置信度分布和低置信度记录，判断哪些类别需要优先复核模型或图像采集条件。",
    },
  ];

  const useDashboardStore = defineStore("dashboard", {
    state: () => ({
      activeView: initialView,
      selectedLineId: null,
      activeLineId: null,
      productionLines: [],
      snapshot: {
        device: {},
        summary: { total_count: 0, good_count: 0, bad_count: 0, yield_rate: 0, avg_inference_ms: 0 },
        latest_result: null,
        recent_results: [],
        history: { records: [], defect_distribution: [], trend: [] },
        connection_plan: {},
        uptime_seconds: 0,
      },
      socket: null,
      socketConnected: false,
      socketPingHandle: null,
      socketReconnectTimer: null,
      manualSocketClose: false,
      mjpegConnected: false,
      mjpegStreamUrl: "/api/stream.mjpg",
      mjpegReconnectTimer: null,
      reconnectBusy: false,
      connectionNotice: "视频由 MJPEG 传输，标记框与统计数据由 WebSocket 推送。",
      tickHandle: null,
      lastAnimationKey: "",
      snapshotReceivedAtMs: Date.now(),
    }),
    getters: {
      device: (state) => state.snapshot.device || {},
      summary: (state) => state.snapshot.summary || {},
      latestResult: (state) => state.snapshot.latest_result || null,
      recentResults: (state) => state.snapshot.recent_results || [],
      defectSummary: (state) => state.snapshot.defect_summary || [],
      history: (state) => state.snapshot.history || { records: [], defect_distribution: [], trend: [] },
      connectionPlan: (state) => state.snapshot.connection_plan || {},
      uptimeSeconds: (state) => state.snapshot.uptime_seconds || 0,
      supportedDefects: (state) => state.snapshot.supported_defects || [],
    },
    actions: {
      apiUrl(path) {
        const url = new URL(path, window.location.origin);
        url.searchParams.set("line_id", this.selectedLineId || this.activeLineId || 1);
        return `${url.pathname}${url.search}`;
      },
      async loadInitial() {
        const infoResponse = await fetch("/api/lines");
        if (!infoResponse.ok) throw new Error("读取产线配置失败");
        const info = await infoResponse.json();
        this.activeLineId = info.active_line_id;
        this.productionLines = info.lines;
        const requested = Number(new URLSearchParams(window.location.search).get("line_id"));
        this.selectedLineId = info.lines.some((line) => line.id === requested) ? requested : info.active_line_id;
        const response = await fetch(this.apiUrl("/api/state"));
        if (!response.ok) throw new Error("读取产线数据失败");
        this.applySnapshot(await response.json());
      },
      applySnapshot(snapshot) {
        this.snapshot = snapshot;
        this.snapshotReceivedAtMs = Date.now();
        this.mjpegConnected = Boolean(snapshot?.device?.online && snapshot?.device?.stream_state === "live");
        if (snapshot?.recent_results?.length) {
          this.lastAnimationKey = "";
        }
      },
      applyTrend(trend) {
        this.snapshot = {
          ...this.snapshot,
          history: {
            ...(this.snapshot.history || {}),
            trend: Array.isArray(trend) ? trend : [],
          },
        };
      },
      mergeLiveState(liveState) {
        const nextDevice = {
          ...(this.snapshot.device || {}),
          ...(liveState?.device || {}),
        };
        this.snapshot = {
          ...this.snapshot,
          device: nextDevice,
          generated_at: liveState?.generated_at || this.snapshot.generated_at,
          uptime_seconds:
            Number.isFinite(liveState?.uptime_seconds) ? liveState.uptime_seconds : this.snapshot.uptime_seconds,
        };
        this.snapshotReceivedAtMs = Date.now();
        this.mjpegConnected = Boolean(nextDevice.online && nextDevice.stream_state === "live");
      },
      mergeResultUpdate(update) {
        this.snapshot = {
          ...this.snapshot,
          ...update,
          device: {
            ...(this.snapshot.device || {}),
            ...(update?.device || {}),
          },
        };
        this.snapshotReceivedAtMs = Date.now();
        this.mjpegConnected = Boolean(
          this.snapshot?.device?.online && this.snapshot?.device?.stream_state === "live"
        );
      },
      stopSocketPing() {
        if (this.socketPingHandle) {
          window.clearInterval(this.socketPingHandle);
          this.socketPingHandle = null;
        }
      },
      connectSocket() {
        if (this.socketReconnectTimer) {
          window.clearTimeout(this.socketReconnectTimer);
          this.socketReconnectTimer = null;
        }
        if (this.socket) {
          this.manualSocketClose = true;
          this.socket.close();
          this.stopSocketPing();
        }
        const protocol = window.location.protocol === "https:" ? "wss" : "ws";
        const url = `${protocol}://${window.location.host}${this.apiUrl("/ws/dashboard")}`;
        const socket = new WebSocket(url);
        socket.onopen = () => {
          this.manualSocketClose = false;
          this.socketConnected = true;
          this.connectionNotice = "WebSocket 数据通道已连接。";
          this.stopSocketPing();
          this.socketPingHandle = window.setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
              socket.send("ping");
            }
          }, 5000);
        };
        socket.onclose = () => {
          this.socketConnected = false;
          this.stopSocketPing();
          if (!this.manualSocketClose) {
            this.connectionNotice = "WebSocket 已断开，正在自动重连。";
            this.socketReconnectTimer = window.setTimeout(() => this.connectSocket(), 2000);
          }
        };
        socket.onerror = () => {
          this.socketConnected = false;
          this.connectionNotice = "WebSocket 建连失败。";
        };
        socket.onmessage = (event) => {
          const message = JSON.parse(event.data);
          if (message.payload?.line_id && message.payload.line_id !== this.selectedLineId) return;
          if (message.type === "snapshot") {
            this.applySnapshot(message.payload);
          }
          if (message.type === "live_state") {
            this.mergeLiveState(message.payload);
          }
          if (message.type === "result_update") {
            this.mergeResultUpdate(message.payload);
          }
          if (message.type === "pong") {
            this.socketConnected = true;
          }
        };
        this.socket = socket;
      },
      connectMjpeg() {
        if (this.selectedLineId !== this.activeLineId) {
          this.mjpegConnected = false;
          this.mjpegStreamUrl = "";
          return;
        }
        if (this.mjpegReconnectTimer) {
          window.clearTimeout(this.mjpegReconnectTimer);
          this.mjpegReconnectTimer = null;
        }
        this.mjpegConnected = false;
        this.mjpegStreamUrl = this.apiUrl(`/api/stream.mjpg?v=${Date.now()}`);
        this.connectionNotice = "正在连接 MJPEG 视频流。";
      },
      markMjpegConnected() {
        this.mjpegConnected = this.selectedLineId === this.activeLineId;
        this.connectionNotice = "MJPEG 视频通道已连接。";
      },
      markMjpegError() {
        this.mjpegConnected = false;
        this.connectionNotice = "MJPEG 视频通道断开，正在重建。";
        if (!this.mjpegReconnectTimer) {
          this.mjpegReconnectTimer = window.setTimeout(() => this.connectMjpeg(), 1600);
        }
      },
      reconnectAll() {
        this.reconnectBusy = true;
        this.connectionNotice = "正在重建 WebSocket 与 MJPEG 实时链路。";
        this.connectSocket();
        this.connectMjpeg();
        window.setTimeout(() => {
          this.reconnectBusy = false;
        }, 900);
      },
      startTicking() {
        if (this.tickHandle) {
          window.clearInterval(this.tickHandle);
        }
        this.tickHandle = window.setInterval(() => {
          this.snapshot = { ...this.snapshot, uptime_seconds: (this.snapshot.uptime_seconds || 0) + 1 };
        }, 1000);
      },
    },
  });

  createApp({
    setup() {
      const store = useDashboardStore();
      return { store };
    },
    data() {
      return {
        miniChart: null,
        trendChart: null,
        yieldChart: null,
        overlayNow: Date.now(),
        overlayTimer: null,
        assistantStatus: { database: {}, pipeline: [] },
        assistantConversations: [],
        assistantConversationId: null,
        assistantMessages: [],
        assistantInput: "",
        assistantLoading: false,
        assistantLoaded: false,
        assistantError: "",
        assistantSpeak: false,
        assistantListening: false,
        assistantRecognition: null,
        assistantQuickPrompts: ASSISTANT_QUICK_PROMPTS,
        trendLoaded: false,
        trendLoading: false,
        trendLoadError: "",
      };
    },
    computed: {
      selectedLineId() { return this.store.selectedLineId; },
      activeLineId() { return this.store.activeLineId; },
      productionLines() { return this.store.productionLines; },
      cameraAssigned() { return this.selectedLineId === this.activeLineId; },
      activeView: {
        get() {
          return this.store.activeView;
        },
        set(value) {
          this.store.activeView = value;
          if (value === "assistant") {
            this.loadAssistant();
          } else {
            this.$nextTick(async () => {
              await nextTick();
              this.renderCharts();
              this.handleResize();
            });
          }
        },
      },
      device() {
        return this.store.device;
      },
      summary() {
        return this.store.summary;
      },
      latestResult() {
        return this.store.latestResult;
      },
      recentResults() {
        return this.store.recentResults;
      },
      defectSummary() {
        return this.store.defectSummary;
      },
      history() {
        return this.store.history;
      },
      connectionPlan() {
        return this.store.connectionPlan;
      },
      uptimeSeconds() {
        return this.store.uptimeSeconds;
      },
      supportedDefects() {
        return this.store.supportedDefects.filter((label) => label !== "划痕");
      },
      socketConnected() {
        return this.store.socketConnected;
      },
      mjpegConnected() {
        return this.store.mjpegConnected;
      },
      mjpegStreamUrl() {
        return this.store.mjpegStreamUrl;
      },
      reconnectBusy() {
        return this.store.reconnectBusy;
      },
      trendButtonLabel() {
        if (this.trendLoading) return "正在读取...";
        return this.trendLoaded ? "刷新趋势" : "显示趋势";
      },
      activeAssistantConversation() {
        return this.assistantConversations.find((item) => item.id === this.assistantConversationId) || null;
      },
      assistantDatabaseStatus() {
        return this.assistantStatus.database || {};
      },
      assistantOutline() {
        let index = 0;
        return this.assistantMessages
          .filter((message) => message.role === "user")
          .map((message) => {
            index += 1;
            const content = (message.content || "").replace(/\s+/g, " ").trim();
            return {
              id: message.id,
              index: String(index).padStart(2, "0"),
              content: content.length > 54 ? `${content.slice(0, 54)}...` : content,
            };
          });
      },
      overlayKey() {
        return [
          Number(this.device?.circle_count || 0),
          this.device?.trigger_overlay?.image_data || "",
          this.device?.trigger_overlay?.expires_at_ms || "",
          this.device?.trigger_overlay?.sent_until_ms || "",
          this.latestResult?.frame_id || "",
        ].join("|");
      },
      triggerOverlayVisible() {
        const overlay = this.device?.trigger_overlay;
        return Boolean(overlay?.image_data && Number(overlay.expires_at_ms || 0) > this.estimatedServerNowMs);
      },
      sentStatusVisible() {
        const overlay = this.device?.trigger_overlay;
        return Boolean(Number(overlay?.sent_until_ms || 0) > this.estimatedServerNowMs);
      },
      estimatedServerNowMs() {
        const generatedAtMs = Date.parse(this.store.snapshot?.generated_at || "");
        if (!Number.isFinite(generatedAtMs)) return this.overlayNow;
        const elapsedSinceMessage = Math.max(0, this.overlayNow - this.store.snapshotReceivedAtMs);
        return generatedAtMs + elapsedSinceMessage;
      },
      chartRenderKey() {
        const records = this.history?.records || [];
        const trend = this.history?.trend || [];
        const defects = this.defectSummary?.length ? this.defectSummary : (this.history?.defect_distribution || []);
        const firstRecord = records[0] || {};
        const lastTrend = trend[trend.length - 1] || {};
        return [
          records.length,
          firstRecord.id || firstRecord.frame_id || "",
          this.trendLoaded ? "loaded" : "pending",
          trend.length,
          lastTrend.bucket || "",
          lastTrend.total_count || 0,
          defects.map((item) => `${item.name}:${item.value}`).join(","),
        ].join("|");
      },
    },
    watch: {
      overlayKey() {
        this.$nextTick(() => {
          this.drawOverlay();
        });
      },
      chartRenderKey() {
        this.$nextTick(() => this.renderCharts());
      },
    },
    async mounted() {
      await this.store.loadInitial();
      this.store.connectSocket();
      this.store.startTicking();
      this.store.connectMjpeg();
      if (this.activeView === "assistant") {
        this.loadAssistant();
      }
      await nextTick();
      this.renderCharts();
      this.drawOverlay();
      this.overlayTimer = window.setInterval(() => {
        this.overlayNow = Date.now();
      }, 80);
      window.addEventListener("resize", this.handleResize);
    },
    beforeUnmount() {
      window.removeEventListener("resize", this.handleResize);
      if (this.overlayTimer) {
        window.clearInterval(this.overlayTimer);
      }
      if (this.assistantRecognition) {
        this.assistantRecognition.stop();
      }
    },
    methods: {
      switchProductionLine(number) {
        if (number === this.selectedLineId || this.assistantLoading) return;
        const url = new URL(window.location.href);
        url.searchParams.set("line_id", number);
        url.searchParams.set("view", this.activeView);
        // Navigate with an explicit line identity; old fetches/streams cannot update the new view.
        window.location.assign(url.href);
      },
      reconnectAll() {
        this.store.reconnectAll();
      },
      async loadTrend() {
        if (this.trendLoading) return;
        this.trendLoading = true;
        this.trendLoadError = "";
        try {
          const payload = await this.requestJson("/api/history/trend");
          this.store.applyTrend(payload.trend);
          this.trendLoaded = true;
          await nextTick();
          this.renderCharts();
          this.handleResize();
        } catch (error) {
          this.trendLoadError = error.message || "趋势数据读取失败";
          console.warn("Trend refresh failed", error);
          await nextTick();
          this.renderCharts();
        } finally {
          this.trendLoading = false;
        }
      },
      async requestJson(url, options = {}) {
        const response = await fetch(this.store.apiUrl(url), options);
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
          throw new Error(payload.detail || `请求失败 (${response.status})`);
        }
        return payload;
      },
      escapeAssistantHtml(content) {
        return String(content ?? "").replace(/[&<>"']/g, (character) => ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#039;",
        })[character]);
      },
      renderAssistantMarkdown(content) {
        const source = String(content ?? "");
        const fallback = () => this.escapeAssistantHtml(source).replace(/\n/g, "<br>");
        if (!window.marked?.parse || !window.DOMPurify?.sanitize) {
          return fallback();
        }
        try {
          const rendered = window.marked.parse(source, { gfm: true, breaks: true });
          return window.DOMPurify.sanitize(rendered, {
            USE_PROFILES: { html: true },
            FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "option", "iframe", "object", "embed"],
            FORBID_ATTR: ["style", "srcset"],
          });
        } catch (error) {
          console.error("Markdown rendering failed", error);
          return fallback();
        }
      },
      async loadAssistant() {
        if (this.assistantLoaded) return;
        this.assistantLoaded = true;
        this.assistantError = "";
        try {
          const [statusPayload, conversationPayload] = await Promise.all([
            this.requestJson("/api/assistant/status"),
            this.requestJson("/api/assistant/conversations"),
          ]);
          this.assistantStatus = statusPayload;
          this.assistantConversations = conversationPayload.conversations || [];
          if (this.assistantConversations.length) {
            await this.selectAssistantConversation(this.assistantConversations[0].id);
          } else {
            await this.newAssistantConversation();
          }
        } catch (error) {
          this.assistantLoaded = false;
          this.assistantError = error.message || "AI 助手加载失败";
        }
      },
      async refreshAssistantConversations() {
        const payload = await this.requestJson("/api/assistant/conversations");
        this.assistantConversations = payload.conversations || [];
      },
      async newAssistantConversation() {
        this.assistantError = "";
        try {
          const payload = await this.requestJson("/api/assistant/conversations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: "新对话" }),
          });
          await this.refreshAssistantConversations();
          await this.selectAssistantConversation(payload.conversation.id);
        } catch (error) {
          this.assistantError = error.message || "新建对话失败";
        }
      },
      async selectAssistantConversation(conversationId) {
        if (!conversationId) return;
        this.assistantConversationId = conversationId;
        this.assistantError = "";
        try {
          const payload = await this.requestJson(`/api/assistant/conversations/${encodeURIComponent(conversationId)}`);
          this.assistantMessages = payload.conversation.messages || [];
          await this.$nextTick();
          this.scrollAssistantToBottom();
        } catch (error) {
          this.assistantError = error.message || "读取对话失败";
        }
      },
      async sendAssistantMessage() {
        const message = this.assistantInput.trim();
        if (!message || this.assistantLoading) return;
        if (!this.assistantConversationId) {
          await this.newAssistantConversation();
          if (!this.assistantConversationId) return;
        }
        this.assistantLoading = true;
        this.assistantError = "";
        this.assistantInput = "";
        const temporaryId = `pending-${Date.now()}`;
        this.assistantMessages.push({
          id: temporaryId,
          role: "user",
          content: message,
          created_at: new Date().toISOString(),
        });
        await this.$nextTick();
        this.scrollAssistantToBottom();
        try {
          const payload = await this.requestJson("/api/assistant/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              conversation_id: this.assistantConversationId,
              message,
              speak: this.assistantSpeak,
            }),
          });
          this.assistantConversationId = payload.conversation.id;
          this.assistantMessages = payload.conversation.messages || [];
          this.assistantStatus.database = payload.database_status || this.assistantStatus.database;
          await this.refreshAssistantConversations();
        } catch (error) {
          this.assistantMessages = this.assistantMessages.filter((item) => item.id !== temporaryId);
          this.assistantInput = message;
          this.assistantError = error.message || "模型调用失败";
        } finally {
          this.assistantLoading = false;
          await this.$nextTick();
          this.scrollAssistantToBottom();
        }
      },
      scrollAssistantToBottom() {
        const container = this.$refs.assistantMessagesEl;
        if (container) container.scrollTop = container.scrollHeight;
      },
      jumpToAssistantMessage(messageId) {
        const target = document.getElementById(`assistant-message-${messageId}`);
        if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
      },
      useAssistantQuickPrompt(prompt) {
        if (!prompt || this.assistantLoading) return;
        this.assistantInput = prompt;
        this.assistantError = "";
        this.$nextTick(() => {
          const input = this.$refs.assistantInputEl;
          if (!input) return;
          input.focus();
          input.setSelectionRange(input.value.length, input.value.length);
          input.scrollIntoView({ behavior: "smooth", block: "nearest" });
        });
      },
      toggleAssistantListening() {
        if (this.assistantListening && this.assistantRecognition) {
          this.assistantRecognition.stop();
          return;
        }
        const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!Recognition) {
          this.assistantError = "当前浏览器不支持语音输入；树莓派端唤醒词语音链路仍可独立使用。";
          return;
        }
        const recognition = new Recognition();
        recognition.lang = "zh-CN";
        recognition.interimResults = false;
        recognition.continuous = false;
        recognition.onstart = () => {
          this.assistantListening = true;
          this.assistantError = "";
        };
        recognition.onresult = (event) => {
          const transcript = event.results?.[0]?.[0]?.transcript || "";
          this.assistantInput = transcript.trim();
        };
        recognition.onerror = (event) => {
          this.assistantError = `语音输入失败: ${event.error || "unknown"}`;
        };
        recognition.onend = () => {
          this.assistantListening = false;
        };
        this.assistantRecognition = recognition;
        recognition.start();
      },
      handleMjpegLoad() {
        this.store.markMjpegConnected();
      },
      handleMjpegError() {
        this.store.markMjpegError();
      },
      cacheBust(url, key) {
        if (!url) return "";
        const imageUrl = new URL(url, window.location.origin);
        imageUrl.searchParams.set("v", key || Date.now());
        return imageUrl.href;
      },
      handleResize() {
        this.drawOverlay();
        if (this.miniChart) this.miniChart.resize();
        if (this.trendChart) this.trendChart.resize();
        if (this.yieldChart) this.yieldChart.resize();
      },
      formatTime(value) {
        if (!value) return "--";
        const date = new Date(value);
        return date.toLocaleString("zh-CN", { hour12: false });
      },
      formatTrendRange(item) {
        const startMs = Number(item?.bucket_start_epoch_ms);
        const endMs = Number(item?.bucket_end_epoch_ms);
        if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) {
          return item?.bucket || "--";
        }
        const options = {
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
          hour12: false,
        };
        const start = new Date(startMs).toLocaleString("zh-CN", options);
        const end = new Date(endMs).toLocaleString("zh-CN", options);
        return startMs === endMs ? start : `${start} - ${end}`;
      },
      formatAgo(value) {
        if (!value) return "尚未收到";
        const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
        if (seconds < 2) return "刚刚";
        if (seconds < 60) return `${seconds} 秒前`;
        if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟前`;
        return `${Math.floor(seconds / 3600)} 小时前`;
      },
      formatDuration(seconds) {
        const safe = Math.max(0, seconds || 0);
        const hours = Math.floor(safe / 3600);
        const mins = Math.floor((safe % 3600) / 60);
        const secs = safe % 60;
        return `${String(hours).padStart(2, "0")}:${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
      },
      drawOverlay() {
        const canvas = this.$refs.overlayEl;
        if (!canvas) return;
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        const stream = this.$refs.mjpegEl;
        if (!stream) return;
        const box = stream.getBoundingClientRect();
        if (!box.width || !box.height) return;
        canvas.width = box.width;
        canvas.height = box.height;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      },
      renderCharts() {
        const distribution = (this.defectSummary.length ? this.defectSummary : this.history.defect_distribution) || [];
        const trend = this.trendLoaded ? (this.history.trend || []) : [];
        if (this.$refs.miniChartEl) {
          this.miniChart = this.miniChart || markRaw(echarts.init(this.$refs.miniChartEl));
          const hasDistribution = distribution.length > 0;
          const totalDefectiveSheets = Number(this.summary.bad_count || 0);
          this.miniChart.setOption({
            backgroundColor: "transparent",
            tooltip: { trigger: "item" },
            title: hasDistribution
              ? {
                  text: String(totalDefectiveSheets),
                  subtext: "不良铝片数",
                  left: "center",
                  top: "39%",
                  textStyle: {
                    color: "#EDF9FF",
                    fontSize: 34,
                    fontWeight: 700,
                  },
                  subtextStyle: {
                    color: "#9FB8C8",
                    fontSize: 13,
                  },
                }
              : {
                  text: "暂无缺陷铝片数据",
                  left: "center",
                  top: "middle",
                  textStyle: {
                    color: "#9FB8C8",
                    fontSize: 18,
                    fontWeight: 500,
                  },
                },
            legend: {
              bottom: 0,
              left: "center",
              textStyle: { color: "#CFE4EF", fontSize: 13 },
              itemWidth: 12,
              itemHeight: 12,
            },
            series: [
              {
                type: "pie",
                radius: hasDistribution ? ["48%", "72%"] : ["0%", "0%"],
                center: ["50%", "42%"],
                avoidLabelOverlap: true,
                stillShowZeroSum: false,
                data: hasDistribution ? distribution : [],
                label: {
                  color: "#EDF9FF",
                  formatter: "{b}\n{c}",
                  fontSize: 13,
                },
                labelLine: {
                  lineStyle: { color: "rgba(207, 228, 239, 0.45)" },
                  length: 14,
                  length2: 10,
                },
                itemStyle: {
                  borderColor: "rgba(4, 17, 29, 0.92)",
                  borderWidth: 4,
                },
                emphasis: {
                  scale: true,
                  scaleSize: 8,
                },
                color: ["#3CF0FF", "#FF5B6E", "#FFD86B", "#6CFFB5", "#7DA8FF", "#FF9F6B"],
              },
            ],
          }, true);
          this.miniChart.resize();
        }
        if (this.$refs.trendChartEl) {
          this.trendChart = this.trendChart || markRaw(echarts.init(this.$refs.trendChartEl));
          const hasTrend = trend.length > 0;
          const trendSeries = hasTrend ? [
            {
              name: "不良数",
              type: "bar",
              yAxisIndex: 0,
              z: 1,
              barMaxWidth: 34,
              data: trend.map((item) => item.bad_count),
              itemStyle: { color: "#FF5B6E", borderRadius: [6, 6, 0, 0] },
            },
            {
              name: "总检测数",
              type: "line",
              yAxisIndex: 0,
              z: 3,
              smooth: true,
              showSymbol: true,
              symbol: "circle",
              symbolSize: 9,
              data: trend.map((item) => item.total_count),
              lineStyle: { color: "#3CF0FF", width: 3 },
              itemStyle: {
                color: "#3CF0FF",
                borderColor: "#04111D",
                borderWidth: 2,
              },
            },
          ] : [];
          this.trendChart.setOption({
            animation: false,
            backgroundColor: "transparent",
            tooltip: {
              trigger: "axis",
              formatter: (params) => {
                const entries = Array.isArray(params) ? params : [params];
                const dataIndex = Number(entries[0]?.dataIndex || 0);
                const lines = [this.formatTrendRange(trend[dataIndex])];
                entries.forEach((entry) => {
                  lines.push(`${entry.marker}${entry.seriesName}: ${entry.value}`);
                });
                return lines.join("<br/>");
              },
            },
            legend: {
              data: hasTrend ? ["总检测数", "不良数"] : [],
              textStyle: { color: "#9FB8C8" },
            },
            title: {
              show: !hasTrend,
              text: this.trendLoaded
                ? (this.trendLoadError || "暂无趋势数据")
                : "点击“显示趋势”加载数据",
              left: "center",
              top: "middle",
              textStyle: {
                color: "#9FB8C8",
                fontSize: 18,
                fontWeight: 500,
              },
            },
            grid: { left: 42, right: 20, top: 50, bottom: 52 },
            xAxis: {
              type: "category",
              data: trend.map((item) => item.bucket),
              axisLabel: {
                color: "#9FB8C8",
                interval: 0,
                rotate: trend.length > 1 ? 24 : 0,
                fontSize: 11,
              },
            },
            yAxis: {
              type: "value",
              min: 0,
              minInterval: 1,
              axisLabel: { color: "#9FB8C8" },
              splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } },
            },
            series: trendSeries,
          }, true);
        }
        if (this.$refs.yieldChartEl) {
          this.yieldChart = this.yieldChart || markRaw(echarts.init(this.$refs.yieldChartEl));
          this.yieldChart.setOption({
            backgroundColor: "transparent",
            tooltip: { trigger: "axis" },
            grid: { left: 42, right: 20, top: 30, bottom: 28 },
            xAxis: {
              type: "category",
              data: distribution.map((item) => item.name),
              axisLabel: { color: "#9FB8C8", interval: 0, rotate: 20 },
            },
            yAxis: {
              type: "value",
              axisLabel: { color: "#9FB8C8" },
              splitLine: { lineStyle: { color: "rgba(255,255,255,0.08)" } },
            },
            series: [
              {
                type: "bar",
                data: distribution.map((item) => item.value),
                itemStyle: {
                  color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: "#3CF0FF" },
                    { offset: 1, color: "#0D6A88" },
                  ]),
                  borderRadius: [10, 10, 0, 0],
                },
              },
            ],
          }, true);
        }
      },
    },
  })
    .use(createPinia())
    .mount("#app");
});
