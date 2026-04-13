# 💼 Gestión Financiera — Django

Sistema de gestión financiera para PyMEs. Permite registrar movimientos diarios,
boletas y facturas agrupadas, y visualizar la salud financiera de la empresa
con dashboards e indicadores clave (KPIs).

---

## 🚀 Instalación en GitHub Codespaces

### 1. Clonar y abrir en Codespaces
```bash
# En GitHub: Code → Codespaces → New codespace
# O desde terminal local:
git clone https://github.com/TU_USUARIO/TU_REPO.git
cd gestion-financiera
```

### 2. Crear y activar entorno virtual
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Crear archivo de configuración
```bash
cp .env.example .env
# Editar .env con el nombre de tu empresa (opcional)
```

### 5. Crear la base de datos e inicializar
```bash
python manage.py makemigrations contabilidad
python manage.py migrate
python manage.py seed_inicial
```

### 6. Iniciar el servidor
```bash
python manage.py runserver 0.0.0.0:8000
```

Abre el puerto **8000** en el panel de Codespaces → **Open in Browser**.

---

## 🖥️ Instalación en servidor local (Windows/Linux/Mac)

### Requisitos
- Python 3.10 o superior
- pip

### Pasos en Linux / Mac
```bash
# Clonar proyecto
git clone https://github.com/TU_USUARIO/TU_REPO.git
cd gestion-financiera

# Crear y activar entorno virtual
python3 -m venv venv
source venv/bin/activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar entorno
cp .env.example .env

# Crear base de datos
python manage.py makemigrations contabilidad
python manage.py migrate
python manage.py seed_inicial

# Iniciar servidor
python manage.py runserver
```

### Pasos en Windows
```bash
# Clonar proyecto
git clone https://github.com/TU_USUARIO/TU_REPO.git
cd gestion-financiera

# Crear y activar entorno virtual
python -m venv venv
venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Configurar entorno
copy .env.example .env

# Crear base de datos
python manage.py makemigrations contabilidad
python manage.py migrate
python manage.py seed_inicial

# Iniciar servidor
python manage.py runserver
```

Accede en el navegador: **http://127.0.0.1:8000**

> ⚠️ **Importante:** cada vez que abras una nueva terminal debes activar el venv antes de correr el servidor:
> - Linux/Mac: `source venv/bin/activate`
> - Windows: `venv\Scripts\activate`

---

## 📁 Estructura del Proyecto

```
gestion-financiera/
├── manage.py
├── requirements.txt
├── .env.example
├── .gitignore
├── db.sqlite3              ← base de datos (se crea con migrate)
├── gestion_financiera/     ← configuración Django
│   ├── settings.py
│   ├── urls.py
│   └── wsgi.py
├── contabilidad/           ← app principal
│   ├── models.py           ← modelos de datos
│   ├── views.py            ← endpoints API REST
│   ├── urls.py             ← rutas
│   ├── utils.py            ← cálculos financieros y KPIs
│   └── management/
│       └── commands/
│           └── seed_inicial.py
└── templates/
    └── index.html          ← frontend completo (SPA)
```

---

## 📊 Funcionalidades

| Módulo | Descripción |
|--------|-------------|
| **Dashboard** | Resumen financiero con gráficos en tiempo real |
| **Nuevo Movimiento** | Registro de ingresos, egresos, boletas y facturas |
| **Historial** | Búsqueda y filtrado de todos los movimientos |
| **Cierre Diario** | Cuadre de caja al final del día |
| **Salud Financiera** | KPIs con semáforo: margen, cobertura, punto de equilibrio |
| **Presupuesto** | Planificación mensual por categorías |
| **Configuración** | Datos de la empresa y saldos iniciales |

---

## 🔗 API Endpoints

| Método | URL | Descripción |
|--------|-----|-------------|
| GET | `/` | Frontend SPA |
| GET/POST | `/api/movimientos` | Listar / crear movimientos |
| PUT/DELETE | `/api/movimientos/<id>` | Editar / eliminar |
| GET | `/api/dashboard` | Datos del dashboard + KPIs |
| GET | `/api/resumen/<anio>/<mes>` | Resumen mensual |
| GET/POST | `/api/cierres` | Historial / registrar cierre |
| GET/POST | `/api/presupuesto` | Presupuesto mensual |
| GET/POST | `/api/configuracion` | Config empresa |
| GET | `/api/tipos` | Catálogo tipos de movimiento |
| GET | `/api/calcular-iva?monto=X` | Calculadora IVA 19% |

---

## 💡 Uso Básico

### Registrar las ventas del día
1. Ir a **Nuevo Movimiento**
2. Seleccionar tipo: **Suma de Boletas** o **Suma Facturas Emitidas**
3. Ingresar el **monto total** del día (suma de todas las boletas)
4. Si es factura, el IVA se calcula automáticamente
5. Guardar

### Ver la salud de la empresa
1. Ir a **Salud Financiera**
2. El semáforo (🟢🟡🔴) indica el estado de cada indicador:
   - **Margen Bruto**: qué tan rentable es cada venta
   - **Cobertura de Gastos**: si las ventas cubren todos los egresos
   - **Punto de Equilibrio**: cuántos días del mes vendes "para pagar costos"
   - **Resultado del Período**: si ganaste o perdiste dinero

### Cierre diario
1. Ir a **Cierre del Día**
2. Verificar la fecha (por defecto hoy)
3. Presionar **Generar Cierre**
4. El sistema calcula saldo inicial, ingresos, egresos y saldo final automáticamente

---

## 🔒 Backup de la base de datos

La base de datos es el archivo `db.sqlite3`. Para respaldarla:

```bash
# Copia simple
cp db.sqlite3 backups/db_$(date +%Y%m%d).sqlite3

# O exportar a JSON
python manage.py dumpdata > backup_$(date +%Y%m%d).json
```

---

## 🐛 Solución de Problemas

**Error: No module named 'django'**
```bash
pip install -r requirements.txt
```

**Error: No such table**
```bash
python manage.py migrate
```

**Puerto 8000 ocupado**
```bash
python manage.py runserver 0.0.0.0:8001
```
