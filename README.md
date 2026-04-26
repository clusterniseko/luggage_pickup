# Niseko Luggage API — Railway Deployment

Backend Flask para el sistema de solicitudes de equipaje del Niseko Cluster.

## Archivos del proyecto

```
app.py            ← Backend principal (Flask + SQLAlchemy)
requirements.txt  ← Dependencias Python
Procfile          ← Comando de inicio para Railway/Gunicorn
railway.json      ← Configuración de Railway
.gitignore        ← Archivos a excluir de Git
index.html        ← Formulario de huéspedes
admin.html        ← Panel de administración
```

## Endpoints API

| Método | Ruta                     | Descripción                        |
|--------|--------------------------|------------------------------------|
| GET    | `/`                      | Health check                       |
| GET    | `/api/luggage`           | Obtener todos los registros activos |
| POST   | `/api/luggage`           | Crear nueva solicitud              |
| GET    | `/api/luggage/trash`     | Obtener registros en papelera      |
| POST   | `/api/luggage/trash`     | Mover registros a papelera         |
| POST   | `/api/luggage/restore`   | Restaurar desde papelera           |
| DELETE | `/api/luggage/permanent` | Eliminar permanentemente           |

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

1. Ve a [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
2. Selecciona tu repositorio
3. Railway detecta automáticamente que es Python/Flask

### 3. Agregar base de datos PostgreSQL

En tu proyecto Railway:
- Click **+ New** → **Database** → **PostgreSQL**
- Railway conecta automáticamente `DATABASE_URL` a tu servicio Flask

### 4. Variables de entorno (opcionales)

Railway ya inyecta `DATABASE_URL` y `PORT` automáticamente.
No necesitas configurar nada más.

### 5. Obtener tu URL pública

En Railway → tu servicio Flask → **Settings** → **Networking** → **Generate Domain**

Copia esa URL (ej: `https://niseko-luggage.up.railway.app`)

### 6. Actualizar los HTML

En `index.html` y `admin.html`, reemplaza:
```js
const API_URL = 'https://YOUR-APP.up.railway.app';
```
con tu URL real:
```js
const API_URL = 'https://niseko-luggage.up.railway.app';
```

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
