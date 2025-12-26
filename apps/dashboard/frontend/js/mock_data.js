const MOCK_METRICS = {
    last_updated: new Date().toISOString(),
    system: {
        cpu: 15.4,
        ram: 42.1,
        disk: 60.5,
        containers: 5,
        uptime: "14d 2h 15m"
    },
    network: {
        internet_status: true,
        ping_ms: 14,
        stats: {
            avg: 14,
            max: 25,
            min: 10,
            p95: 18
        }
    },
    monitor: {
        worker_status: 200,
        cycle_duration: 350,
        stats: {
            avg: 340,
            max: 520,
            min: 310,
            p95: 480
        },
        uptime: {
            "24h": 99.98,
            "7d": 99.95,
            "30d": 99.90
        },
        distribution: [
            { value: 85, name: '200' },
            { value: 10, name: '220' },
            { value: 5, name: '500' }
        ]
    },
    services: [
        { 
            name: "nextjs", 
            service_type: "http", 
            status: "healthy", 
            status_code: 200, 
            latency: 45,
            stats: { max: 55, avg: 45, min: 35, p95: 50 } 
        },
        { 
            name: "strapi", 
            service_type: "http", 
            status: "healthy", 
            status_code: 200, 
            latency: 120,
            stats: { max: 140, avg: 120, min: 100, p95: 130 }
        },
        { 
            name: "umami", 
            service_type: "http", 
            status: "healthy", 
            status_code: 200, 
            latency: 30,
            stats: { max: 40, avg: 30, min: 20, p95: 35 }
        },
        { 
            name: "nginx", 
            service_type: "docker", 
            status: "healthy", 
            status_code: null, 
            latency: 10,
            stats: { max: 15, avg: 10, min: 5, p95: 12 }
        },
        { 
            name: "database", 
            service_type: "docker", 
            status: "unhealthy", 
            status_code: null, 
            latency: 0,
            stats: { max: 0, avg: 0, min: 0, p95: 0 }
        }
    ],
    history: {
        times: Array.from({length: 30}, (_, i) => `10:${i < 10 ? '0'+i : i}`),
        system: {
            cpu: Array.from({length: 30}, () => Math.floor(Math.random() * 20 + 10)),
            ram: Array.from({length: 30}, () => Math.floor(Math.random() * 5 + 40)),
            disk: Array.from({length: 30}, () => 60)
        },
        cycle_duration: Array.from({length: 30}, () => Math.floor(Math.random() * 200 + 300)),
        ping: Array.from({length: 30}, () => Math.floor(Math.random() * 15 + 10)),
        services: {
            "nextjs": Array.from({length: 30}, () => Math.floor(Math.random() * 20 + 40)),
            "strapi": Array.from({length: 30}, () => Math.floor(Math.random() * 30 + 100)),
            "umami": Array.from({length: 30}, () => Math.floor(Math.random() * 10 + 20)),
            "nginx": Array.from({length: 30}, () => Math.floor(Math.random() * 5 + 8)),
            "database": Array.from({length: 30}, () => 0)
        }
    }
};