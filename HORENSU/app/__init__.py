import os
from flask import Flask
from config import Config
from flask_wtf import CSRFProtect
from app.extensions import db, login_manager

csrf = CSRFProtect()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(os.path.join(app.instance_path), exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from app.auth import auth_bp
    from app.main import main_bp
    from app.problems import problems_bp
    from app.admin import admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(problems_bp, url_prefix="/problems")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    register_template_helpers(app)
    register_error_handlers(app)

    with app.app_context():
        db.create_all()
        # Migrations first: they add the columns the models expect, so any
        # query below (and every request after) sees the current schema.
        _apply_migrations(app)
        _ensure_theme_settings()

    return app


def _apply_migrations(app):
    """Bring an existing database up to the current model shape."""
    from app.migrations import apply_pending

    try:
        changes = apply_pending()
    except Exception as exc:  # pragma: no cover - surfaced, never fatal at boot
        app.logger.warning("Schema migration skipped: %s", exc)
        db.session.rollback()
        return
    for change in changes:
        app.logger.info("Migration: %s", change)


def _ensure_theme_settings():
    from app.models import ThemeSetting
    if ThemeSetting.query.first() is None:
        db.session.add(ThemeSetting())
        db.session.commit()


def register_template_helpers(app):
    from flask_login import current_user
    from app.models import ThemeSetting, Notification

    @app.context_processor
    def inject_globals():
        from app.timezone import now_wib, TZ_LABEL, TZ_NAME

        theme = ThemeSetting.query.first()
        unread_count = 0
        if current_user.is_authenticated:
            unread_count = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        from app.models import ROLE_RANK, ROLE_LABELS, ESCALATION_CHAIN

        return dict(
            theme=theme,
            unread_notif_count=unread_count,
            now_wib=now_wib(),
            tz_label=TZ_LABEL,
            tz_name=TZ_NAME,
            ROLE_RANK=ROLE_RANK,
            ROLE_LABELS=ROLE_LABELS,
            ESCALATION_CHAIN=ESCALATION_CHAIN,
        )

    @app.template_filter("dt")
    def format_dt(value, fmt="%d %b %Y, %H:%M"):
        """Render a stored UTC timestamp on the Jakarta clock (WIB, GMT+7)."""
        from app.timezone import format_wib
        return format_wib(value, fmt)

    @app.template_filter("dtz")
    def format_dt_with_zone(value, fmt="%d %b %Y, %H:%M"):
        """Same as `dt` but spells out the zone — for audit trails and receipts."""
        from app.timezone import format_wib, TZ_LABEL
        if not value:
            return "-"
        return "%s %s" % (format_wib(value, fmt), TZ_LABEL)

    @app.template_filter("dtinput")
    def format_dt_input(value, fmt="%Y-%m-%dT%H:%M"):
        """WIB value for a `datetime-local` / `date` input."""
        from app.timezone import to_input_value
        return to_input_value(value, fmt)

    @app.template_filter("timeago")
    def timeago(value):
        if not value:
            return "-"
        from app.timezone import now_utc
        delta = now_utc() - value
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "baru saja"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} menit lalu"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} jam lalu"
        days = hours // 24
        if days < 30:
            return f"{days} hari lalu"
        return value.strftime("%d %b %Y")


def register_error_handlers(app):
    from flask import render_template

    def _render(code, icon_name, heading, message):
        return render_template(
            "errors/generic.html", code=code, icon_name=icon_name, heading=heading, message=message
        ), code

    @app.errorhandler(401)
    def unauthorized(e):
        return _render(401, "lock", "Silakan masuk", "Anda perlu masuk untuk mengakses halaman ini.")

    @app.errorhandler(403)
    def forbidden(e):
        return _render(403, "shield", "Akses Ditolak", "Anda tidak memiliki izin untuk mengakses halaman ini.")

    @app.errorhandler(404)
    def not_found(e):
        return _render(404, "search", "Halaman Tidak Ditemukan", "Halaman yang Anda cari tidak ditemukan.")

    @app.errorhandler(413)
    def too_large(e):
        return _render(413, "upload", "File Terlalu Besar", "Ukuran file melebihi batas maksimum yang diizinkan.")

    @app.errorhandler(400)
    def bad_request(e):
        return _render(400, "alert", "Permintaan Tidak Valid", "Sesi Anda mungkin telah kedaluwarsa. Silakan muat ulang halaman dan coba lagi.")
