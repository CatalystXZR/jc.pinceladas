from collections import defaultdict, deque
from datetime import datetime, timedelta
from functools import wraps
from threading import Lock
import os
import re
import secrets

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from sqlalchemy import or_, text
from werkzeug.security import check_password_hash, generate_password_hash

from database import Acceso, Admin, Clienta, Curso, EventoSistema, db
from email_service import enviar_bienvenida, enviar_recordatorio, mail

load_dotenv()


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on', 'si'}


def env_int(name, default):
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def normalizar_database_url(url):
    if not url:
        return ''
    if url.startswith('postgres://'):
        return url.replace('postgres://', 'postgresql://', 1)
    return url


def resolver_database_uri():
    database_url = normalizar_database_url(os.getenv('DATABASE_URL', '').strip())
    if database_url:
        return database_url
    return 'sqlite:///ceramica.db'


def limpiar_texto(valor):
    return (valor or '').strip()


def parsear_dias(valor, default=60):
    try:
        dias = int(valor)
    except (TypeError, ValueError):
        return default
    return max(1, min(dias, 365))


def parsear_entero(valor, default=None):
    try:
        return int(valor)
    except (TypeError, ValueError):
        return default


IS_VERCEL = bool(os.getenv('VERCEL'))
IS_PRODUCTION = (
    os.getenv('APP_ENV', '').lower() == 'production'
    or os.getenv('VERCEL_ENV', '').lower() == 'production'
)

DATABASE_URI = resolver_database_uri()
SECRET_KEY = limpiar_texto(os.getenv('SECRET_KEY'))
if not SECRET_KEY:
    if IS_PRODUCTION:
        raise RuntimeError('SECRET_KEY es obligatoria en producción.')
    SECRET_KEY = secrets.token_urlsafe(32)


# ============================================================
# CONFIGURACIÓN DE LA APLICACIÓN
# ============================================================
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Cookies y sesión
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = IS_PRODUCTION
app.config['REMEMBER_COOKIE_SECURE'] = IS_PRODUCTION
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Marca / contacto
app.config['BRAND_NAME'] = os.getenv('BRAND_NAME', 'jc.pinceladas')
app.config['PLATFORM_URL'] = os.getenv('PLATFORM_URL', 'http://localhost:5000')
app.config['SUPPORT_WHATSAPP'] = os.getenv('SUPPORT_WHATSAPP', '+56 9 XXXX XXXX')
app.config['SUPPORT_INSTAGRAM'] = os.getenv('SUPPORT_INSTAGRAM', '@jc.pinceladas_')
app.config['BRAND_LOGO_URL'] = limpiar_texto(os.getenv('BRAND_LOGO_URL'))
app.config['BRAND_PROFILE_URL'] = limpiar_texto(os.getenv('BRAND_PROFILE_URL'))

# Seguridad y operación
app.config['ENABLE_SCHEDULER'] = env_bool('ENABLE_SCHEDULER', default=not IS_VERCEL)
app.config['INTERNAL_CRON_TOKEN'] = limpiar_texto(os.getenv('INTERNAL_CRON_TOKEN'))
app.config['LOGIN_RATE_LIMIT_ATTEMPTS'] = env_int('LOGIN_RATE_LIMIT_ATTEMPTS', 8)
app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS'] = env_int('LOGIN_RATE_LIMIT_WINDOW_SECONDS', 900)

# ============================================================
# CONFIGURACIÓN DE CORREO ELECTRÓNICO
# ============================================================
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = env_int('MAIL_PORT', 587)
app.config['MAIL_USE_TLS'] = env_bool('MAIL_USE_TLS', True)
app.config['MAIL_USERNAME'] = limpiar_texto(os.getenv('MAIL_USERNAME'))
app.config['MAIL_PASSWORD'] = limpiar_texto(os.getenv('MAIL_PASSWORD'))
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', app.config['MAIL_USERNAME'])
app.config['MAIL_SUPPRESS_SEND'] = env_bool('MAIL_SUPPRESS_SEND', False)

if DATABASE_URI.startswith('postgresql://'):
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': env_int('DB_POOL_RECYCLE', 300),
        'pool_size': env_int('DB_POOL_SIZE', 2),
        'max_overflow': env_int('DB_MAX_OVERFLOW', 3),
    }


# Inicializar extensiones
db.init_app(app)
mail.init_app(app)


