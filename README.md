# Nexora

Nexora es una aplicación web para administrar equipos y mantenimientos. Incluye inicio de sesión, roles de administrador y usuario, historial por equipo, alertas de mantenimiento vencido y resumen mensual. La interfaz ofrece un dashboard oscuro adaptable a móviles, navegación lateral colapsable e indicadores visuales por estado.

## Requisitos

- Python 3.10 o posterior.
- Dependencias instaladas con:

```powershell
python -m pip install -r requirements.txt
```

## Inicio rápido en Windows

Haz doble clic en `start_web.bat`. La aplicación estará disponible en <http://127.0.0.1:5000>. Mantén abierta la ventana de consola mientras uses la web; al cerrarla se detiene el servidor.

La primera vez, el launcher solicita el nombre y la contraseña de la cuenta administradora. La contraseña debe tener al menos 12 caracteres. Las cuentas posteriores se gestionan desde **Usuarios**.

## Inicio manual

Configura una clave secreta persistente, credenciales iniciales y la ruta de la base de datos:

```powershell
$env:GESTOR_PC_SECRET_KEY = python -c "import secrets; print(secrets.token_hex(32))"
$env:GESTOR_PC_USERNAME = "admin"
$env:GESTOR_PC_PASSWORD = Read-Host "Crea una contraseña segura"
$env:GESTOR_PC_DB = Join-Path $PWD "web-data\mantenimiento.db"
python web.py
```

Guarda `GESTOR_PC_SECRET_KEY` de forma segura y utiliza el mismo valor en cada reinicio para conservar las sesiones. Las credenciales de arranque solo se usan para crear la primera cuenta.

## Datos

La base de datos web se guarda en `web-data\mantenimiento.db` al usar el launcher, o en la ruta indicada por `GESTOR_PC_DB`. Haz copias de seguridad periódicas y conserva la clave secreta. La base no se debe borrar para actualizar la aplicación.

## Ejecución local con Waitress

Para usar un servidor WSGI en lugar del servidor de desarrollo de Flask:

```powershell
python -m waitress --listen=127.0.0.1:8080 web:app
```

Abre <http://127.0.0.1:8080>. No expongas el servidor directamente a internet. Para acceso remoto, despliega con HTTPS, un proxy inverso y almacenamiento persistente, y configura `GESTOR_PC_COOKIE_SECURE=true`.

Las variables `GESTOR_PC_*` y las carpetas de datos existentes se conservan para mantener la compatibilidad con instalaciones y datos previos; la marca visible de la aplicación es Nexora.

## Pruebas

```powershell
python -m unittest discover -s tests
```
