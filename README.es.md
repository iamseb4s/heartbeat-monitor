# Heartbeat Monitor: Agente de Monitorización de Alto Rendimiento

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.14-blue.svg" alt="Python 3.14">
  <img src="https://img.shields.io/badge/Docker-passing-brightgreen.svg" alt="Docker Build Status">
</p>

Un agente de monitorización ligero, modular y concurrente diseñado específicamente para entornos Dockerizados. Este sistema no solo verifica la disponibilidad, sino que optimiza la latencia de red y gestiona el estado de los servicios con una arquitectura resiliente.

Desarrollado en **Python 3.14 (Alpine)**, enfocado en la eficiencia de recursos y la precisión de métricas.

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

## 📂 Estructura del Código

El proyecto ha sido refactorizado desde un script monolítico hacia una arquitectura modular basada en responsabilidades únicas (SRP):

```text
app/
├── main.py        # Orquestador principal de la aplicación.
├── config.py      # Gestión de la configuración y variables de entorno.
├── monitors.py    # Recopilación de métricas y chequeos de salud.
├── alerts.py      # Gestión del estado y envío de notificaciones.
├── network.py     # Infraestructura de red y configuración de requests.
└── database.py    # Funcionalidades de persistencia de datos SQLite.
```

### Descripción de Módulos

* **`main.py`**: Contiene el bucle principal de ejecución de la aplicación. Coordina la inicialización, la recolección de datos, el procesamiento de estado y la persistencia de métricas mediante la interacción con los demás módulos.
* **`config.py`**: Centraliza la lectura de variables de entorno, la definición de constantes globales y el parseo de la configuración de servicios a monitorizar.
* **`monitors.py`**: Agrupa las funciones responsables de obtener datos del sistema (CPU, RAM, Disco), contar contenedores Docker y realizar las comprobaciones de salud de los servicios HTTP/HTTPS y Docker.
* **`alerts.py`**: Implementa la lógica de gestión de estado transitorio y estable, así como el mecanismo de envío de alertas a través de webhooks N8N y la comunicación de latidos al worker de Cloudflare.
* **`network.py`**: Provee la capa de abstracción para las operaciones de red. Incluye la configuración de sesiones HTTP (forzando IPv4), y la función `smart_request` con su lógica de anulación de DNS interno.
* **`database.py`**: Encapsula todas las operaciones relacionadas con la base de datos SQLite, incluyendo su inicialización (creación de tablas) y el guardado de las métricas recolectadas en cada ciclo.

## Arquitectura y Flujo de Ejecución

El agente opera en un bucle principal que se ejecuta cada `LOOP_INTERVAL_SECONDS` (actualmente 10 segundos). La ejecución está alineada con el reloj del sistema para garantizar la consistencia de los intervalos (ej., se ejecuta a las :00, :10, :20 segundos, etc.).

Cada ciclo de ejecución sigue un modelo de concurrencia para optimizar el tiempo y evitar bloqueos:

1. **Tarea de CPU Secuencial:** Primero, se recopilan las métricas del sistema (`cpu_percent`, `ram_percent`, etc.) utilizando `psutil`. La llamada a `psutil.cpu_percent(interval=None)` es no bloqueante y mide el uso de CPU desde la última llamada.
2. **Tareas de I/O Concurrentes:** Inmediatamente después, se utiliza un `ThreadPoolExecutor` para lanzar todas las tareas de red (que son bloqueantes por naturaleza) en paralelo. Esto incluye:
    * `check_services_health`: Verifica el estado de todos los servicios definidos en las variables de entorno.
    * `check_internet_and_ping`: Mide la conectividad y latencia a `google.com`.
    * `get_container_count`: Se conecta al socket de Docker para contar los contenedores activos.
3. **Recopilación de Resultados:** El script espera a que todas las tareas concurrentes finalicen antes de continuar.
4. **Envío de Latido (Heartbeat):** Con los resultados de las comprobaciones, se construye y envía un payload al `HEARTBEAT_URL`.
5. **Procesamiento de Estado y Alertas**: Se analiza el estado del worker y de cada servicio para determinar si se ha producido un cambio de estado estable que requiera una notificación.
6. **Persistencia en Base de Datos:** Finalmente, todas las métricas y resultados del ciclo se guardan en la base de datos SQLite.

### Estimación del Tiempo de Ciclo

El uso de `ThreadPoolExecutor` significa que el tiempo de la fase de I/O está determinado por la tarea más lenta, no por la suma de todas. El `cycle_duration_ms` guardado en la base de datos registra la duración real de cada ciclo para su análisis.

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

* **Nota:** Requiere que el agente tenga acceso al socket de Docker (`/var/run/docker.sock`), lo cual ya está configurado por defecto en el `docker-compose.yml`.

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

## Persistencia de Datos (Base de Datos)

Todas las métricas se almacenan en una base de datos SQLite (`metrics.db`) con el modo `WAL` activado para mejorar la concurrencia de escritura/lectura.

| Columna | Tipo | Descripción |
| :--- | :--- | :--- |
| `id` | `TEXT` | UUID único del registro. |
| `timestamp_lima`| `TEXT` | Marca de tiempo en ISO8601 (zona horaria de Lima). |
| `cpu_percent` | `REAL` | Uso de CPU. |
| `ram_percent` | `REAL` | Uso de RAM (%). |
| `ram_used_mb` | `REAL` | RAM usada (MB). |
| `disk_percent`| `REAL` | Uso del disco raíz (%). |
| `container_count`| `INTEGER`| Contenedores Docker activos. |
| `internet_ok` | `INTEGER`| `1` si hay conexión, `0` si no. |
| `ping_ms` | `REAL` | Latencia a `google.com`. |
| `worker_status` | `INTEGER` | Código de estado HTTP retornado por la API del Cloudflare Worker. Refleja el resultado del procesamiento del latido. <br> - `200`: **Éxito**. Latido recibido, procesado y el estado del host/servicios fue actualizado. Puede indicar un estado "recorded" (sin cambios) o "recovered" (recuperación). <br> - `220`: **Advertencia (Ciego)**. Latido recibido y timestamp actualizado, pero la API no pudo leer el estado *anterior* de su base de datos. No se pudo determinar si hubo una recuperación. <br> - `221`: **Advertencia (Fallo en Actualización de Recuperación)**. Se detectó una recuperación, pero la API falló al actualizar su propio estado o al enviar la notificación. <br> - `500`: **Error Crítico del Worker**. La API falló en un paso esencial (ej. escribir el timestamp inicial) y el latido fue abortado. <br> - `NULL`: **Error del Agente Local**. El script de monitorización no pudo contactar la API del worker (ej. timeout, error de red, DNS). |
| `cycle_duration_ms` | `INTEGER` | Duración del ciclo de monitorización (ms). |
| `services_health`| `TEXT` | JSON con el estado, latencia y posible error de cada servicio. <br> Ej: `{"app": {"status": "healthy", "latency_ms": 25, "error": null}}` |

## Configuración y Despliegue

1. **Clonar el repositorio:** `git clone https://github.com/iamseb4s/heartbeat-monitor.git && cd heartbeat-monitor`
2. **Configurar `.env`:** Copia `.env.example` a `.env` y rellena `SECRET_KEY`, `HEARTBEAT_URL`, `N8N_WEBHOOK_URL`, `SERVICE_NAMES` y las `SERVICE_URL_*` correspondientes.
3. **Ejecutar:** `docker compose up -d --build`
4. **Ver Logs:** `docker compose logs -f monitor-agent`
