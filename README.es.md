# Heartbeat Monitor: Agente de Monitorización de Alto Rendimiento

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-blue.svg" alt="Python 3.14">
  <img src="https://img.shields.io/badge/FastAPI-0.109-009688.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/AlpineJS-3.x-8bc34a.svg" alt="AlpineJS">
  <img src="https://img.shields.io/badge/Docker-passing-brightgreen.svg" alt="Docker Build Status">
</p>

Un agente de monitorización ligero, modular y concurrente diseñado específicamente para entornos Dockerizados. Este sistema no solo verifica la disponibilidad, sino que optimiza la latencia de red y gestiona el estado de los servicios con una arquitectura resiliente.

Desarrollado en **Python 3.14 (Alpine)**, enfocado en la eficiencia de recursos y la precisión de métricas.

## 📊 Dashboard de Analítica

El sistema incluye un panel de control moderno para visualizar la salud de tu infraestructura.

* **Frontend:** Construido con **AlpineJS** y **ECharts**. Ligero, sin build-step complejo, con actualizaciones en tiempo real ("Live Mode") y visualización de **Jitter**.
* **Backend:** API RESTful de alto rendimiento con **FastAPI**. Implementa **Resolución Dinámica** (`TARGET_DATA_POINTS = 30`) para garantizar gráficos fluidos sin importar el rango de tiempo consultado (desde 5 minutos hasta 30 días).

## 🏗️ Arquitectura del Sistema

El sistema utiliza un patrón de **Productor-Consumidor desacoplado** a través de la base de datos compartida.

```ascii
+----------------------+           +------------------------+
|   HEARTBEAT AGENT    |  (Write)  |     SQLITE (WAL)       |
| (Python / Productor) |---------->| (Persistencia Híbrida) |
+----------------------+           +------------------------+
          ^                                    ^
          | (10s Loop)                         |
          |                                    | (Read-Only :ro)
+---------+------------+           +-----------+------------+
| Servicios / Docker   |           |   DASHBOARD BACKEND    |
| (Target a Monitorear)|           | (FastAPI / Consumidor) |
+----------------------+           +-----------+------------+
                                               ^
                                               | (JSON / REST)
                                               v
                                   +------------------------+
                                   |   DASHBOARD FRONTEND   |
                                   |   (AlpineJS / ECharts) |
                                   +------------------------+
```

1. **Agente (Escritura):** Tiene acceso exclusivo de escritura a la DB. Usa modo WAL para no bloquear lecturas.
2. **Dashboard (Lectura):** Monta el volumen de datos como `read-only` (`:ro`). Si el agente cae, el dashboard sigue mostrando datos históricos.
3. **Frontend:** Consume la API del backend mediante *polling* inteligente (cada 2s en modo Live).

## 🚀 Características Técnicas Destacadas

Más que un simple script de "ping", este proyecto implementa patrones de ingeniería para resolver problemas comunes en monitorización distribuida:

* **⚡ Arquitectura Concurrente:** Implementación de `ThreadPoolExecutor` para paralelizar operaciones de I/O (solicitudes HTTP, consultas a sockets Docker), desacoplando la recolección de métricas del bloqueo de red y garantizando ciclos de ejecución precisos.
* **🧠 Red Inteligente (Smart Networking):**
  * **DNS Override & Host Injection:** Mecanismo capaz de interceptar tráfico hacia servicios internos, resolviendo directamente a IPs locales e inyectando cabeceras `Host`. Esto elimina la latencia de resolución DNS externa y el overhead de SSL en redes internas (reducción de ~50ms a ~2ms).
  * **IPv4 Enforcement:** Adaptadores HTTP personalizados a nivel de transporte para mitigar los retrasos de resolución IPv6 comunes en contenedores Alpine Linux.
* **🐳 Protocolo Docker Nativo:** Soporte para el esquema `docker:<container_name>`, permitiendo verificaciones de salud directas contra el socket Unix de Docker (`/var/run/docker.sock`) para servicios que no exponen puertos HTTP.
* **🛡️ Resiliencia de Datos:** Uso de SQLite en modo **WAL (Write-Ahead Logging)** para permitir alta concurrencia en operaciones de lectura/escritura sin bloqueos de base de datos.
* **🔔 Gestión de Estado con "Debounce":** Sistema de alertas inteligente que filtra falsos positivos mediante umbrales de cambio de estado configurables y lógica de reintentos automática ante fallos del webhook.

## ⚙️ Flujo de Ejecución del Agente

El agente opera en un bucle principal, ejecutándose cada 10 segundos, coordinando la recolección, procesamiento y notificación.