# ============================================================
# FILTRO DE FECHA EN ESPAÑOL
# ============================================================
MESES_ES = {
    1: 'enero',
    2: 'febrero',
    3: 'marzo',
    4: 'abril',
    5: 'mayo',
    6: 'junio',
    7: 'julio',
    8: 'agosto',
    9: 'septiembre',
    10: 'octubre',
    11: 'noviembre',
    12: 'diciembre',
}


@app.template_filter('fecha_es')
def fecha_es(fecha):
    if not fecha:
        return '-'
    return f"{fecha.day} de {MESES_ES[fecha.month]} de {fecha.year}"


# ============================================================
# SISTEMA DE LOGIN
# ============================================================
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor inicia sesión para continuar.'
login_manager.login_message_category = 'warning'


@login_manager.unauthorized_handler
def unauthorized():
    if request.path.startswith('/admin'):
        return redirect(url_for('admin_login', next=request.full_path))
    return redirect(url_for('login', next=request.full_path))


@login_manager.user_loader
def load_user(user_id):
    if user_id.startswith('admin_'):
        return db.session.get(Admin, int(user_id.split('_')[1]))
    if user_id.startswith('clienta_'):
        return db.session.get(Clienta, int(user_id.split('_')[1]))
    return None


# ============================================================
# PROTECCIÓN CSRF SIMPLE
# ============================================================
CSRF_SESSION_KEY = '_csrf_token'


def generar_csrf_token():
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


@app.context_processor
def inyectar_contexto_global():
    def resolver_asset_brand(url_configurada, candidatos_relativos):
        if url_configurada:
            return url_configurada
        for asset_rel in candidatos_relativos:
            if os.path.exists(os.path.join(app.static_folder, asset_rel)):
                return url_for('static', filename=asset_rel)
        return ''

    logo_url = resolver_asset_brand(
        app.config['BRAND_LOGO_URL'],
        (
            'brand/logo_tienda.jpg',
            'brand/logo.png',
            'brand/logo.jpg',
            'brand/logo.jpeg',
            'brand/logo.webp',
            'brand/logo.svg',
        ),
    )
    profile_url = resolver_asset_brand(
        app.config['BRAND_PROFILE_URL'],
        (
            'brand/profile.png',
            'brand/profile.jpg',
            'brand/profile.jpeg',
            'brand/profile.webp',
        ),
    )

    return {
        'csrf_token': generar_csrf_token,
        'brand_name': app.config['BRAND_NAME'],
        'brand_logo_url': logo_url,
        'brand_profile_url': profile_url,
        'support_whatsapp': app.config['SUPPORT_WHATSAPP'],
        'support_instagram': app.config['SUPPORT_INSTAGRAM'],
    }


@app.before_request
def proteger_csrf():
    if request.method not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        return

    # Endpoint interno usa token Bearer
    if request.endpoint == 'internal_verificar_expiraciones':
        return

    token_formulario = request.form.get('_csrf_token') or request.headers.get('X-CSRFToken')
    token_sesion = session.get(CSRF_SESSION_KEY)
    if not token_sesion or not token_formulario:
        abort(400, description='Solicitud inválida (CSRF).')
    if not secrets.compare_digest(token_sesion, token_formulario):
        abort(400, description='Token de seguridad inválido.')


@app.after_request
def agregar_headers_seguridad(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')

    csp = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "script-src 'self' 'unsafe-inline'; "
        "frame-src https://www.youtube.com https://player.vimeo.com https://drive.google.com;"
    )
    response.headers.setdefault('Content-Security-Policy', csp)

    if IS_PRODUCTION:
        response.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')

    return response


# ============================================================
# LIMITADOR SIMPLE DE LOGIN POR IP
# ============================================================
LOGIN_ATTEMPTS = defaultdict(deque)
LOGIN_ATTEMPTS_LOCK = Lock()


def obtener_ip_cliente():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or 'ip_desconocida'


def limpiar_intentos_antiguos(ip):
    ventana = app.config['LOGIN_RATE_LIMIT_WINDOW_SECONDS']
    ahora = datetime.utcnow()
    historial = LOGIN_ATTEMPTS[ip]
    while historial and (ahora - historial[0]).total_seconds() > ventana:
        historial.popleft()


