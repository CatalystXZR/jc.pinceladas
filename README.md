# Plataforma de Cursos - jc.pinceladas

MVP mejorado para gestionar clientas, cursos por video y accesos temporales.

## Objetivo

- Uso ultra simple para administradora y clientas.
- Bajo costo de mantenimiento.
- Preparado para escalar con **Supabase (Postgres)** y **Vercel**.

## Stack

- Python + Flask
- Flask-Login, Flask-SQLAlchemy, Flask-Mail
- APScheduler (solo local / servidores persistentes)
- Templates Jinja2 + CSS

## Funcionalidades actuales

- Login de admin y clienta (clave simple)
- Panel admin:
  - clientas (crear, ver, buscar)
  - cursos (crear, editar, activar/desactivar)
  - accesos (agregar, revocar, reactivar, extender)
  - cambio de contraseña
  - bitácora de actividad
- Zona clienta:
  - ver cursos activos
  - reproducir video embebido
- Automatización:
  - recordatorios de expiración
  - desactivación automática de accesos vencidos

## Mejoras aplicadas en esta versión

- Seguridad:
  - CSRF en formularios POST
  - headers de seguridad (CSP, HSTS en producción, etc.)
  - rate-limit básico de login por IP
  - contraseña admin mínima de 8 caracteres
- Escalabilidad:
  - soporte para `DATABASE_URL` (Supabase Postgres)
  - índices en tablas de alto uso
  - endpoint interno para cron en Vercel
- Operación:
  - healthcheck `/health`
  - bitácora `eventos_sistema`
  - correos de bienvenida/recordatorio reestilizados
- UX/UI:
  - rediseño completo alineado a estilo artesanal de marca
  - mejor legibilidad en móvil y escritorio

## Variables de entorno

Configura en `.env` local y en Vercel (Production):

- `APP_ENV=production`
- `SECRET_KEY=<clave-larga-segura>`
- `DATABASE_URL=<url-postgresql-supabase>`
- `PLATFORM_URL=https://tu-dominio.vercel.app`
- `BRAND_NAME=jc.pinceladas`
- `SUPPORT_WHATSAPP=+56 9 ...`
- `SUPPORT_INSTAGRAM=@jc.pinceladas_`
- `BRAND_LOGO_URL=https://.../logo.png` (opcional)
- `BRAND_PROFILE_URL=https://.../foto-perfil.jpg` (opcional)
- `INTERNAL_CRON_TOKEN=<token-seguro>`
- `CRON_SECRET=<token-seguro>` (opcional, compatible con Vercel Cron)

Correo (si se usará envío real):

- `MAIL_SERVER=smtp.gmail.com`
- `MAIL_PORT=587`
- `MAIL_USE_TLS=true`
- `MAIL_USERNAME=<correo>`
- `MAIL_PASSWORD=<app-password>`
- `MAIL_DEFAULT_SENDER=<correo>`

Bootstrap admin inicial (solo si no existe admin):

- `BOOTSTRAP_ADMIN_USERNAME=ADMIN`
- `BOOTSTRAP_ADMIN_EMAIL=<correo-admin>`
- `BOOTSTRAP_ADMIN_PASSWORD=<clave-admin>`

## Desarrollo local

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Despliegue en Vercel + Supabase

1. Crear proyecto en Supabase y copiar `DATABASE_URL` (pooler).
2. Configurar variables de entorno en Vercel.
3. Desplegar este repo.
4. Crear cron en Vercel para ejecutar (por ejemplo, diario 09:00 UTC):

```bash
GET /internal/verificar-expiraciones
Authorization: Bearer <INTERNAL_CRON_TOKEN o CRON_SECRET>
```

Si usas Vercel Cron sin headers custom, deja configurado `CRON_SECRET`.

## Notas importantes

- En producción serverless, no dependas del scheduler interno; usa cron externo.
- `AUTO_INIT_DB` por defecto queda desactivado en producción.
- Cambia cualquier valor demo de `.env` antes de usar con clientas reales.
- Si no configuras `BRAND_LOGO_URL`, la app intentará usar automáticamente `static/brand/logo_tienda.jpg` (o png/jpg/jpeg/webp/svg).
- Si no configuras `BRAND_PROFILE_URL`, intentará usar `static/brand/profile.png` (o jpg/jpeg/webp).