```ascii
[ INICIO ]
    |
    v
[ 1. Cargar Configuración (.env) ]
    |
    v
[ 2. Init Base de Datos (SQLite WAL) ]
    |
    +---> [ BUCLE PRINCIPAL (Cada 10s) ] <--------------------------+
            |                                                       |
            |-- (A) Métricas Sistema (CPU/RAM) [Síncrono]           |
            |                                                       |
            |-- (B) Health Checks [ThreadPoolExecutor / Paralelo]   |
            |       |--> HTTP/HTTPS (Smart Request)                 |
            |       |--> Docker Socket                              |
            |       +--> Ping Internet                              |
            |                                                       |
            v                                                       |
    [ 3. Procesar Estado (Debounce Logic) ]                         |
            |                                                       |
            +--- ¿Cambio de Estado? ---> [ Enviar Alerta (N8N) ]    |
            |                                                       |
            +--- ¿Internet OK? --------> [ Enviar Heartbeat (CF) ]  |
            |                                                       |
            v                                                       |
    [ 4. Persistencia (Guardar Métricas en DB) ] -------------------+
```

### Flujo de Ejecución Detallado (Ciclo de 10s)

1. **Inicialización:** Carga de configuración y establecimiento de conexiones persistentes (Keep-Alive).
2. **Métricas de Sistema (Síncrono):** Lectura instantánea de CPU/RAM/Disco (`psutil`).
3. **Health Checks (Paralelo)::** Se lanzan hilos concurrentes para verificar todos los servicios configurados y la conectividad a Internet.
4. **Procesamiento de Estado:** Se evalúan los cambios (Healthy <-> Unhealthy) contra los umbrales definidos.
5. **Notificación/Heartbeat:** Si hay cambios críticos o corresponde un latido, se envían payloads JSON optimizados a los endpoints externos.
6. **Persistencia:** Se realiza un commit atómico de todas las métricas del ciclo en la base de datos local.

## 📂 Estructura del Código (Monorepo)

El proyecto ha evolucionado hacia una arquitectura de **Monorepo** para gestionar tanto el agente principal como las herramientas de visualización y desarrollo:

```text
/
├── apps/
│   ├── heartbeat/     # Agente de Monitorización (Python Service)
│   │   ├── main.py        # Orquestador principal.
│   │   ├── config.py      # Gestión de configuración.
│   │   ├── monitors.py    # Lógica de health checks y métricas.
│   │   ├── alerts.py      # Gestión de estado y notificaciones.
│   │   ├── network.py     # Capa de red (Smart Request, IPv4).
│   │   └── database.py    # Persistencia SQLite.
│   ├── dashboard/     # Panel de Visualización (Nuevo)
│   │   ├── backend/       # API FastAPI para analítica.
│   │   └── frontend/      # UI Reactiva (AlpineJS + ECharts).
│   └── mocks/         # Mock Server para desarrollo local
│       ├── server.py      # Servidor Python de pruebas.
│       └── templates/     # UI del Mock Controller.
├── data/              # Volúmenes persistentes (DBs, logs)
│   ├── metrics.db     # Base de datos Producción.
│   ├── metrics_dev.db # Base de datos Desarrollo.
│   └── ...
├── docker-compose.prod.yml  # Stack Producción (Agente + Dashboard).
├── docker-compose.dev.yml   # Stack Desarrollo (Agente + Dashboard + Mock).
├── .env.prod.example        # Plantilla env Producción.
├── .env.dev.example         # Plantilla env Desarrollo.
└── ...
```

### Descripción de Módulos (Heartbeat Agent)

* **`main.py`**: Contiene el bucle principal de ejecución de la aplicación. Coordina la inicialización, la recolección de datos, el procesamiento de estado y la persistencia de métricas.
* **`config.py`**: Centraliza la lectura de variables de entorno, la definición de constantes globales y el parseo de la configuración de servicios a monitorizar.
* **`monitors.py`**: Agrupa las funciones responsables de obtener datos del sistema (CPU, RAM, Disco) y realizar los health checks HTTP/HTTPS y Docker.
* **`alerts.py`**: Implementa la lógica de gestión de estado transitorio y estable, así como el mecanismo de envío de alertas a través de webhooks N8N y la comunicación de latidos al worker de Cloudflare.
* **`network.py`**: Provee la capa de abstracción para red, incluyendo optimización de sesiones y la lógica `smart_request` para DNS Override.
* **`database.py`**: Encapsula todas las operaciones relacionadas con la base de datos SQLite y el guardado de métricas recolectadas en cada ciclo.

## Monitorización de Servicios