def ip_bloqueada(ip):
    with LOGIN_ATTEMPTS_LOCK:
        limpiar_intentos_antiguos(ip)
        return len(LOGIN_ATTEMPTS[ip]) >= app.config['LOGIN_RATE_LIMIT_ATTEMPTS']


def registrar_intento_fallido(ip):
    with LOGIN_ATTEMPTS_LOCK:
        limpiar_intentos_antiguos(ip)
        LOGIN_ATTEMPTS[ip].append(datetime.utcnow())


def limpiar_intentos_exitosos(ip):
    with LOGIN_ATTEMPTS_LOCK:
        LOGIN_ATTEMPTS.pop(ip, None)


# ============================================================
# BITÁCORA DE EVENTOS
# ============================================================
def registrar_evento(accion, entidad=None, detalle=None, actor=None, actor_tipo=None):
    try:
        if actor is not None:
            if isinstance(actor, Admin):
                actor_tipo = 'admin'
                actor_id = actor.id
                actor_nombre = actor.username
            elif isinstance(actor, Clienta):
                actor_tipo = 'clienta'
                actor_id = actor.id
                actor_nombre = actor.nombre
            else:
                actor_tipo = actor_tipo or 'sistema'
                actor_id = None
                actor_nombre = str(actor)
        else:
            actor_tipo = actor_tipo or 'sistema'
            actor_id = None
            actor_nombre = 'Sistema'

        evento = EventoSistema(
            actor_tipo=actor_tipo,
            actor_id=actor_id,
            actor_nombre=actor_nombre,
            accion=accion,
            entidad=entidad,
            detalle=detalle,
        )
        db.session.add(evento)
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception('No se pudo registrar evento: %s', accion)


# ============================================================
# TAREA AUTOMÁTICA: Verificar accesos por expirar
# ============================================================
def verificar_expiraciones():
    with app.app_context():
        ahora = datetime.utcnow()
        en_7_dias = ahora + timedelta(days=7)

        recordatorios_enviados = 0
        accesos_desactivados = 0

        accesos_por_expirar = Acceso.query.filter(
            Acceso.activo.is_(True),
            Acceso.fecha_expiracion <= en_7_dias,
            Acceso.fecha_expiracion > ahora,
            Acceso.recordatorio_enviado.is_(False),
        ).all()

        for acceso in accesos_por_expirar:
            if enviar_recordatorio(app, acceso):
                acceso.recordatorio_enviado = True
                recordatorios_enviados += 1

        expirados = Acceso.query.filter(
            Acceso.activo.is_(True),
            Acceso.fecha_expiracion <= ahora,
        ).all()
        for acceso in expirados:
            acceso.activo = False
            accesos_desactivados += 1

        db.session.commit()

        if recordatorios_enviados or accesos_desactivados:
            registrar_evento(
                actor_tipo='sistema',
                accion='Verificación de expiraciones',
                entidad='accesos',
                detalle=(
                    f'Recordatorios enviados: {recordatorios_enviados} | '
                    f'Accesos desactivados: {accesos_desactivados}'
                ),
            )

        return {
            'recordatorios_enviados': recordatorios_enviados,
            'accesos_desactivados': accesos_desactivados,
        }


scheduler = BackgroundScheduler(timezone='UTC', daemon=True)


def iniciar_scheduler():
    if scheduler.running:
        return
    scheduler.add_job(
        verificar_expiraciones,
        'cron',
        hour=9,
        minute=0,
        id='verificar_expiraciones',
        replace_existing=True,
    )
    scheduler.start()
    app.logger.info('Scheduler iniciado (09:00 UTC).')


# ============================================================
# DECORADOR ADMIN
# ============================================================
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not isinstance(current_user, Admin):
            abort(403)
        return f(*args, **kwargs)

    return decorated_function


# ============================================================
# UTILIDADES DE VIDEO
# ============================================================
def generar_embed_url(url, tipo):
    """Convierte URL de video a URL embed."""
    if tipo == 'youtube':
        match = re.search(
            r'(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|shorts/))([a-zA-Z0-9_-]{11})',
            url,
        )
        if match:
            video_id = match.group(1)
            return f'https://www.youtube.com/embed/{video_id}?rel=0&modestbranding=1'

    elif tipo == 'vimeo':
        match = re.search(r'vimeo\.com/(\d+)', url)
        if match:
            return f'https://player.vimeo.com/video/{match.group(1)}?dnt=1'

    elif tipo == 'drive':
        match = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
        if match:
            return f'https://drive.google.com/file/d/{match.group(1)}/preview'

    return url


