const API_URL = "/api/live"; 

// Extended color palette for dynamic service charts
const CHART_COLORS = [
  "#22c55e", "#3b82f6", "#f59e0b", "#ec4899", "#8b5cf6", 
  "#06b6d4", "#f97316", "#10b981", "#ef4444", "#a855f7", 
  "#eab308", "#6366f1"
];

// Semantic colors for service states
const STATUS_COLORS = {
  "healthy": "#22c55e", // Green
  "down": "#ef4444",    // Red
  "error": "#f97316",   // Orange
  "timeout": "#eab308", // Yellow
  "unknown": "#6b7280"  // Gray/Purple
};

document.addEventListener("alpine:init", () => {
  Alpine.data("dashboardApp", () => {
    // Stores ECharts instances (non-reactive for performance)
    const chartInstances = {
      host: {},
      general: {},
      services: {},
      servicesPie: {},
    };

    return {
      activeTab: "general",
      timeRange: "live",
      timeOptions: ['live', '1h', '3h', '6h', '12h', '24h', '7d', '30d'],
      metrics: MOCK_METRICS, // Initial placeholder
      scrolled: false,
      
      // Generic card configuration for Agent and Network
      globalCards: [
        {
          id: 'agent',
          title: 'Agent Health',
          pieId: 'statusPieChart',
          pieLabel: 'Status Dist.',
          chartId: 'cycleChart',
          chartLabel: 'Cycle Duration (ms)',
          statsTitle: 'Cycle Stats'
        },
        {
          id: 'network',
          title: 'Network Connectivity',
          pieId: 'internetPieChart',
          pieLabel: 'Internet Uptime',
          chartId: 'pingChart',
          chartLabel: 'Google Ping (ms)',
          statsTitle: 'Ping Stats'
        }
      ],
      
      mockState: {
        initialized: false,
        times: [],
        cpu: [], ram: [], disk: [],
        cycle: [], ping: [],
        services: {}
      },

      init() {
        this.$nextTick(() => {
          this.initHostCharts();
          this.initGeneralCharts();
          this.syncServiceCharts();
        });

        window.addEventListener("resize", () => this.resizeAll());
        
        // Show floating toast on scroll
        window.addEventListener("scroll", () => {
            this.scrolled = window.scrollY > 150;
        });

        // Trigger resize on tab switch to fix ECharts rendering
        this.$watch("activeTab", () => {
          this.$nextTick(() => this.resizeAll());
          setTimeout(() => this.resizeAll(), 50);
        });

        this.$watch("timeRange", () => {
          this.fetchMetrics();
        });

        // Start polling
        this.fetchMetrics();
        setInterval(() => this.fetchMetrics(), 10000);
      },

      // --- Helpers ---

      escapeHtml(unsafe) {
        if (!unsafe) return "";
        return unsafe
          .replace(/&/g, "&amp;")
          .replace(/</g, "&lt;")
          .replace(/>/g, "&gt;")
          .replace(/"/g, "&quot;")
          .replace(/'/g, "&#039;");
      },

      formatTime(isoString) {
        if (!isoString) return "--:--";
        const date = new Date(isoString);
        return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      },

      getCardData(id) {
        if (id === 'agent') {
          const status = this.metrics.monitor.worker_status;
          return {
            stats: this.metrics.monitor.stats,
            badgeLabel: 'WORKER: ' + status,
            isHealthy: status === 200
          };
        } else if (id === 'network') {
          const status = this.metrics.network.internet_status;
          return {
            stats: this.metrics.network.stats,
            badgeLabel: status ? 'NET: ONLINE' : 'NET: OFFLINE',
            isHealthy: status
          };
        }
        return { stats: {}, badgeLabel: '??', isHealthy: false };
      },
      
      // Helper to determine status badge color in services table
      getStatusBadgeColor(status) {
        if (status === 'healthy') return 'bg-green-500/20 text-green-400 border-green-500/30';
        if (status === 'down') return 'bg-red-500/20 text-red-400 border-red-500/30';
        if (status === 'error') return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
        if (status === 'timeout') return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
        return 'bg-gray-500/20 text-gray-400 border-gray-500/30'; // unknown
      },

      // --- Chart Management ---

      resizeAll() {
        const all = [
          ...Object.values(chartInstances.host),
          ...Object.values(chartInstances.general),
          ...Object.values(chartInstances.services),
          ...Object.values(chartInstances.servicesPie),
        ];
        all.forEach((c) => {
          if (c && typeof c.resize === "function" && !c.isDisposed()) {
            c.resize();
          }
        });
      },

      initHostCharts() {
        chartInstances.host.cpu = this.initLine("cpuChart", "#6d28d9", "CPU %");
        chartInstances.host.ram = this.initLine("ramChart", "#3b82f6", "RAM %");
        chartInstances.host.disk = this.initLine("diskChart", "#f59e0b", "Disk %");
      },

      initGeneralCharts() {
        chartInstances.general.cycle = this.initLine("cycleChart", "#22c55e", "Duration (ms)");
        chartInstances.general.ping = this.initLine("pingChart", "#ec4899", "Ping (ms)");
        this.initServicesOverviewChart();
        this.initStatusPieChart();
        this.initInternetPieChart();
      },

      syncServiceCharts() {
        this.metrics.services.forEach((svc, index) => {
          if (!chartInstances.services[svc.name]) {
            const color = CHART_COLORS[index % CHART_COLORS.length];
            chartInstances.services[svc.name] = this.initLine(
              `chart-service-${svc.name}`,
              color,
              "Latency (ms)"
            );
          }
          if (!chartInstances.servicesPie[svc.name]) {
            chartInstances.servicesPie[svc.name] = this.initServicePie(
              `pie-service-${svc.name}`,
              svc.status === "healthy" ? 99 : 0
            );
          }
        });
      },

      // --- ECharts Builders ---

      getCommonOptions() {
        return {
          backgroundColor: "transparent",
          animation: true,
          animationDuration: 500,
          tooltip: {
            trigger: "axis",
            backgroundColor: "#1a1a1c",
            borderColor: "#27272a",
            textStyle: { color: "#fafafa" },
            confine: false,
            appendToBody: true,
            extraCssText: 'z-index: 9999 !important;',
            axisPointer: { type: "line", lineStyle: { color: "#a1a1aa", type: "dashed" }, animation: false },
          },
          grid: { left: "2%", right: "2%", bottom: "5%", top: "5%", containLabel: true },
          xAxis: {
            type: "category",
            boundaryGap: false,
            axisLine: { lineStyle: { color: "#27272a" } },
            axisLabel: { color: "#a1a1aa", fontSize: 10 },
          },
          yAxis: {
            type: "value",
            splitLine: { show: true, lineStyle: { color: "#27272a" } },
            axisLabel: { color: "#a1a1aa", fontSize: 10 },
          },
        };
      },

      initLine(domId, color, name) {
        const dom = document.getElementById(domId);
        if (!dom) return null;
        let chart = echarts.getInstanceByDom(dom);
        if (chart) chart.dispose();
        chart = echarts.init(dom);
        
        const base = this.getCommonOptions();
        chart.setOption({
          ...base,
          series: [{
            name: name,
            type: "line",
            smooth: true,
            showSymbol: false,
            lineStyle: { color: color, width: 2 },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: color },
                { offset: 1, color: "transparent" },
              ]),
            },
            data: [] 
          }],
        });
        return chart;
      },

      initServicesOverviewChart() {
        const dom = document.getElementById("servicesChart");
        if (!dom) return;
        let chart = echarts.getInstanceByDom(dom);
        if (chart) chart.dispose();
        chart = echarts.init(dom);
        chartInstances.general.services = chart;
        
        const base = this.getCommonOptions();
        chart.setOption({
          ...base,
          grid: { ...base.grid, top: "45px" },
          legend: { textStyle: { color: "#a1a1aa" }, top: 0 },
          xAxis: { ...base.xAxis, data: [] },
          series: [],
        });
      },

      initGenericPie(domId, title, subtext, colorPalette) {
        const dom = document.getElementById(domId);
        if (!dom) return null;
        let chart = echarts.getInstanceByDom(dom);
        if (chart) chart.dispose();
        chart = echarts.init(dom);

        chart.setOption({
          backgroundColor: "transparent",
          tooltip: { 
            trigger: "item", 
            backgroundColor: "#1a1a1c", 
            borderColor: "#27272a", 
            textStyle: { color: "#fafafa" },
            formatter: (params) => {
              const safeName = this.escapeHtml(params.name);
              return `${params.marker} <span style="font-weight:bold">${safeName}</span>: ${params.value} (${params.percent}%)`;
            },
            confine: false,
            appendToBody: true,
            extraCssText: 'z-index: 9999 !important;'
          },
          title: { 
            text: title, 
            subtext: subtext, 
            left: "center", 
            top: "center", 
            textStyle: { color: "#fafafa", fontSize: 16, fontWeight: "bold" }, 
            subtextStyle: { color: "#a1a1aa", fontSize: 10 } 
          },
          series: [{
            type: "pie",
            radius: ["60%", "85%"],
            avoidLabelOverlap: false,
            itemStyle: { borderRadius: 4, borderColor: "#1a1a1c", borderWidth: 2 },
            label: { show: false },
            data: [],
            color: colorPalette
          }]
        });
        return chart;
      },

      initStatusPieChart() {
        chartInstances.general.pie = this.initGenericPie(
            "statusPieChart", "0%", "Success", ["#22c55e", "#f59e0b", "#ef4444"]
        );
      },

      initInternetPieChart() {
        chartInstances.general.internetPie = this.initGenericPie(
            "internetPieChart", "--%", "Net Uptime", ["#22c55e", "#ef4444"]
        );
      },

      initServicePie(domId, healthPercent) {
        return this.initGenericPie(
            domId, "--%", "Uptime", ["#22c55e", "#ef4444"]
        );
      },

      // --- Core Data Logic ---
      
      currentRequestController: null, // Store the active controller

      async fetchMetrics() {
        // Cancel previous request if it exists
        if (this.currentRequestController) {
          this.currentRequestController.abort();
        }
        
        // Create new controller for this request
        this.currentRequestController = new AbortController();
        const signal = this.currentRequestController.signal;

        try {
          const response = await fetch(`${API_URL}?range=${this.timeRange}`, { signal });
          if (!response.ok) throw new Error("Backend response error: " + response.status);
          const data = await response.json();
          this.updateDashboard(data);
        } catch (e) { 
          if (e.name === 'AbortError') {
             // Request cancelled intentionally, do nothing
             console.log("Previous fetch cancelled");
          } else {
             console.error("API Error - Failed to fetch metrics:", e); 
          }
        } finally {
           // Cleanup if this request finished naturally
           if (this.currentRequestController && this.currentRequestController.signal === signal) {
              this.currentRequestController = null;
           }
        }
      },

      updateDashboard(data) {
        this.metrics = data; 

        // 1. Host Charts
        const times = data.history.times;
        this.updateChart(chartInstances.host.cpu, times, data.history.system.cpu);
        this.updateChart(chartInstances.host.ram, times, data.history.system.ram);
        this.updateChart(chartInstances.host.disk, times, data.history.system.disk);

        // 2. General Charts
        this.updateChart(chartInstances.general.cycle, times, data.history.cycle_duration);
        this.updateChart(chartInstances.general.ping, times, data.history.ping);

        // 3. Status Pie (Worker Availability)
        if (chartInstances.general.pie && !chartInstances.general.pie.isDisposed()) {
          const rangeKey = this.timeRange; 
          const successPct = data.monitor.uptime[rangeKey] || 0;
          
          // Apply custom coloring logic: Green for 200, Palette for others
          const coloredData = data.monitor.distribution.map((item, index) => {
            let color;
            if (item.name === "200") {
                color = "#22c55e"; 
            } else {
                color = CHART_COLORS[(index + 1) % CHART_COLORS.length];
            }
            return {
                value: item.value,
                name: item.name,
                itemStyle: { color: color }
            };
          });

          chartInstances.general.pie.setOption({
             title: { text: successPct + "%" },
             series: [{ data: coloredData }]
          });
        }

        // 4. Internet Pie (Network Availability)
        if (chartInstances.general.internetPie && !chartInstances.general.internetPie.isDisposed()) {
            const upPct = data.network.uptime; 
            
            let pieData = [];
            if (data.network.uptime_counts) {
                pieData = [
                    { value: data.network.uptime_counts.success, name: "Online", itemStyle: { color: "#22c55e" } },
                    { value: data.network.uptime_counts.failure, name: "Offline", itemStyle: { color: "#ef4444" } }
                ];
            } else {
                pieData = [{ value: 1, name: "No Data", itemStyle: { color: "#555" } }];
            }

            chartInstances.general.internetPie.setOption({
                title: { text: upPct + "%" },
                series: [{ data: pieData }]
            });
        }

        // 5. Services Overview
        this.updateServicesOverview(times, data);

        // 6. Individual Services (Dynamic Sync)
        this.syncServiceCharts(); 
        data.services.forEach(svc => {
            const seriesData = data.history.services[svc.name];
            // Line chart
            this.updateChart(chartInstances.services[svc.name], times, seriesData);
            
            // Pie chart
            const pie = chartInstances.servicesPie[svc.name];
            if (pie && !pie.isDisposed()) {
                const healthPct = svc.stats.uptime; 
                let pieData = [];
                if (svc.stats.distribution) {
                    // Map distribution to semantic colors
                    pieData = Object.entries(svc.stats.distribution).map(([status, count]) => ({
                        value: count,
                        name: status.toUpperCase(),
                        itemStyle: { color: STATUS_COLORS[status] || STATUS_COLORS.unknown }
                    }));
                } else {
                    // Fallback
                    pieData = [
                        { value: svc.stats.success, name: "Healthy", itemStyle: { color: STATUS_COLORS.healthy } },
                        { value: svc.stats.failure, name: "Unhealthy", itemStyle: { color: STATUS_COLORS.down } }
                    ];
                }

                pie.setOption({
                    title: { text: healthPct + "%" },
                    series: [{ data: pieData }]
                });
            }
        });
      },

      updateChart(chart, times, data) {
        if (chart && !chart.isDisposed()) {
          chart.setOption({
            xAxis: { data: times },
            series: [{ data: data }]
          });
        }
      },

      updateServicesOverview(times, data) {
        const chart = chartInstances.general.services;
        if (chart && !chart.isDisposed()) {
          const series = data.services.map((svc, i) => ({
            name: svc.name,
            type: "line",
            smooth: true,
            showSymbol: false,
            lineStyle: { width: 2 },
            itemStyle: { color: CHART_COLORS[i % CHART_COLORS.length] },
            data: data.history.services[svc.name]
          }));
          
          chart.setOption({
             legend: { data: data.services.map(s => s.name) },
             xAxis: { data: times },
             series: series
          });
        }
      }
    };
  });
});