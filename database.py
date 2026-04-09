import random
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin

db = SQLAlchemy()


# ============================================================
# MODELOS DE LA BASE DE DATOS
# ============================================================

class Admin(UserMixin, db.Model):
    """Administrador del sistema (tu mamá)"""
    __tablename__ = 'admins'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_admins_username', 'username'),
        db.Index('ix_admins_email', 'email'),
    )

    def get_id(self):
        return f'admin_{self.id}'


class Clienta(UserMixin, db.Model):
    """Clienta del sistema"""
    __tablename__ = 'clientas'

    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(10), unique=True, nullable=False)       # Ej: CLI-0001
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    telefono = db.Column(db.String(20), nullable=True)
    clave_acceso = db.Column(db.String(20), unique=True, nullable=False)  # Clave para login
    activa = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_clientas_email', 'email'),
        db.Index('ix_clientas_clave_acceso', 'clave_acceso'),
        db.Index('ix_clientas_activa', 'activa'),
    )

    # Relación con accesos
    accesos = db.relationship('Acceso', backref='clienta', lazy=True)

    def get_id(self):
        return f'clienta_{self.id}'

    @staticmethod
    def generar_codigo():
        """Genera un código único tipo CLI-0001"""
        ultimo = Clienta.query.order_by(Clienta.id.desc()).first()
        numero = (ultimo.id + 1) if ultimo else 1
        return f'CLI-{numero:04d}'

    @staticmethod
    def generar_clave():
        """Genera una clave aleatoria fácil de leer (sin caracteres confusos)"""
        # Sin 0, O, I, l para evitar confusiones
        caracteres = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
        clave = ''.join(random.choices(caracteres, k=8))
        # Verificar que no exista ya
        while Clienta.query.filter_by(clave_acceso=clave).first():
            clave = ''.join(random.choices(caracteres, k=8))
        return clave


class Curso(db.Model):
    """Curso / video disponible en la plataforma"""
    __tablename__ = 'cursos'

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text, nullable=True)
    video_url = db.Column(db.String(500), nullable=False)
    tipo_video = db.Column(db.String(20), default='youtube')  # youtube, vimeo, drive
    activo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_cursos_activo', 'activo'),
    )

    # Relación con accesos
    accesos = db.relationship('Acceso', backref='curso', lazy=True)

    @property
    def total_clientas(self):
        return len([a for a in self.accesos if a.activo])


class Acceso(db.Model):
    """Relación entre clienta y curso, con fecha de expiración"""
    __tablename__ = 'accesos'

    id = db.Column(db.Integer, primary_key=True)
    clienta_id = db.Column(db.Integer, db.ForeignKey('clientas.id'), nullable=False)
    curso_id = db.Column(db.Integer, db.ForeignKey('cursos.id'), nullable=False)
    fecha_inicio = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_expiracion = db.Column(db.DateTime, nullable=False)
    activo = db.Column(db.Boolean, default=True)
    recordatorio_enviado = db.Column(db.Boolean, default=False)
    notas = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.Index('ix_accesos_activo_expiracion', 'activo', 'fecha_expiracion'),
        db.Index('ix_accesos_clienta_activo_expiracion', 'clienta_id', 'activo', 'fecha_expiracion'),
        db.Index('ix_accesos_curso_activo', 'curso_id', 'activo'),
    )

    @property
    def esta_vigente(self):
        """Retorna True si el acceso está activo y no ha expirado"""
        return self.activo and self.fecha_expiracion > datetime.utcnow()

    @property
    def dias_restantes(self):
        """Días que faltan para que expire"""
        if not self.esta_vigente:
            return 0
        delta = self.fecha_expiracion - datetime.utcnow()
        return delta.days


class EventoSistema(db.Model):
    """Bitácora simple de acciones administrativas"""
    __tablename__ = 'eventos_sistema'

    id = db.Column(db.Integer, primary_key=True)
    actor_tipo = db.Column(db.String(20), nullable=False)      # admin, sistema
    actor_id = db.Column(db.Integer, nullable=True)
    actor_nombre = db.Column(db.String(120), nullable=False)
    accion = db.Column(db.String(120), nullable=False)
    entidad = db.Column(db.String(120), nullable=True)
    detalle = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.Index('ix_eventos_created_at', 'created_at'),
        db.Index('ix_eventos_actor_tipo', 'actor_tipo'),
    )