# ============================================================
# RUTAS DE SALUD / OPERACIÓN
# ============================================================
@app.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        db_ok = True
    except Exception:
        db_ok = False

    return jsonify(
        {
            'ok': db_ok,
            'database': 'up' if db_ok else 'down',
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        }
    ), 200 if db_ok else 503


@app.route('/internal/verificar-expiraciones', methods=['GET', 'POST'])
def internal_verificar_expiraciones():
    token_esperado = app.config['INTERNAL_CRON_TOKEN'] or limpiar_texto(os.getenv('CRON_SECRET'))
    if not token_esperado:
        abort(403)

    auth_header = request.headers.get('Authorization', '')
    if auth_header != f'Bearer {token_esperado}':
        abort(401)

    resultado = verificar_expiraciones()
    return jsonify({'ok': True, **resultado})


# ============================================================
# RUTAS DE AUTENTICACIÓN
# ============================================================
@app.route('/')
def index():
    if current_user.is_authenticated:
        if isinstance(current_user, Admin):
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('clienta_cursos'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))

    next_url = request.args.get('next', '')

    if request.method == 'POST':
        ip = obtener_ip_cliente()
        if ip_bloqueada(ip):
            flash('Demasiados intentos. Espera 15 minutos antes de volver a intentar.', 'danger')
            return render_template('login.html'), 429

        clave = limpiar_texto(request.form.get('clienta_clave')).upper()
        if not clave:
            registrar_intento_fallido(ip)
            flash('Debes ingresar tus datos para continuar.', 'warning')
            return render_template('login.html'), 400

        clienta = Clienta.query.filter_by(clave_acceso=clave).first()
        if clienta and clienta.activa:
            login_user(clienta)
            session.permanent = True
            limpiar_intentos_exitosos(ip)

            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('clienta_cursos'))

        registrar_intento_fallido(ip)
        flash('Clave incorrecta o cuenta inactiva. Intenta de nuevo.', 'danger')

    return render_template('login.html')


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        if isinstance(current_user, Admin):
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('clienta_cursos'))

    next_url = request.args.get('next', '')

    if request.method == 'POST':
        ip = obtener_ip_cliente()
        if ip_bloqueada(ip):
            flash('Demasiados intentos. Espera 15 minutos antes de volver a intentar.', 'danger')
            return render_template('admin_login.html'), 429

        username = limpiar_texto(request.form.get('admin_username')).upper()
        password = limpiar_texto(request.form.get('admin_password'))
        if not username or not password:
            registrar_intento_fallido(ip)
            flash('Ingresa usuario y contraseña para continuar.', 'warning')
            return render_template('admin_login.html'), 400

        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password_hash, password):
            login_user(admin)
            session.permanent = True
            limpiar_intentos_exitosos(ip)

            if next_url.startswith('/') and not next_url.startswith('//'):
                return redirect(next_url)
            return redirect(url_for('admin_dashboard'))

        registrar_intento_fallido(ip)
        flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('admin_login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión correctamente.', 'success')
    return redirect(url_for('login'))


# ============================================================
# RUTAS DEL PANEL DE ADMINISTRACIÓN
# ============================================================
@app.route('/admin')
@login_required
@admin_required
def admin_dashboard():
    ahora = datetime.utcnow()
    en_7_dias = ahora + timedelta(days=7)

    total_clientas = Clienta.query.filter_by(activa=True).count()
    total_cursos = Curso.query.filter_by(activo=True).count()
    accesos_activos = Acceso.query.filter(
        Acceso.activo.is_(True),
        Acceso.fecha_expiracion > ahora,
    ).count()

    por_expirar = Acceso.query.filter(
        Acceso.activo.is_(True),
        Acceso.fecha_expiracion <= en_7_dias,
        Acceso.fecha_expiracion > ahora,
    ).all()

    ultimas_clientas = Clienta.query.order_by(Clienta.created_at.desc()).limit(5).all()
    ultimos_eventos = EventoSistema.query.order_by(EventoSistema.created_at.desc()).limit(8).all()

    return render_template(
        'admin/dashboard.html',
        total_clientas=total_clientas,
        total_cursos=total_cursos,
        accesos_activos=accesos_activos,
        por_expirar=por_expirar,
        ultimas_clientas=ultimas_clientas,
        ultimos_eventos=ultimos_eventos,
    )


