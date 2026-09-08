import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "horensu-dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "instance", "horensu.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 15 * 1024 * 1024  # 15 MB per request
    ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "pdf", "doc", "docx", "xls", "xlsx", "csv", "txt"}

    # ---- Branding uploads (logo & favicon) ----
    # Kept apart from problem attachments: these are served publicly, since the
    # login page has to render them before anyone has signed in.
    BRANDING_FOLDER = os.path.join(BASE_DIR, "uploads", "branding")
    LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "svg", "webp"}
    FAVICON_EXTENSIONS = {"png", "ico", "svg"}
    MAX_LOGO_BYTES = 512 * 1024          # 512 KB
    MAX_FAVICON_BYTES = 100 * 1024       # 100 KB
    LOGO_RECOMMENDED = "PNG/SVG persegi, 256×256 px, maksimal 512 KB"
    FAVICON_RECOMMENDED = "PNG/ICO/SVG persegi, 64×64 px, maksimal 100 KB"

    # ---- Locale ----
    TIMEZONE_NAME = "Asia/Jakarta"
    TIMEZONE_LABEL = "WIB"
    PERMANENT_SESSION_LIFETIME = timedelta(hours=8)
    REMEMBER_COOKIE_DURATION = timedelta(days=14)
