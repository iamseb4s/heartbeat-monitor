# Monitor de Latido (Heartbeat Monitor): Documentación Técnica

## Resumen

Este documento detalla la arquitectura y el funcionamiento interno del agente de monitorización. El agente es un script de Python que se ejecuta en un contenedor Docker y está diseñado para evaluar la salud de un servidor y sus servicios, reportando métricas a un endpoint externo y a una base de datos local.

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

Los servicios a monitorizar no están codificados en el script. Se configuran dinámicamente a través de variables de entorno:

1. **`SERVICE_NAMES`**: Una lista de nombres de servicio separados por comas (ej: `SERVICE_NAMES=nextjs,strapi,umami`).
2. **`SERVICE_URL_{name}`**: La URL a comprobar para cada nombre de servicio definido (ej: `SERVICE_URL_nextjs=https://www.example.com`).

Un servicio se considera `"healthy"` si responde con un código de estado `2xx` o `3xx`. De lo contrario, se marca como `"unhealthy"`.

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

El sistema envía alertas al `N8N_WEBHOOK_URL` (el único canal para todas las notificaciones) bajo las siguientes condiciones:

1. **Caída de un Servicio:**
    * Si un servicio reporta un estado `unhealthy` durante `STATUS_CHANGE_THRESHOLD` (actualmente 4) ciclos consecutivos, se envía una alerta de "Servicio Caído".

2. **Recuperación de un Servicio:**
    * Si un servicio que estaba caído reporta `healthy` **una sola vez**, se envía una alerta de "Servicio Recuperado" de forma inmediata.

3. **Cambio de Estado del Worker:**
    * Utiliza el mismo umbral `STATUS_CHANGE_THRESHOLD` para confirmar un cambio de estado estable (ej. de `200` a `500`).
    * La recuperación a un estado `200` se notifica de inmediato.
    * Los mensajes de alerta son personalizados para cada código de estado (`200`, `220`, `221`, `500`) y para los casos en que el worker es inaccesible (debido a falta de internet o a un fallo de la API), proporcionando un contexto más preciso.

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
| `cycle_duration_ms` | `REAL` | Duración del ciclo de monitorización (ms). |
| `services_health`| `TEXT` | JSON con el estado detallado y latencia de cada servicio. |

## Configuración y Despliegue

1. **Clonar el repositorio:** `git clone https://github.com/iamseb4s/heartbeat-monitor.git && cd heartbeat-monitor`
2. **Configurar `.env`:** Copia `.env.example` a `.env` y rellena `SECRET_KEY`, `HEARTBEAT_URL`, `N8N_WEBHOOK_URL`, `SERVICE_NAMES` y las `SERVICE_URL_*` correspondientes.
3. **Ejecutar:** `docker compose up -d --build`
4. **Ver Logs:** `docker compose logs -f monitor-agent`