@app.route('/admin/clientas')
@login_required
@admin_required
def admin_clientas():
    busqueda = limpiar_texto(request.args.get('buscar'))
    if busqueda:
        clientas = Clienta.query.filter(
            or_(
                Clienta.nombre.ilike(f'%{busqueda}%'),
                Clienta.email.ilike(f'%{busqueda}%'),
                Clienta.codigo.ilike(f'%{busqueda}%'),
            )
        ).order_by(Clienta.created_at.desc()).all()
    else:
        clientas = Clienta.query.order_by(Clienta.created_at.desc()).all()

    return render_template('admin/clientas.html', clientas=clientas, busqueda=busqueda)


@app.route('/admin/clientas/nueva', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_nueva_clienta():
    cursos = Curso.query.filter_by(activo=True).order_by(Curso.nombre.asc()).all()

    if request.method == 'POST':
        nombre = limpiar_texto(request.form.get('nombre'))
        email = limpiar_texto(request.form.get('email')).lower()
        telefono = limpiar_texto(request.form.get('telefono'))
        curso_id = limpiar_texto(request.form.get('curso_id'))
        dias = parsear_dias(request.form.get('dias_acceso'), 60)
        notas = limpiar_texto(request.form.get('notas'))

        if not nombre or not email:
            flash('Nombre y correo son obligatorios.', 'danger')
            return render_template('admin/nueva_clienta.html', cursos=cursos)

        if Clienta.query.filter_by(email=email).first():
            flash('Ya existe una clienta con ese correo.', 'danger')
            return render_template('admin/nueva_clienta.html', cursos=cursos)

        clienta = Clienta(
            codigo=Clienta.generar_codigo(),
            nombre=nombre,
            email=email,
            telefono=telefono or None,
            clave_acceso=Clienta.generar_clave(),
        )
        db.session.add(clienta)
        db.session.flush()

        acceso = None
        if curso_id:
            curso_id_int = parsear_entero(curso_id)
            curso = db.session.get(Curso, curso_id_int) if curso_id_int else None
            if curso and curso.activo:
                acceso = Acceso(
                    clienta_id=clienta.id,
                    curso_id=curso.id,
                    fecha_expiracion=datetime.utcnow() + timedelta(days=dias),
                    notas=notas or None,
                )
                db.session.add(acceso)

        db.session.commit()

        if acceso:
            enviar_bienvenida(app, clienta, acceso)

        registrar_evento(
            actor=current_user,
            accion='Creó clienta',
            entidad=f'Clienta #{clienta.id}',
            detalle=f'{clienta.nombre} ({clienta.email})',
        )

        flash(f'Clienta "{nombre}" creada. Clave de acceso: {clienta.clave_acceso}', 'success')
        return redirect(url_for('admin_detalle_clienta', clienta_id=clienta.id))

    return render_template('admin/nueva_clienta.html', cursos=cursos)


@app.route('/admin/clientas/<int:clienta_id>')
@login_required
@admin_required
def admin_detalle_clienta(clienta_id):
    clienta = Clienta.query.get_or_404(clienta_id)
    cursos_con_acceso_vigente = {a.curso_id for a in clienta.accesos if a.esta_vigente}

    cursos_disponibles = Curso.query.filter(
        Curso.activo.is_(True),
        ~Curso.id.in_(cursos_con_acceso_vigente) if cursos_con_acceso_vigente else True,
    ).order_by(Curso.nombre.asc()).all()

    return render_template(
        'admin/detalle_clienta.html',
        clienta=clienta,
        cursos_disponibles=cursos_disponibles,
    )


@app.route('/admin/clientas/<int:clienta_id>/agregar-curso', methods=['POST'])
@login_required
@admin_required
def admin_agregar_curso(clienta_id):
    clienta = Clienta.query.get_or_404(clienta_id)
    curso_id = limpiar_texto(request.form.get('curso_id'))
    dias = parsear_dias(request.form.get('dias_acceso'), 60)
    notas = limpiar_texto(request.form.get('notas'))

    if not curso_id:
        flash('Selecciona un curso.', 'warning')
        return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))

    curso_id_int = parsear_entero(curso_id)
    if not curso_id_int:
        flash('Curso inválido.', 'danger')
        return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))

    curso = Curso.query.get_or_404(curso_id_int)

    acceso_vigente = Acceso.query.filter(
        Acceso.clienta_id == clienta.id,
        Acceso.curso_id == curso.id,
        Acceso.activo.is_(True),
        Acceso.fecha_expiracion > datetime.utcnow(),
    ).first()

    if acceso_vigente:
        flash('La clienta ya tiene un acceso vigente a este curso.', 'warning')
        return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))

    acceso = Acceso(
        clienta_id=clienta.id,
        curso_id=curso.id,
        fecha_expiracion=datetime.utcnow() + timedelta(days=dias),
        notas=notas or None,
    )
    clienta.activa = True
    db.session.add(acceso)
    db.session.commit()

    enviar_bienvenida(app, clienta, acceso)
    registrar_evento(
        actor=current_user,
        accion='Agregó acceso',
        entidad=f'Acceso #{acceso.id}',
        detalle=f'{clienta.nombre} -> {curso.nombre}',
    )

    flash(f'Acceso a "{curso.nombre}" agregado correctamente.', 'success')
    return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))


