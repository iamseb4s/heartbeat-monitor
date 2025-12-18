const API_URL = ""; // TODO: Set your Backend URL here (e.g., "http://localhost:8000/api/metrics")
const GRAPH_POINTS = 30;

const CHART_COLORS = [
  "#22c55e", "#3b82f6", "#f59e0b", "#ec4899", "#8b5cf6", 
  "#06b6d4", "#f97316", "#10b981", "#ef4444", "#a855f7", 
  "#eab308", "#6366f1"
];

document.addEventListener("alpine:init", () => {
  Alpine.data("dashboardApp", () => {
    // Non-reactive chart instances
    const chartInstances = {
      host: {},
      general: {},
      services: {},
      servicesPie: {},
    };

    return {
      activeTab: "general",
      timeRange: "1h",
      metrics: MOCK_METRICS,
      scrolled: false, // Track scroll position for Toast
      
      // Configuration for Generic Cards
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
        
        // Scroll Listener for Floating Toast
        window.addEventListener("scroll", () => {
            this.scrolled = window.scrollY > 150;
        });

        this.$watch("activeTab", () => {
          this.$nextTick(() => this.resizeAll());
          setTimeout(() => this.resizeAll(), 50);
        });

        this.$watch("timeRange", () => {
          this.mockState.initialized = false;
          this.fetchMetrics();
        });

        setInterval(() => this.fetchMetrics(), 2000);
      },

      // --- HELPERS ---

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

      // --- CHART MANAGEMENT ---

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

      // Dynamic Service Chart Sync
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

      // --- ECHARTS BUILDERS ---

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
            confine: true,
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
            data: [] // Init empty
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

      initStatusPieChart() {
        const dom = document.getElementById("statusPieChart");
        if (!dom) return;
        let chart = echarts.getInstanceByDom(dom);
        if (chart) chart.dispose();
        chart = echarts.init(dom);
        chartInstances.general.pie = chart;

        chart.setOption({
          backgroundColor: "transparent",
          tooltip: { trigger: "item", backgroundColor: "#1a1a1c", borderColor: "#27272a", textStyle: { color: "#fafafa" } },
          title: { text: "0%", subtext: "Success", left: "center", top: "center", textStyle: { color: "#fafafa", fontSize: 18 }, subtextStyle: { color: "#a1a1aa", fontSize: 9 } },
          series: [{
            type: "pie",
            radius: ["60%", "85%"],
            avoidLabelOverlap: false,
            itemStyle: { borderRadius: 4, borderColor: "#1a1a1c", borderWidth: 2 },
            label: { show: false },
            data: [],
            color: ["#22c55e", "#f59e0b", "#ef4444"],
          }],
        });
      },

      initInternetPieChart() {
        const dom = document.getElementById("internetPieChart");
        if (!dom) return;
        let chart = echarts.getInstanceByDom(dom);
        if (chart) chart.dispose();
        chart = echarts.init(dom);
        chartInstances.general.internetPie = chart;
        
        // Initial setup only
        chart.setOption({
          backgroundColor: "transparent",
          tooltip: { trigger: "item", backgroundColor: "#1a1a1c", borderColor: "#27272a", textStyle: { color: "#fafafa" }, formatter: "{b}: {c}%" },
          title: { text: "--%", subtext: "Net Uptime", left: "center", top: "center", textStyle: { color: "#fafafa", fontSize: 16, fontWeight: "bold" }, subtextStyle: { color: "#a1a1aa", fontSize: 10 } },
          series: [{
            name: "Internet Status",
            type: "pie",
            radius: ["65%", "90%"],
            avoidLabelOverlap: false,
            itemStyle: { borderRadius: 2, borderColor: "#1a1a1c", borderWidth: 1 },
            label: { show: false },
            data: []
          }]
        });
      },

      initServicePie(domId, healthPercent) {
        const dom = document.getElementById(domId);
        if (!dom) return null;
        let chart = echarts.getInstanceByDom(dom);
        if (chart) chart.dispose();
        chart = echarts.init(dom);
        
        // Initial setup only
        chart.setOption({
          backgroundColor: "transparent",
          tooltip: { trigger: "item", backgroundColor: "#1a1a1c", borderColor: "#27272a", textStyle: { color: "#fafafa" }, formatter: "{b}: {c}%" },
          title: { text: "--%", subtext: "Uptime", left: "center", top: "center", textStyle: { color: "#fafafa", fontSize: 16, fontWeight: "bold" }, subtextStyle: { color: "#a1a1aa", fontSize: 10 } },
          series: [{
            type: "pie",
            radius: ["65%", "90%"],
            avoidLabelOverlap: false,
            itemStyle: { borderRadius: 2, borderColor: "#1a1a1c", borderWidth: 1 },
            label: { show: false },
            data: []
          }]
        });
        return chart;
      },

      // --- DATA FETCHING & UPDATE ---

      async fetchMetrics() {
        // -----------------------------------------------------------------
        // TODO: INTEGRATION POINT (Uncomment for production)
        // try {
        //   const response = await fetch(`${API_URL}?range=${this.timeRange}`);
        //   const data = await response.json();
        //   this.updateDashboard(data);
        // } catch (e) { console.error("API Error", e); }
        // -----------------------------------------------------------------

        // --- MOCK DATA GENERATION ---
        const now = new Date();
        const rnd = (min, max) => Math.floor(Math.random() * (max - min + 1)) + min;
        const rndFloat = (min, max) => (Math.random() * (max - min) + min).toFixed(1);

        // Helper to calculate stats from an array
        const calculateStats = (arr) => {
            const sorted = [...arr].sort((a, b) => a - b);
            return {
                max: sorted[sorted.length - 1],
                min: sorted[0],
                avg: (arr.reduce((a, b) => a + parseFloat(b), 0) / arr.length).toFixed(0),
                p95: sorted[Math.floor(sorted.length * 0.95)]
            };
        };

        // Initialize persistent mock history if missing
        if (!this.mockState.initialized) {
            this.mockState.times = Array.from({ length: GRAPH_POINTS }, (_, i) => {
                const d = new Date(now - (GRAPH_POINTS - i) * 10000);
                return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
            });
            this.mockState.cpu = Array.from({ length: GRAPH_POINTS }, () => rndFloat(10, 30));
            this.mockState.ram = Array.from({ length: GRAPH_POINTS }, () => rndFloat(40, 50));
            this.mockState.disk = Array(GRAPH_POINTS).fill(60);
            this.mockState.cycle = Array.from({ length: GRAPH_POINTS }, () => rnd(200, 350));
            this.mockState.ping = Array.from({ length: GRAPH_POINTS }, () => rnd(10, 30));
            
            this.metrics.services.forEach(s => {
                this.mockState.services[s.name] = Array.from({ length: GRAPH_POINTS }, () => rnd(20, 100));
            });
            this.mockState.initialized = true;
        }

        // Advance Time
        const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        this.mockState.times.push(timeStr);
        this.mockState.times.shift();

        // Advance Metrics
        const pushMetric = (arr, min, max, isFloat = false) => {
            const last = parseFloat(arr[arr.length - 1]);
            let next = last + (Math.random() * (max - min) * 0.2 - (max - min) * 0.1); 
            if (next < min) next = min;
            if (next > max) next = max;
            arr.push(isFloat ? next.toFixed(1) : Math.floor(next));
            arr.shift();
        };

        pushMetric(this.mockState.cpu, 10, 40, true);
        pushMetric(this.mockState.ram, 40, 60, true);
        
        pushMetric(this.mockState.cycle, 200, 400);
        pushMetric(this.mockState.ping, 10, 50);

        Object.keys(this.mockState.services).forEach(key => {
            pushMetric(this.mockState.services[key], 20, 150);
        });

        // Construct Response Object (Full Backend Snapshot)
        const mockData = {
          last_updated: now.toISOString(),
          system: {
              cpu: this.mockState.cpu[GRAPH_POINTS - 1],
              ram: this.mockState.ram[GRAPH_POINTS - 1],
              disk: 60,
              containers: 5,
              uptime: "14d"
          },
          monitor: {
              worker_status: 200,
              uptime: { "24h": rndFloat(99.0, 99.9) },
              distribution: [{ value: rnd(85, 95), name: '200' }, { value: rnd(5, 15), name: '500' }],
              stats: calculateStats(this.mockState.cycle) // Calculated from real history
          },
          network: {
              internet_status: Math.random() > 0.05,
              stats: calculateStats(this.mockState.ping) // Calculated from real history
          },
          services: this.metrics.services.map(s => ({
              ...s,
              status: Math.random() > 0.05 ? "healthy" : "unhealthy",
              latency: this.mockState.services[s.name][GRAPH_POINTS - 1],
              stats: calculateStats(this.mockState.services[s.name]) // Calculated from real history
          })),
          history: {
            times: [...this.mockState.times],
            system: { 
                cpu: [...this.mockState.cpu], 
                ram: [...this.mockState.ram], 
                disk: [...this.mockState.disk] 
            },
            cycle_duration: [...this.mockState.cycle],
            ping: [...this.mockState.ping],
            services: { ...this.mockState.services }
          }
        };

        this.updateDashboard(mockData);
      },

      // --- CORE UPDATE LOGIC ---

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

        // 3. Status Pie
        if (chartInstances.general.pie && !chartInstances.general.pie.isDisposed()) {
          const successVal = data.monitor.distribution.find(d => d.name === '200')?.value || 0;
          chartInstances.general.pie.setOption({
             title: { text: successVal + "%" },
             series: [{ data: data.monitor.distribution }]
          });
        }

        // 4. Internet Pie
        if (chartInstances.general.internetPie && !chartInstances.general.internetPie.isDisposed()) {
            const up = data.monitor.uptime["24h"] || 0;
            const down = (100 - up).toFixed(1);
            chartInstances.general.internetPie.setOption({
                title: { text: up + "%" },
                series: [{ 
                    data: [
                        { value: up, name: "Online", itemStyle: { color: "#22c55e" } },
                        { value: down, name: "Offline", itemStyle: { color: "#ef4444" } }
                    ]
                }]
            });
        }

        // 5. Services Overview
        this.updateServicesOverview(times, data);

        // 6. Individual Services (Dynamic Sync)
        this.syncServiceCharts(); 
        data.services.forEach(svc => {
            const seriesData = data.history.services[svc.name];
            // Line
            this.updateChart(chartInstances.services[svc.name], times, seriesData);
            
            // Pie
            const pie = chartInstances.servicesPie[svc.name];
            if (pie && !pie.isDisposed()) {
                const health = svc.status === 'healthy' ? 99 : 0; 
                pie.setOption({
                    title: { text: health + "%" },
                    series: [{ 
                        data: [
                            { value: health, name: "Healthy", itemStyle: { color: "#22c55e" } },
                            { value: 100 - health, name: "Unhealthy", itemStyle: { color: "#ef4444" } }
                        ]
                    }]
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