La funcionalidad principal del agente es monitorizar el estado de múltiples servicios web, reportarlo al worker y generar alertas si su estado cambia de forma persistente.

### Configuración Dinámica

Los servicios a monitorear se configuran dinámicamente mediante variables de entorno:

1. **`SERVICE_NAMES`**: Lista separada por comas de los nombres de los servicios (ej: `SERVICE_NAMES=nextjs,strapi,umami`).
2. **`SERVICE_URL_{nombre}`**: La URL a chequear para cada nombre definido (ej: `SERVICE_URL_nextjs=https://www.ejemplo.com`).

Un servicio se considera `"healthy"` si responde con un código `2xx` o `3xx`. De lo contrario, se marca como `"unhealthy"`.

### Configuración Avanzada de Servicios

El monitor soporta características avanzadas para cubrir casos de uso complejos, como servicios internos o endpoints protegidos.

#### 1. Monitoreo Directo de Contenedores (`docker:`)

Para servicios de infraestructura (como Nginx, túneles, bases de datos) que no exponen un puerto HTTP accesible fácilmente, puedes usar el protocolo `docker:`. Esto verifica directamente si el contenedor está en estado `running`.

* **Sintaxis:** `SERVICE_URL_<nombre>="docker:<nombre_del_contenedor>"`
* **Ejemplo:**

    ```bash
    SERVICE_URL_nginx="docker:mi-contenedor-nginx"
    ```

* **Nota:** Requiere que el agente tenga acceso al socket de Docker (`/var/run/docker.sock`).

#### 2. Headers HTTP Personalizados

Algunos endpoints de salud requieren autenticación o headers específicos para responder correctamente. Puedes definirlos usando variables de entorno con el prefijo `SERVICE_HEADERS_`.

* **Sintaxis:** `SERVICE_HEADERS_<nombre>="Header1:Valor1,Header2:Valor2"`
* **Ejemplo:**

    ```bash
    # Verifica un endpoint que requiere un token o flag especial
    SERVICE_URL_api="https://mi-api.com/health"
    SERVICE_HEADERS_api="x-health-check:true,Authorization:Bearer mi-token"
    ```

### Optimización de Latencia (DNS Override)

Para entornos donde los servicios residen en la misma red local o servidor (ej: contenedores Docker detrás de un Nginx en el host), el agente permite configurar una IP de anulación de DNS (`INTERNAL_DNS_OVERRIDE_IP`) para reducir drásticamente la latencia.

* **Funcionamiento:** Si se define esta variable, el agente interceptará las peticiones a los servicios monitorizados, resolverá el dominio directamente a la IP especificada, forzará el uso de HTTP (evitando el handshake SSL innecesario en la red interna) e inyectará el encabezado `Host` correcto.
* **Beneficio:** Reduce la latencia de ~50ms a ~1-3ms al saltarse la resolución DNS externa y el enrutamiento público.
* **Configuración:** Ver variable `INTERNAL_DNS_OVERRIDE_IP` en `.env`.

### Payload de Estado de Salud

En cada ciclo, el agente construye un payload JSON que resume el estado de salud de los servicios y lo envía al `HEARTBEAT_URL`.

* **Estructura del Payload:**

    ```json
    {
      "services": {
        "nextjs": { "status": "healthy" },
        "strapi": { "status": "unhealthy" },
        "umami": { "status": "healthy" }
      }
    }
    ```

## Gestión de Estado y Alertas

Para evitar falsas alarmas por fallos transitorios y gestionar las notificaciones de forma centralizada, el agente implementa una **arquitectura de estado unificada**.

Toda la lógica de estado se gestiona a través de una única función genérica, `check_state_change`, y se almacena en un diccionario global en memoria, `global_states`. Este enfoque permite monitorear cualquier item (el worker principal o servicios individuales) usando las mismas reglas, evitando la duplicación de código.

### Lógica de Notificación

El sistema envía alertas al `N8N_WEBHOOK_URL` bajo las siguientes condiciones, incluyendo ahora mecanismos de robustez y detalle:

1. **Robustez y Reintentos:**
    * Si el envío de la alerta falla (por ejemplo, timeout del webhook), el sistema reintenta automáticamente hasta **3 veces** antes de desistir, asegurando que las alertas críticas lleguen a su destino.

2. **Alertas Enriquecidas:**
    * **Servicio Caído:** Incluye la razón específica del fallo (ej: `HTTP 500`, `Timeout`, `Container Exited`) para facilitar el diagnóstico inmediato.
    * **Servicio Recuperado:** Muestra la latencia actual del servicio tras la recuperación.
    * **Timestamp:** Todas las alertas incluyen la fecha y hora exacta del evento (zona horaria configurada) para una auditoría precisa.

