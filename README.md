# Niseko Luggage API — Railway Deployment

Backend Flask para el sistema de solicitudes de equipaje del Niseko Cluster.
Frontend publicado en GitHub Pages en `https://pickup.nisekocluster.com`.

## Archivos del proyecto

```
app.py            ← Backend principal (Flask + SQLAlchemy)
requirements.txt  ← Dependencias Python
Procfile          ← Comando de inicio (railway.json tiene prioridad)
railway.json      ← Configuración de Railway
.gitignore        ← Archivos a excluir de Git
index.html        ← Formulario de huéspedes
admin.html        ← Panel de administración
CNAME             ← Dominio personalizado de GitHub Pages (pickup.nisekocluster.com)
```

## Endpoints API

| Método | Ruta                       | Descripción                                   |
|--------|----------------------------|-----------------------------------------------|
| GET    | `/`                        | Health check                                  |
| GET    | `/api/luggage`             | Obtener todos los registros activos           |
| POST   | `/api/luggage`             | Crear nueva solicitud                         |
| GET    | `/api/luggage/trash`       | Obtener registros en papelera                 |
| POST   | `/api/luggage/trash`       | Mover registros a papelera                    |
| POST   | `/api/luggage/restore`     | Restaurar desde papelera                      |
| DELETE | `/api/luggage/permanent`   | Eliminar permanentemente                      |
| POST   | `/api/auth/login`          | Login del panel de administración             |
| POST   | `/api/send-daily-report`   | Enviar el report diario de Hilton (cron job)  |

## Despliegue en Railway

### 1. Preparar el repositorio GitHub

```bash
git init
git add .
git commit -m "Initial commit — Niseko Luggage API"
git remote add origin https://github.com/TU_USUARIO/TU_REPO.git
git push -u origin main
```

### 2. Conectar Railway al repo

1. Ve a [railway.com](https://railway.com) → New Project → Deploy from GitHub repo
2. Selecciona tu repositorio
3. Railway detecta automáticamente que es Python/Flask

### 3. Agregar base de datos PostgreSQL

En tu proyecto Railway:
- Click **+ New** → **Database** → **PostgreSQL**
- Railway conecta automáticamente `DATABASE_URL` a tu servicio Flask

### 4. Variables de entorno

Railway inyecta `DATABASE_URL` y `PORT` automáticamente. El resto se configura
en el servicio Flask → **Variables**:

| Variable                  | Uso                                                                 |
|---------------------------|---------------------------------------------------------------------|
| `ADMIN_USERS`             | Usuarios del panel admin. Formato: `Admin:pass1,Manager:pass2`      |
| `SECRET_KEY`              | Clave para firmar las sesiones del admin (cadena larga y aleatoria) |
| `REPORT_SECRET`           | Token que el cron job envía para autorizar el report diario         |
| `RESEND_API_KEY`          | API key de Resend para enviar emails                                |
| `REPORT_EMAIL_FROM`       | Remitente del report, de un dominio verificado en Resend (ej. `luggage@nisekocluster.com`) |
| `REPORT_EMAIL_TO_HILTON`  | Destinatarios del report de Hilton, separados por comas             |
| `GMAIL_FROM`              | Opcional. Dirección de respuesta (reply-to) del report              |

> Las sesiones del admin caducan a las 12 horas. Si cambias `SECRET_KEY`,
> todas las sesiones abiertas se invalidan.

### 5. Obtener tu URL pública

En Railway → tu servicio Flask → **Settings** → **Networking** → **Generate Domain**

URL actual: `https://luggagepickup-production.up.railway.app`

### 6. Actualizar los HTML

En `index.html` y `admin.html`, la constante `API_URL` debe apuntar a la URL de Railway:
```js
const API_URL = 'https://luggagepickup-production.up.railway.app';
```

## Report diario (Hilton)

Un cron job externo llama cada día a `POST /api/send-daily-report` con el header
`Authorization: Bearer <REPORT_SECRET>`.

El endpoint:
1. Calcula la fecha de mañana en hora de Japón (JST, UTC+9).
2. Busca las solicitudes de Hilton para esa fecha (sin incluir las de la papelera).
3. Si no hay ninguna, no envía nada y responde `{"sent": false}`.
4. Si hay solicitudes, genera un Excel y lo envía por email con la API de
   [Resend](https://resend.com) a los destinatarios de `REPORT_EMAIL_TO_HILTON`.

El envío usa la API HTTPS de Resend porque Railway bloquea el SMTP saliente
en los planes Free, Trial y Hobby.

**Probar manualmente:**

```bash
curl -X POST https://luggagepickup-production.up.railway.app/api/send-daily-report \
  -H "Authorization: Bearer TU_REPORT_SECRET"
```

Si falla, la respuesta y los logs de Railway muestran el error devuelto por Resend.
Los envíos también se pueden revisar en el panel **Emails** de Resend.

## Desarrollo local

```bash
# Crear entorno virtual
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Correr localmente (usa SQLite automáticamente)
python app.py
```

El servidor corre en `http://localhost:5000`.
La base de datos local se crea como `luggage.db` (ignorada por Git).
