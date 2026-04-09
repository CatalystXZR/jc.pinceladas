from flask_mail import Mail, Message

mail = Mail()


def _enviar_correo(app, subject, recipients, html):
    try:
        with app.app_context():
            if app.config.get('MAIL_SUPPRESS_SEND'):
                app.logger.info('MAIL_SUPPRESS_SEND activo. Correo omitido: %s', subject)
                return True

            if not app.config.get('MAIL_USERNAME') or not app.config.get('MAIL_PASSWORD'):
                app.logger.warning('Correo no configurado. Omite envío de: %s', subject)
                return False

            msg = Message(subject=subject, recipients=recipients)
            msg.html = html
            mail.send(msg)
            return True
    except Exception:
        app.logger.exception('Error enviando correo: %s', subject)
        return False


def enviar_recordatorio(app, acceso):
    """Envía recordatorio previo al vencimiento del acceso."""
    brand = app.config.get('BRAND_NAME', 'jc.pinceladas')
    support_whatsapp = app.config.get('SUPPORT_WHATSAPP', '+56 9 XXXX XXXX')
    support_instagram = app.config.get('SUPPORT_INSTAGRAM', '@jc.pinceladas_')
    platform_url = app.config.get('PLATFORM_URL', 'http://localhost:5000')

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, sans-serif; max-width: 620px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #8c715f, #b89a7a); padding: 24px 20px; border-radius: 16px 16px 0 0; text-align: center;">
            <h1 style="margin: 0; color: #fff; font-size: 26px;">{brand}</h1>
            <p style="margin: 8px 0 0; color: #f6efe8; font-size: 14px;">Tu espacio para aprender y crear</p>
        </div>

        <div style="background-color: #fcf8f3; padding: 26px; border: 1px solid #eadfcf; border-top: none; border-radius: 0 0 16px 16px; color: #4d3f33;">
            <p style="font-size: 17px; margin-top: 0;">Hola <strong>{acceso.clienta.nombre}</strong>,</p>

            <p>
                Tu acceso al curso <strong>\"{acceso.curso.nombre}\"</strong> vence en
                <strong>{acceso.dias_restantes} día(s)</strong>.
            </p>

            <div style="background: #fff7da; border-left: 4px solid #caa867; padding: 14px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0;">Fecha de vencimiento: <strong>{acceso.fecha_expiracion.strftime('%d/%m/%Y')}</strong></p>
            </div>

            <p style="margin-bottom: 8px;">Tu clave de acceso es: <strong>{acceso.clienta.clave_acceso}</strong></p>
            <p style="margin-top: 0;">Ingresa desde: <a href=\"{platform_url}\" style=\"color: #8c715f;\">{platform_url}</a></p>

            <p style="margin-top: 22px; margin-bottom: 0;">
                Para renovar tu acceso, escríbenos por WhatsApp {support_whatsapp} o Instagram {support_instagram}.
            </p>

            <hr style="margin: 24px 0; border: none; border-top: 1px solid #eadfcf;">
            <p style="margin: 0; color: #8f7b69; font-size: 12px;">Este es un correo automático, no es necesario responder.</p>
        </div>
    </div>
    """

    return _enviar_correo(
        app,
        subject='Tu acceso al curso está por vencer',
        recipients=[acceso.clienta.email],
        html=html,
    )


def enviar_bienvenida(app, clienta, acceso):
    """Envía correo de bienvenida con los datos de acceso al curso."""
    brand = app.config.get('BRAND_NAME', 'jc.pinceladas')
    support_whatsapp = app.config.get('SUPPORT_WHATSAPP', '+56 9 XXXX XXXX')
    support_instagram = app.config.get('SUPPORT_INSTAGRAM', '@jc.pinceladas_')
    platform_url = app.config.get('PLATFORM_URL', 'http://localhost:5000')

    html = f"""
    <div style="font-family: 'Segoe UI', Tahoma, sans-serif; max-width: 620px; margin: 0 auto;">
        <div style="background: linear-gradient(135deg, #8c715f, #b89a7a); padding: 24px 20px; border-radius: 16px 16px 0 0; text-align: center;">
            <h1 style="margin: 0; color: #fff; font-size: 26px;">{brand}</h1>
            <p style="margin: 8px 0 0; color: #f6efe8; font-size: 14px;">Gracias por confiar en nosotros</p>
        </div>

        <div style="background-color: #fcf8f3; padding: 26px; border: 1px solid #eadfcf; border-top: none; border-radius: 0 0 16px 16px; color: #4d3f33;">
            <p style="font-size: 17px; margin-top: 0;">Hola <strong>{clienta.nombre}</strong>,</p>

            <p>Te damos la bienvenida. Ya tienes acceso al curso <strong>\"{acceso.curso.nombre}\"</strong>.</p>

            <div style="background: #eef8f0; border-left: 4px solid #4f9d5d; padding: 14px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0 0 8px;"><strong>Datos de acceso:</strong></p>
                <p style="margin: 0;">Codigo: <strong>{clienta.codigo}</strong></p>
                <p style="margin: 8px 0 0;">Clave: <strong>{clienta.clave_acceso}</strong></p>
            </div>

            <div style="background: #fff7da; border-left: 4px solid #caa867; padding: 14px; border-radius: 8px; margin: 20px 0;">
                <p style="margin: 0;">Tu acceso vence el: <strong>{acceso.fecha_expiracion.strftime('%d/%m/%Y')}</strong></p>
            </div>

            <p>Ingresa aquí: <a href=\"{platform_url}\" style=\"color: #8c715f;\">{platform_url}</a></p>

            <p style="margin-top: 18px; margin-bottom: 0;">
                Si necesitas ayuda, contáctanos por WhatsApp {support_whatsapp} o Instagram {support_instagram}.
            </p>

            <hr style="margin: 24px 0; border: none; border-top: 1px solid #eadfcf;">
            <p style="margin: 0; color: #8f7b69; font-size: 12px;">Este es un correo automático.</p>
        </div>
    </div>
    """

    return _enviar_correo(
        app,
        subject='Bienvenida: tu acceso al curso ya está activo',
        recipients=[clienta.email],
        html=html,
    )
