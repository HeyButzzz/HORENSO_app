import secrets
from datetime import timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db
from app.models import User
from app.timezone import now_utc
from app.utils import log_change

auth_bp = Blueprint("auth", __name__)

PASSWORD_MIN_LENGTH = 6


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        password = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        user = User.query.filter(
            (User.username == identifier) | (User.email == identifier)
        ).first()

        if user and user.active and user.check_password(password):
            login_user(user, remember=remember)
            user.last_login_at = now_utc()
            log_change("session", user.id, user.full_name, "Masuk ke aplikasi", user=user)
            db.session.commit()
            next_url = request.args.get("next")
            return redirect(next_url or url_for("main.dashboard"))

        if user and not user.active:
            log_change("session", user.id, user.username, "Percobaan masuk ditolak",
                       "Akun nonaktif", user=None)
        else:
            log_change("session", None, identifier or "-", "Percobaan masuk gagal",
                       "Username/email atau password salah", user=None)
        db.session.commit()
        flash("Username/email atau password salah. Silakan coba lagi.", "danger")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    log_change("session", current_user.id, current_user.full_name, "Keluar dari aplikasi")
    db.session.commit()
    logout_user()
    flash("Anda telah keluar. Sampai jumpa lagi!", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/akun/password", methods=["GET", "POST"])
@login_required
def change_password():
    """Any signed-in account changes its own password.

    The current password is asked for as well as the two new entries: without
    it, anyone who reaches an unattended session could lock the owner out.
    """
    if request.method == "POST":
        current = request.form.get("current_password", "")
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not current_user.check_password(current):
            flash("Password saat ini salah.", "danger")
        elif len(password) < PASSWORD_MIN_LENGTH:
            flash("Password baru minimal %d karakter." % PASSWORD_MIN_LENGTH, "danger")
        elif password != confirm:
            flash("Konfirmasi password tidak cocok. Masukkan password baru dua kali dengan sama persis.", "danger")
        elif password == current:
            flash("Password baru harus berbeda dari password saat ini.", "danger")
        else:
            current_user.set_password(password)
            log_change("account", current_user.id, current_user.full_name,
                       "Mengubah password sendiri")
            db.session.commit()
            flash("Password berhasil diubah.", "success")
            return redirect(url_for("auth.change_password"))

    return render_template("auth/change_password.html", min_length=PASSWORD_MIN_LENGTH)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    reset_link = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        user = User.query.filter_by(email=email).first()
        if user:
            token = secrets.token_urlsafe(24)
            user.reset_token = token
            user.reset_token_expires = now_utc() + timedelta(hours=1)
            db.session.commit()
            reset_link = url_for("auth.reset_password", token=token, _external=False)
        flash(
            "Jika email terdaftar, tautan reset password telah dibuat. "
            "(Demo: belum terhubung ke server email — tautan ditampilkan di bawah)",
            "info",
        )
    return render_template("auth/forgot_password.html", reset_link=reset_link)


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user or not user.reset_token_expires or user.reset_token_expires < now_utc():
        flash("Tautan reset password tidak valid atau sudah kedaluwarsa.", "danger")
        return redirect(url_for("auth.forgot_password"))

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        if len(password) < PASSWORD_MIN_LENGTH:
            flash("Password minimal %d karakter." % PASSWORD_MIN_LENGTH, "danger")
        elif password != confirm:
            flash("Konfirmasi password tidak cocok.", "danger")
        else:
            user.set_password(password)
            user.reset_token = None
            user.reset_token_expires = None
            log_change("account", user.id, user.full_name,
                       "Mengatur ulang password via tautan reset", user=user)
            db.session.commit()
            flash("Password berhasil diubah. Silakan masuk.", "success")
            return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token)
