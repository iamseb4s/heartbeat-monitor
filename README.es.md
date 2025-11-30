# Monitor de Latido (Heartbeat Monitor): Agente de Servidor Local

## Resumen

Este repositorio contiene un agente Pythonizado y contenedorizado con Docker diseñado para monitorizar el estado de un servidor local. Recopila métricas del sistema, cuenta los contenedores Docker en ejecución, verifica la conectividad a Internet y envía latidos regulares a una API de Cloudflare Worker. También se integra con una instancia local de n8n para alertas inmediatas si el propio servicio de monitorización de Cloudflare deja de ser accesible.

## Características

* **Recopilación de Métricas del Sistema:** Reúne estadísticas de uso de CPU, RAM y Disco.
* **Conteo de Contenedores Docker:** Monitoriza el número de contenedores Docker activos en el host.
* **Verificación de Conectividad a Internet:** Verifica el acceso a Internet y mide la latencia a un endpoint externo fiable.
* **Ejecución Alineada al Reloj:** Se ejecuta cada 10 segundos, precisamente alineado con el reloj del sistema (por ejemplo, a los :00, :10, :20 segundos).
* **Latido de Cloudflare:** Envía peticiones POST autenticadas a un Cloudflare Worker, actuando como una señal de "latido".
* **Alerta Local (n8n):** Activa un webhook local de n8n si el Cloudflare Worker deja de ser accesible, proporcionando un mecanismo de alerta redundante.
* **Registro de Datos Persistente:** Almacena todas las métricas recopiladas en una base de datos SQLite local (`metrics.db`) para análisis histórico.
* **Lógica de Alerta Robusta:** Suprime las alertas iniciales al inicio, pero notifica todos los cambios de estado posteriores (transiciones en línea/fuera de línea).

## Esquema de la Base de Datos

Los datos recopilados se almacenan en una base de datos SQLite (`metrics.db`) dentro del directorio `data/`. La tabla principal es `metrics`:

| Columna | Tipo | Descripción |
| :-------------- | :------- | :----------------------------------------------------------------------- |
| `id` | `TEXT` (UUID) | Clave Primaria, un identificador único para el registro. |
| `timestamp_lima` | `TEXT` (ISO8601) | Marca de tiempo del registro en la zona horaria de Lima (UTC-5). |
| `cpu_percent` | `REAL` | Porcentaje de uso de CPU. |
| `ram_percent` | `REAL` | Porcentaje de uso de RAM. |
| `ram_used_mb` | `REAL` | RAM utilizada en Megabytes. |
| `disk_percent` | `REAL` | Porcentaje de uso del disco del sistema de archivos raíz. |
| `container_count`| `INTEGER` | Número de contenedores Docker en ejecución. |
| `internet_ok` | `INTEGER` | `1` si Internet es accesible, `0` en caso contrario. |
| `ping_ms` | `REAL` | Latencia en milisegundos a un servidor de prueba (Google). `NULL` si no hay Internet. |
| `worker_status` | `INTEGER` | Código de estado HTTP del latido enviado al Cloudflare Worker. `NULL` si el latido falló. |
| `cycle_duration_ms` | `REAL` | Duración del ciclo de monitoreo actual en milisegundos. |

## `monitor.py` - El Script Agente Principal

El script `app/monitor.py` es el componente central responsable de:

* **Gestión de la Base de Datos:** Inicializa `metrics.db` con el modo WAL habilitado y crea la tabla `metrics`.
* **Recopilación de Métricas:** Invoca varias funciones (`get_system_metrics`, `get_container_count`, `check_internet_and_ping`) para recopilar el estado del servidor.
* **Transmisión de Latidos:** Envía datos autenticados a la `HEARTBEAT_URL` configurada.
* **Alineación al Reloj:** Gestiona el bucle de ejecución para asegurar que las métricas se recopilen precisamente cada 10 segundos.
* **Persistencia de Estado:** Lee el `last_worker_status` de la base de datos al inicio para mantener el contexto de alerta entre reinicios.
* **Lógica de Alerta:** Detecta cambios en `worker_status` y envía alertas detalladas al webhook de n8n, suprimiendo inteligentemente los falsos positivos en el inicio inicial.

## Cómo Empezar

Sigue estos pasos para configurar y ejecutar el Monitor de Latido:

1. **Clonar el repositorio:**

    ```bash
    git clone https://github.com/iamseb4s/heartbeat-monitor.git
    cd heartbeat-monitor
    ```

2. **Configurar Variables de Entorno:**
    Copia el archivo de ejemplo de variables de entorno y rellena tus datos:

    ```bash
    cp .env.example .env
    ```

    Edita el archivo `.env` con tu `SECRET_KEY`, `HEARTBEAT_URL` (el endpoint de tu Cloudflare Worker) y `N8N_WEBHOOK_URL` (el webhook de tu n8n local para alertas locales). Consulta `.env.example` para más detalles.

3. **Ejecutar con Docker Compose:**
    Construye la imagen de Docker e inicia el servicio de monitorización:

    ```bash
    docker compose up -d --build
    ```

4. **Ver Registros (Logs):**
    Para ver la salida del monitor:

    ```bash
    docker compose logs -f monitor-agent
    ```

    (Presiona `Ctrl+C` para salir de los logs).

5. **Inspeccionar Base de Datos:**
    Para ver los últimos registros que se están escribiendo en la base de datos (sin necesidad de ejecutar como root):

    ```bash
    sqlite3 data/metrics.db "SELECT * FROM metrics ORDER BY timestamp_lima DESC LIMIT 20;"
    ```

## Solución de Problemas

Si encuentras errores de permisos con `metrics.db` o el socket de Docker:

* Asegúrate de que el directorio `data/` sea propiedad de tu usuario (`ls -l data/`).
* Verifica que el UID de tu usuario y el GID del grupo Docker estén configurados correctamente en `docker-compose.yml` (`user: "TU_UID:GID_DOCKER"`). Puedes encontrar tu UID con `id -u` y el GID de Docker con `getent group docker | cut -d: -f3`.