3. **Condiciones de Disparo:**
    * **Caída de Servicio:** Tras `STATUS_CHANGE_THRESHOLD` fallos consecutivos.
    * **Recuperación de Servicio:** Inmediata al primer éxito.
    * **Estado del Worker:** Monitorización de cambios de estado del propio worker de Cloudflare con alertas contextuales.

Este mecanismo asegura que solo se notifiquen los cambios de estado confirmados, aplicando una lógica consistente a todos los elementos monitoreados.

## 💾 Persistencia de Datos (Esquema Relacional)

El sistema utiliza **SQLite** en modo **WAL (Write-Ahead Logging)** para permitir escrituras de alta concurrencia desde el agente y lecturas simultáneas desde el dashboard sin bloqueos. El esquema ha sido normalizado para soportar consultas analíticas eficientes.

### Tabla 1: `monitoring_cycles` (Hechos Globales)

Almacena una fila por cada ciclo de ejecución (10s).

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | `TEXT (PK)` | UUID único del ciclo. |
| `timestamp_lima`| `TEXT` | Marca de tiempo ISO8601 (Indexado). |
| `cpu_percent` | `REAL` | Uso de CPU global. |
| `ram_percent` | `REAL` | Uso de RAM global. |
| `disk_percent`| `REAL` | Uso de disco raíz. |
| `uptime_seconds`| `REAL` | Uptime del sistema host. |
| `container_count`| `INTEGER`| Total de contenedores Docker corriendo. |
| `internet_status` | `BOOLEAN`| `1` (Online) / `0` (Offline). |
| `ping_ms` | `REAL` | Latencia a Internet (ICMP/HTTP Ping). |
| `worker_status` | `INTEGER` | Código de estado HTTP retornado por la API del Cloudflare Worker. Refleja el resultado del procesamiento del latido. <br> - `200`: **Éxito**. Latido recibido, procesado y el estado del host/servicios fue actualizado. Puede indicar un estado "recorded" (sin cambios) o "recovered" (recuperación). <br> - `220`: **Advertencia (Ciego)**. Latido recibido y timestamp actualizado, pero la API no pudo leer el estado *anterior* de su base de datos. No se pudo determinar si hubo una recuperación. <br> - `221`: **Advertencia (Fallo en Actualización de Recuperación)**. Se detectó una recuperación, pero la API falló al actualizar su propio estado o al enviar la notificación. <br> - `500`: **Error Crítico del Worker**. La API falló en un paso esencial (ej. escribir el timestamp inicial) y el latido fue abortado. <br> - `NULL`: **Error del Agente Local**. El script de monitorización no pudo contactar la API del worker (ej. timeout, error de red, DNS). |
| `cycle_duration_ms` | `INTEGER` | Tiempo total de ejecución del ciclo. |

### Tabla 2: `service_checks` (Detalle por Servicio)

Almacena el estado individual de cada servicio monitoreado en un ciclo. Relación 1:N con `monitoring_cycles`.

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | `INTEGER (PK)` | Auto-incremental. |
| `cycle_id` | `TEXT (FK)` | Referencia a `monitoring_cycles.id`. |
| `service_name` | `TEXT` | Nombre del servicio (Indexado). |
| `service_url` | `TEXT` | Endpoint verificado. |
| `status` | `TEXT` | `'healthy'` o `'unhealthy'`. |
| `latency_ms` | `REAL` | Tiempo de respuesta del servicio. |
| `status_code` | `INTEGER` | Código HTTP de respuesta (ej. 200, 500). |
| `error_message` | `TEXT` | Detalle del error (Timeout, Connection Refused). |

## 🔌 API del Dashboard (Backend)

El backend del dashboard expone una API REST optimizada para consumo de métricas históricas y en tiempo real.

### `GET /api/live`

Retorna el estado actual del sistema y las series de tiempo históricas.

* **Parámetros:**
  * `range` (Query, opcional): Ventana de tiempo. Opciones: `live` (5m), `1h`, `12h`, `24h`, `7d`, `30d`. Default: `1h`.

* **Optimización (Resolución Dinámica):**
  El backend aplica automáticamente un algoritmo de *downsampling* basado en la constante `TARGET_DATA_POINTS = 30`.
  * Si pides `24h`, la API agrupará los datos en buckets de ~48 minutos.
  * Si pides `live` (5m), los buckets serán de 10 segundos (raw data).
  * **Beneficio:** El frontend siempre recibe ~30 puntos, manteniendo la renderización rápida y ligera.