@app.route('/admin/accesos/<int:acceso_id>/revocar', methods=['POST'])
@login_required
@admin_required
def admin_revocar_acceso(acceso_id):
    acceso = Acceso.query.get_or_404(acceso_id)
    clienta_id = acceso.clienta_id
    acceso.activo = False
    db.session.commit()

    registrar_evento(
        actor=current_user,
        accion='Revocó acceso',
        entidad=f'Acceso #{acceso.id}',
        detalle=f'{acceso.clienta.nombre} -> {acceso.curso.nombre}',
    )

    flash('Acceso revocado.', 'success')
    return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))


@app.route('/admin/accesos/<int:acceso_id>/reactivar', methods=['POST'])
@login_required
@admin_required
def admin_reactivar_acceso(acceso_id):
    acceso = Acceso.query.get_or_404(acceso_id)
    clienta_id = acceso.clienta_id
    dias = parsear_dias(request.form.get('dias'), 60)

    acceso.activo = True
    acceso.fecha_expiracion = datetime.utcnow() + timedelta(days=dias)
    acceso.recordatorio_enviado = False
    acceso.clienta.activa = True
    db.session.commit()

    registrar_evento(
        actor=current_user,
        accion='Reactivó acceso',
        entidad=f'Acceso #{acceso.id}',
        detalle=f'{acceso.clienta.nombre} -> {acceso.curso.nombre} ({dias} días)',
    )

    flash(f'Acceso reactivado por {dias} días.', 'success')
    return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))


@app.route('/admin/accesos/<int:acceso_id>/extender', methods=['POST'])
@login_required
@admin_required
def admin_extender_acceso(acceso_id):
    acceso = Acceso.query.get_or_404(acceso_id)
    clienta_id = acceso.clienta_id
    dias = parsear_dias(request.form.get('dias_extender'), 30)

    base = acceso.fecha_expiracion if acceso.fecha_expiracion > datetime.utcnow() else datetime.utcnow()
    acceso.fecha_expiracion = base + timedelta(days=dias)
    acceso.activo = True
    acceso.recordatorio_enviado = False
    acceso.clienta.activa = True
    db.session.commit()

    registrar_evento(
        actor=current_user,
        accion='Extendió acceso',
        entidad=f'Acceso #{acceso.id}',
        detalle=f'{acceso.clienta.nombre} -> {acceso.curso.nombre} (+{dias} días)',
    )

    flash(f'Se extendió el acceso por {dias} días.', 'success')
    return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))


@app.route('/admin/clientas/<int:clienta_id>/revocar-todo', methods=['POST'])
@login_required
@admin_required
def admin_revocar_todo(clienta_id):
    clienta = Clienta.query.get_or_404(clienta_id)
    for acceso in clienta.accesos:
        acceso.activo = False
    clienta.activa = False
    db.session.commit()

    registrar_evento(
        actor=current_user,
        accion='Revocó todos los accesos',
        entidad=f'Clienta #{clienta.id}',
        detalle=clienta.nombre,
    )

    flash(f'Todos los accesos de "{clienta.nombre}" han sido revocados.', 'success')
    return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))