* **Métricas Incluidas:**
  * **Jitter:** Calculado como `MAX(latency) - MIN(latency)` por bucket.
  * **Uptime %:** Calculado sobre el total de ciclos en el rango.
  * **Distribución de Errores:** Conteo agrupado por códigos de estado.

## ⚙️ Configuración y Variables de Entorno

El comportamiento del sistema se controla centralizadamente a través de variables de entorno (archivos `.env`).

### Credenciales y Endpoints

| Variable | Requerida | Descripción | Ejemplo |
| :--- | :---: | :--- | :--- |
| `SECRET_KEY` | **Sí** | Clave compartida para autenticar con el Worker de Cloudflare. | `sk_12345abcdef` |
| `HEARTBEAT_URL` | **Sí** | URL del endpoint del Cloudflare Worker para recibir latidos. | `https://worker.dev/api/heartbeat` |
| `N8N_WEBHOOK_URL` | No | URL del webhook para alertas externas. | `https://n8n.mi-server.com/...` |
| `SQLITE_DB_PATH` | No | Ruta interna para el archivo de base de datos. | `data/metrics.db` |

### Monitorización de Servicios

| Variable | Descripción | Ejemplo |
| :--- | :--- | :--- |
| `SERVICE_NAMES` | Lista separada por comas de identificadores de servicios. | `api,webapp,db_primary` |
| `SERVICE_URL_{NAME}` | URL de destino para el health check. Soporta `http(s)://` y `docker:`. | `docker:postgres-container` |
| `SERVICE_HEADERS_{NAME}`| Headers HTTP opcionales (Auth, User-Agent, etc.). | `Authorization:Bearer xyz` |

### Red Avanzada

| Variable | Descripción | Ejemplo |
| :--- | :--- | :--- |
| `INTERNAL_DNS_OVERRIDE_IP` | IP para forzar resolución DNS local. Útil para saltar NAT/Loopback. | `172.17.0.1` (Gateway Docker) |

### Configuración Operacional (Avanzado)

| Variable | Descripción | Defecto |
| :--- | :--- | :--- |
| `LOOP_INTERVAL_SECONDS` | Intervalo del bucle principal del agente (en segundos). | `10` |
| `STATUS_CHANGE_THRESHOLD` | Umbral de confirmación para cambios de estado (Debounce). | `4` |
| `SERVICE_TIMEOUT_SECONDS` | Tiempo de espera máximo para cada health check. | `2` |
| `TARGET_DATA_POINTS` | Densidad de puntos en las gráficas del dashboard (Bucketing). | `30` |
| `TZ` | Zona horaria del sistema (ej. `America/Lima`). | `UTC` |

## 🛠️ Configuración y Despliegue

### Entorno de Producción

1. **Clonar el repositorio:**

    ```bash
    git clone https://github.com/iamseb4s/heartbeat-monitor.git
    cd heartbeat-monitor
    ```

2. **Configurar Variables:**
    * Copia `.env.prod.example` a `.env.prod`.
    * Rellena `SECRET_KEY`, `HEARTBEAT_URL`, `N8N_WEBHOOK_URL`, `SERVICE_NAMES` y las `SERVICE_URL_*` correspondientes.
3. **Ejecutar:**

    ```bash
    docker compose -f docker-compose.prod.yml up -d --build
    ```

4. **Acceso:**
    * **Dashboard:** `http://localhost:8100` (o la IP/dominio configurado).
    * **Logs del Agente:** `docker logs -f heartbeat-agent-prod`

### Entorno de Desarrollo (Local + Mock)

Para desarrollar sin afectar la base de datos de producción ni saturar el Worker real, utiliza el entorno aislado que incluye un **Mock Server**:

1. **Configurar Variables:** Copia `.env.dev.example` a `.env.dev`.
2. **Ejecutar:** `docker compose -f docker-compose.dev.yml up --build`
3. **Herramientas Disponibles:**
    * **Dashboard:** **<http://localhost:8098>** - Visualización de métricas en tiempo real.
    * **Mock Controller:** **<http://localhost:8099>** - Simular caídas, ver logs y forzar respuestas.

## 🧪 Pruebas (Testing)

El proyecto incluye una suite completa de pruebas unitarias y de integración para garantizar la fiabilidad de la lógica de alertas, red y monitoreo.

* **Ejecución Manual:** Ejecuta los tests dentro del contenedor de desarrollo:

  ```bash
  docker exec heartbeat-agent-dev pytest
  ```

* **Automatización (Git Hook):** Para ejecutar tests automáticamente antes de cada merge, activa el hook incluido:

  ```bash
  git config core.hooksPath .githooks
  ```