@app.route('/admin/clientas/<int:clienta_id>/regenerar-clave', methods=['POST'])
@login_required
@admin_required
def admin_regenerar_clave(clienta_id):
    clienta = Clienta.query.get_or_404(clienta_id)
    clienta.clave_acceso = Clienta.generar_clave()
    db.session.commit()

    registrar_evento(
        actor=current_user,
        accion='Regeneró clave de clienta',
        entidad=f'Clienta #{clienta.id}',
        detalle=clienta.nombre,
    )

    flash(
        f'Nueva clave generada: {clienta.clave_acceso} - Entrégasela a la clienta.',
        'success',
    )
    return redirect(url_for('admin_detalle_clienta', clienta_id=clienta_id))


# ============================================================
# RUTAS DE CURSOS (ADMINISTRACIÓN)
# ============================================================
@app.route('/admin/cursos')
@login_required
@admin_required
def admin_cursos():
    cursos = Curso.query.order_by(Curso.created_at.desc()).all()
    return render_template('admin/cursos.html', cursos=cursos)


@app.route('/admin/cursos/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_nuevo_curso():
    if request.method == 'POST':
        nombre = limpiar_texto(request.form.get('nombre'))
        descripcion = limpiar_texto(request.form.get('descripcion'))
        tipo_video = limpiar_texto(request.form.get('tipo_video')) or 'youtube'
        video_url = limpiar_texto(request.form.get('video_url'))

        if not nombre or not video_url:
            flash('Nombre y URL del video son obligatorios.', 'danger')
            return render_template('admin/nuevo_curso.html')

        curso = Curso(
            nombre=nombre,
            descripcion=descripcion or None,
            tipo_video=tipo_video,
            video_url=video_url,
        )
        db.session.add(curso)
        db.session.commit()

        registrar_evento(
            actor=current_user,
            accion='Creó curso',
            entidad=f'Curso #{curso.id}',
            detalle=curso.nombre,
        )

        flash(f'Curso "{nombre}" creado correctamente.', 'success')
        return redirect(url_for('admin_cursos'))

    return render_template('admin/nuevo_curso.html')


@app.route('/admin/cursos/<int:curso_id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_editar_curso(curso_id):
    curso = Curso.query.get_or_404(curso_id)

    if request.method == 'POST':
        curso.nombre = limpiar_texto(request.form.get('nombre'))
        curso.descripcion = limpiar_texto(request.form.get('descripcion')) or None
        curso.tipo_video = limpiar_texto(request.form.get('tipo_video')) or 'youtube'
        curso.video_url = limpiar_texto(request.form.get('video_url'))
        db.session.commit()

        registrar_evento(
            actor=current_user,
            accion='Editó curso',
            entidad=f'Curso #{curso.id}',
            detalle=curso.nombre,
        )

        flash('Curso actualizado correctamente.', 'success')
        return redirect(url_for('admin_cursos'))

    return render_template('admin/editar_curso.html', curso=curso)


@app.route('/admin/cursos/<int:curso_id>/toggle-estado', methods=['POST'])
@login_required
@admin_required
def admin_toggle_curso_estado(curso_id):
    curso = Curso.query.get_or_404(curso_id)
    curso.activo = not curso.activo
    db.session.commit()

    registrar_evento(
        actor=current_user,
        accion='Cambió estado de curso',
        entidad=f'Curso #{curso.id}',
        detalle=f'{curso.nombre}: {"Activo" if curso.activo else "Inactivo"}',
    )

    estado = 'activado' if curso.activo else 'desactivado'
    flash(f'Curso {estado} correctamente.', 'success')
    return redirect(url_for('admin_cursos'))


@app.route('/admin/eventos')
@login_required
@admin_required
def admin_eventos():
    eventos = EventoSistema.query.order_by(EventoSistema.created_at.desc()).limit(200).all()
    return render_template('admin/eventos.html', eventos=eventos)


# ============================================================
# RUTA PARA CAMBIAR CONTRASEÑA DEL ADMIN
# ============================================================
@app.route('/admin/cambiar-contrasena', methods=['GET', 'POST'])
@login_required
@admin_required
def admin_cambiar_contrasena():
    if request.method == 'POST':
        actual = request.form.get('actual', '')
        nueva = request.form.get('nueva', '')
        confirmar = request.form.get('confirmar', '')

        if not check_password_hash(current_user.password_hash, actual):
            flash('La contraseña actual es incorrecta.', 'danger')
        elif nueva != confirmar:
            flash('Las contraseñas nuevas no coinciden.', 'danger')
        elif len(nueva) < 8:
            flash('La contraseña debe tener al menos 8 caracteres.', 'danger')
        else:
            current_user.password_hash = generate_password_hash(nueva)
            db.session.commit()

            registrar_evento(
                actor=current_user,
                accion='Cambió contraseña',
                entidad=f'Admin #{current_user.id}',
                detalle=current_user.username,
            )

            flash('Contraseña cambiada correctamente.', 'success')
            return redirect(url_for('admin_dashboard'))

    return render_template('admin/cambiar_contrasena.html')


# ============================================================
# RUTAS DE LA CLIENTA
# ============================================================
@app.route('/mis-cursos')
@login_required
def clienta_cursos():
    if isinstance(current_user, Admin):
        return redirect(url_for('admin_dashboard'))

    ahora = datetime.utcnow()
    accesos = (
        Acceso.query.join(Curso)
        .filter(
            Acceso.clienta_id == current_user.id,
            Acceso.activo.is_(True),
            Acceso.fecha_expiracion > ahora,
            Curso.activo.is_(True),
        )
        .order_by(Acceso.fecha_expiracion.asc())
        .all()
    )
    return render_template('clienta/mis_cursos.html', accesos=accesos)


@app.route('/ver-video/<int:acceso_id>')
@login_required
def ver_video(acceso_id):
    if isinstance(current_user, Admin):
        return redirect(url_for('admin_dashboard'))

    acceso = Acceso.query.get_or_404(acceso_id)

    if acceso.clienta_id != current_user.id:
        abort(403)

    if not acceso.esta_vigente:
        flash('Tu acceso a este video ha expirado.', 'warning')
        return redirect(url_for('clienta_cursos'))

    if not acceso.curso.activo:
        flash('Este curso no está disponible temporalmente.', 'warning')
        return redirect(url_for('clienta_cursos'))

    embed_url = generar_embed_url(acceso.curso.video_url, acceso.curso.tipo_video)
    return render_template('clienta/ver_video.html', acceso=acceso, embed_url=embed_url)


# ============================================================
# INICIALIZACIÓN DE LA BASE DE DATOS
# ============================================================
def crear_admin_inicial_si_falta():
    if Admin.query.first():
        return

    username = limpiar_texto(os.getenv('BOOTSTRAP_ADMIN_USERNAME', 'ADMIN')).upper()
    email = limpiar_texto(os.getenv('BOOTSTRAP_ADMIN_EMAIL')).lower()
    password = limpiar_texto(os.getenv('BOOTSTRAP_ADMIN_PASSWORD'))

    if not email or not password:
        if IS_PRODUCTION or IS_VERCEL:
            app.logger.warning(
                'No existe admin y no hay BOOTSTRAP_ADMIN_* configurado. '
                'Define BOOTSTRAP_ADMIN_EMAIL y BOOTSTRAP_ADMIN_PASSWORD.'
            )
            return

        email = 'admin@local.dev'
        password = 'admin12345'
        app.logger.warning(
            'Se creó admin temporal para entorno local. Usuario: ADMIN | Clave: admin12345 '
            '(cámbiala al iniciar sesión).'
        )

    admin = Admin(
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
    )
    db.session.add(admin)
    db.session.commit()

    registrar_evento(
        actor_tipo='sistema',
        accion='Creó admin inicial',
        entidad=f'Admin #{admin.id}',
        detalle=admin.username,
    )


def inicializar_db():
    with app.app_context():
        db.create_all()
        crear_admin_inicial_si_falta()


if env_bool('AUTO_INIT_DB', default=True):
    try:
        inicializar_db()
    except Exception:
        app.logger.exception('No se pudo inicializar la base de datos automáticamente.')


if __name__ == '__main__':
    inicializar_db()
    debug_mode = env_bool('FLASK_DEBUG', default=not IS_PRODUCTION)

    if app.config['ENABLE_SCHEDULER'] and not IS_VERCEL:
        # Evita duplicado del scheduler con reloader.
        if not debug_mode or os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
            iniciar_scheduler()

    print('Iniciando plataforma de cursos...')
    print(f"Base de datos: {app.config['SQLALCHEMY_DATABASE_URI']}")
    print(f"URL local: {app.config['PLATFORM_URL']}")

    app.run(debug=debug_mode, host='0.0.0.0', port=env_int('PORT', 5000))
