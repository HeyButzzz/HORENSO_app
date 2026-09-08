import re
from datetime import datetime, timedelta
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from app.extensions import db
from app.models import (
    User, Department, Category, Priority, Status, ThemeSetting, ActivityLog,
    ProblemCard, Action, Decision, Comment, Notification,
    ROLES, ROLE_LABELS, ROLE_ADMIN, ESCALATION_CHAIN, ROLE_RANK,
    STATUS_RESOLVED, STATUS_CLOSED,
)
from app.decorators import role_required
from app.utils import log_change, describe_changes, save_branding_image, delete_branding_image

USERNAME_RE = re.compile(r"^[a-zA-Z0-9._-]{3,64}$")

admin_bp = Blueprint("admin", __name__)


@admin_bp.before_request
@login_required
def _guard():
    if current_user.role != ROLE_ADMIN:
        abort(403)


@admin_bp.route("/")
def index():
    total_problems = ProblemCard.query.count()
    by_status = {}
    for s in Status.query.all():
        by_status[s.label] = ProblemCard.query.filter_by(status_id=s.id).count()

    overdue = sum(
        1 for p in ProblemCard.query.join(Status).filter(Status.code.notin_([STATUS_RESOLVED, STATUS_CLOSED])).all()
        if p.is_overdue
    )

    by_department = {}
    for d in Department.query.all():
        by_department[d.name] = ProblemCard.query.filter_by(department_id=d.id).count()

    by_priority = {}
    for pr in Priority.query.order_by(Priority.level).all():
        by_priority[pr.label] = ProblemCard.query.filter_by(priority_id=pr.id).count()

    # HORENSO compliance across all problems
    all_problems = ProblemCard.query.all()
    n = len(all_problems) or 1
    compliance = {
        "Report": 100,
        "Inform": round(sum(1 for p in all_problems if p.stage_inform_done) / n * 100),
        "Consult": round(sum(1 for p in all_problems if p.stage_consult_done) / n * 100),
        "Action": round(sum(1 for p in all_problems if p.stage_action_done) / n * 100),
        "Closure": round(sum(1 for p in all_problems if p.stage_closure_done) / n * 100),
    }

    return render_template(
        "admin/index.html",
        total_problems=total_problems,
        by_status=by_status,
        by_department=by_department,
        by_priority=by_priority,
        overdue=overdue,
        compliance=compliance,
        user_count=User.query.count(),
    )


# ------------------------------------------------------------------ USERS -

@admin_bp.route("/users")
def users():
    # Listed top of the ladder first, so the hierarchy reads at a glance.
    people = sorted(
        User.query.all(),
        key=lambda u: (-ROLE_RANK.get(u.role, 0), u.full_name.lower()),
    )
    return render_template(
        "admin/users.html",
        users=people,
        departments=Department.query.order_by(Department.name).all(),
        roles=ROLES,
        role_labels=ROLE_LABELS,
        escalation_chain=ESCALATION_CHAIN,
        blockers={u.id: _user_references(u) for u in people},
    )


@admin_bp.route("/users/new", methods=["POST"])
def create_user():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    full_name = request.form.get("full_name", "").strip()
    role = request.form.get("role")
    department_id = request.form.get("department_id", type=int)
    password = request.form.get("password") or "horensu123"

    if User.query.filter((User.username == username) | (User.email == email)).first():
        flash("Username atau email sudah digunakan.", "danger")
        return redirect(url_for("admin.users"))

    if not USERNAME_RE.match(username):
        flash("Username hanya boleh huruf, angka, titik, garis bawah, atau strip (3-64 karakter).", "danger")
        return redirect(url_for("admin.users"))

    user = User(username=username, email=email, full_name=full_name, role=role, department_id=department_id)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    log_change("user", user.id, user.full_name, "Membuat user",
               f"username={username}, role={role}, email={email}")
    db.session.commit()
    flash(f"User {full_name} berhasil dibuat. Password sementara: {password}", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/edit", methods=["POST"])
def edit_user(user_id):
    user = User.query.get_or_404(user_id)

    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    username = request.form.get("username", "").strip()
    role = request.form.get("role")

    if not full_name or not email:
        flash("Nama lengkap dan email wajib diisi.", "danger")
        return redirect(url_for("admin.users"))

    # Email is unique in the schema: reject a clash before SQLAlchemy raises.
    clash = User.query.filter(User.email == email, User.id != user.id).first()
    if clash:
        flash(f"Email {email} sudah dipakai oleh {clash.full_name}.", "danger")
        return redirect(url_for("admin.users"))

    # Username is the login identifier, so it is validated and de-duplicated
    # the same way. A blank field means "leave it alone".
    if username and username != user.username:
        if not USERNAME_RE.match(username):
            flash("Username hanya boleh huruf, angka, titik, garis bawah, atau strip (3-64 karakter).", "danger")
            return redirect(url_for("admin.users"))
        taken = User.query.filter(User.username == username, User.id != user.id).first()
        if taken:
            flash(f"Username {username} sudah dipakai oleh {taken.full_name}.", "danger")
            return redirect(url_for("admin.users"))

    before = {
        "username": user.username, "full_name": user.full_name, "email": user.email,
        "role": user.role_label,
        "department": user.department.name if user.department else None,
    }

    if username:
        user.username = username
    user.full_name = full_name
    user.email = email
    if role in ROLES:
        user.role = role
    # An empty option means "no department"; a missing field leaves it as-is.
    if "department_id" in request.form:
        user.department_id = request.form.get("department_id", type=int)

    new_password = request.form.get("password", "").strip()
    password_reset = bool(new_password)
    if password_reset:
        user.set_password(new_password)

    db.session.flush()
    after = {
        "username": user.username, "full_name": user.full_name, "email": user.email,
        "role": user.role_label,
        "department": user.department.name if user.department else None,
    }
    detail = describe_changes(before, after, {
        "username": "Username", "full_name": "Nama", "email": "Email",
        "role": "Role", "department": "Departemen",
    })
    if password_reset:
        detail = (detail + "; " if detail else "") + "Password direset oleh admin"
    if detail:
        log_change("user", user.id, user.full_name, "Mengubah user", detail)

    db.session.commit()
    flash(f"Data {user.full_name} berhasil diperbarui.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
def toggle_user_active(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id and user.active:
        flash("Anda tidak dapat menonaktifkan akun Anda sendiri.", "danger")
        return redirect(url_for("admin.users"))
    user.active = not user.active
    log_change("user", user.id, user.full_name,
               "Mengaktifkan user" if user.active else "Menonaktifkan user")
    db.session.commit()
    flash(f"User {'diaktifkan' if user.active else 'dinonaktifkan'}.", "info")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
def delete_user(user_id):
    """Permanently remove an account.

    Refused when the account still owns history — a reported card, an
    assignment, a decision — because deleting it would orphan that record.
    Deactivating is the right move there, and the message says so.
    """
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("Anda tidak dapat menghapus akun Anda sendiri.", "danger")
        return redirect(url_for("admin.users"))

    if user.role == ROLE_ADMIN and User.query.filter_by(role=ROLE_ADMIN, active=True).count() <= 1:
        flash("Tidak dapat menghapus admin aktif terakhir.", "danger")
        return redirect(url_for("admin.users"))

    if (request.form.get("confirm_username") or "").strip() != user.username:
        flash(f"Ketik username ({user.username}) dengan tepat untuk menghapus akun.", "danger")
        return redirect(url_for("admin.users"))

    blockers = _user_references(user)
    if blockers:
        detail = ", ".join(f"{count} {label}" for label, count in blockers)
        flash(
            f"{user.full_name} masih tercatat pada {detail}. "
            "Nonaktifkan akunnya agar riwayat laporan tetap utuh.",
            "danger",
        )
        return redirect(url_for("admin.users"))

    name = user.full_name
    log_change("user", user.id, name, "Menghapus user",
               f"username={user.username}, role={user.role_label}, email={user.email}")
    Notification.query.filter_by(user_id=user.id).delete(synchronize_session=False)
    db.session.delete(user)
    db.session.commit()
    flash(f"Akun {name} telah dihapus permanen.", "info")
    return redirect(url_for("admin.users"))


def _user_references(user):
    """History that would be orphaned by deleting this account."""
    checks = [
        ("laporan sebagai pelapor", ProblemCard.query.filter_by(reporter_id=user.id).count()),
        ("laporan sebagai PIC", ProblemCard.query.filter_by(pic_id=user.id).count()),
        ("penyelesaian laporan", ProblemCard.query.filter_by(resolved_by_id=user.id).count()),
        ("penutupan laporan", ProblemCard.query.filter_by(closed_by_id=user.id).count()),
        ("action", Action.query.filter_by(pic_id=user.id).count()),
        ("keputusan konsultasi", Decision.query.filter_by(decided_by_id=user.id).count()),
        ("komentar", Comment.query.filter_by(user_id=user.id).count()),
        ("catatan audit", ActivityLog.query.filter_by(user_id=user.id).count()),
    ]
    return [(label, count) for label, count in checks if count]


# ------------------------------------------------------------ DEPARTMENTS -

@admin_bp.route("/departments")
def departments():
    return render_template("admin/departments.html", departments=Department.query.all())


@admin_bp.route("/departments/new", methods=["POST"])
def create_department():
    name = request.form.get("name", "").strip()
    code = request.form.get("code", "").strip()
    if name:
        dep = Department(name=name, code=code)
        db.session.add(dep)
        db.session.flush()
        log_change("department", dep.id, dep.name, "Menambah departemen", f"kode={code or '-'}")
        db.session.commit()
        flash("Departemen ditambahkan.", "success")
    return redirect(url_for("admin.departments"))


@admin_bp.route("/departments/<int:dep_id>/edit", methods=["POST"])
def edit_department(dep_id):
    dep = Department.query.get_or_404(dep_id)
    before = {"name": dep.name, "code": dep.code, "aktif": dep.is_active}
    dep.name = request.form.get("name", dep.name)
    dep.code = request.form.get("code", dep.code)
    dep.is_active = bool(request.form.get("is_active"))
    detail = describe_changes(before, {"name": dep.name, "code": dep.code, "aktif": dep.is_active},
                              {"name": "Nama", "code": "Kode", "aktif": "Aktif"})
    if detail:
        log_change("department", dep.id, dep.name, "Mengubah departemen", detail)
    db.session.commit()
    flash("Departemen diperbarui.", "success")
    return redirect(url_for("admin.departments"))


# -------------------------------------------------------------- CATEGORIES

@admin_bp.route("/categories")
def categories():
    return render_template(
        "admin/categories.html",
        categories=Category.query.order_by(Category.name).all(),
    )


@admin_bp.route("/categories/new", methods=["POST"])
def create_category():
    name = request.form.get("name", "").strip()
    reference = request.form.get("reference", "").strip()
    if not name:
        flash("Nama kategori wajib diisi.", "danger")
        return redirect(url_for("admin.categories"))
    if Category.query.filter(Category.name == name).first():
        flash(f"Kategori “{name}” sudah ada.", "danger")
        return redirect(url_for("admin.categories"))
    cat = Category(name=name, reference=reference or None)
    db.session.add(cat)
    db.session.flush()
    log_change("category", cat.id, cat.name, "Menambah kategori",
               f"referensi: {reference or '-'}")
    db.session.commit()
    flash("Kategori ditambahkan.", "success")
    return redirect(url_for("admin.categories"))


@admin_bp.route("/categories/<int:cat_id>/edit", methods=["POST"])
def edit_category(cat_id):
    cat = Category.query.get_or_404(cat_id)
    name = request.form.get("name", "").strip()
    if not name:
        flash("Nama kategori wajib diisi.", "danger")
        return redirect(url_for("admin.categories"))
    clash = Category.query.filter(Category.name == name, Category.id != cat.id).first()
    if clash:
        flash(f"Kategori “{name}” sudah ada.", "danger")
        return redirect(url_for("admin.categories"))

    before = {"name": cat.name, "reference": cat.reference, "aktif": cat.is_active}
    cat.name = name
    cat.reference = request.form.get("reference", "").strip() or None
    cat.is_active = bool(request.form.get("is_active"))
    detail = describe_changes(before, {"name": cat.name, "reference": cat.reference, "aktif": cat.is_active},
                              {"name": "Nama", "reference": "Referensi", "aktif": "Aktif"})
    if detail:
        log_change("category", cat.id, cat.name, "Mengubah kategori", detail)
    db.session.commit()
    flash("Kategori diperbarui.", "success")
    return redirect(url_for("admin.categories"))


# -------------------------------------------------------------- PRIORITIES

@admin_bp.route("/priorities")
def priorities():
    return render_template("admin/priorities.html", priorities=Priority.query.order_by(Priority.level).all())


@admin_bp.route("/priorities/<int:pr_id>/edit", methods=["POST"])
def edit_priority(pr_id):
    pr = Priority.query.get_or_404(pr_id)
    before = {"label": pr.label, "color": pr.color, "sla": pr.sla_hours}
    pr.label = request.form.get("label", pr.label)
    pr.color = request.form.get("color", pr.color)
    pr.sla_hours = request.form.get("sla_hours", type=int) or pr.sla_hours
    detail = describe_changes(before, {"label": pr.label, "color": pr.color, "sla": pr.sla_hours},
                              {"label": "Label", "color": "Warna", "sla": "SLA (jam)"})
    if detail:
        log_change("priority", pr.id, pr.code, "Mengubah prioritas", detail)
    db.session.commit()
    flash("Prioritas & SLA diperbarui.", "success")
    return redirect(url_for("admin.priorities"))


# ----------------------------------------------------------------- STATUS -

@admin_bp.route("/statuses")
def statuses():
    return render_template("admin/statuses.html", statuses=Status.query.order_by(Status.order).all())


@admin_bp.route("/statuses/<int:st_id>/edit", methods=["POST"])
def edit_status(st_id):
    st = Status.query.get_or_404(st_id)
    before = {"label": st.label, "color": st.color}
    st.label = request.form.get("label", st.label)
    st.color = request.form.get("color", st.color)
    detail = describe_changes(before, {"label": st.label, "color": st.color},
                              {"label": "Label", "color": "Warna"})
    if detail:
        log_change("status", st.id, st.code, "Mengubah status", detail)
    db.session.commit()
    flash("Status diperbarui.", "success")
    return redirect(url_for("admin.statuses"))


# ------------------------------------------------------------------ THEME -

TEXT_FIELD_LABELS = {
    "app_name": "Nama aplikasi", "company_name": "Nama perusahaan",
    "primary_color": "Warna primary", "secondary_color": "Warna secondary",
    "accent_color": "Warna accent", "background_color": "Warna background",
    "font_family": "Font", "sidebar_style": "Gaya sidebar",
    "welcome_message": "Pesan sambutan", "login_tagline": "Tagline login",
    "footer_text": "Teks footer",
}


@admin_bp.route("/theme", methods=["GET", "POST"])
def theme():
    theme = ThemeSetting.query.first()
    if request.method == "POST":
        before = {f: getattr(theme, f) for f in TEXT_FIELD_LABELS}
        for field in TEXT_FIELD_LABELS:
            value = request.form.get(field)
            if value is not None:
                setattr(theme, field, value)

        notes = []

        # Logo and favicon arrive as uploads; each replaces the previous file.
        for kind, name_field, remove_field in [
            ("logo", "logo_filename", "remove_logo"),
            ("favicon", "favicon_filename", "remove_favicon"),
        ]:
            if request.form.get(remove_field):
                old = getattr(theme, name_field)
                if old:
                    delete_branding_image(old)
                    setattr(theme, name_field, None)
                    notes.append(f"{kind} dihapus")
                setattr(theme, f"{kind}_url", None)
                continue

            stored, error = save_branding_image(request.files.get(f"{kind}_file"), kind)
            if error:
                flash(f"{kind.title()}: {error}", "danger")
                db.session.rollback()
                return redirect(url_for("admin.theme"))
            if stored:
                delete_branding_image(getattr(theme, name_field))
                setattr(theme, name_field, stored)
                setattr(theme, f"{kind}_url", None)
                notes.append(f"{kind} diunggah ({stored})")

        after = {f: getattr(theme, f) for f in TEXT_FIELD_LABELS}
        detail = describe_changes(before, after, TEXT_FIELD_LABELS)
        if notes:
            detail = (detail + "; " if detail else "") + ", ".join(notes)
        if detail:
            log_change("theme", theme.id, theme.app_name, "Mengubah tampilan & branding", detail)

        db.session.commit()
        flash("Tampilan aplikasi berhasil diperbarui.", "success")
        return redirect(url_for("admin.theme"))
    return render_template("admin/theme.html", theme=theme)


# -------------------------------------------------------------- AUDIT LOG -

@admin_bp.route("/audit-log")
def audit_log():
    """Every recorded change, newest first, filterable by area and by person."""
    query = ActivityLog.query

    entity_type = request.args.get("entity_type")
    user_id = request.args.get("user", type=int)
    search = (request.args.get("q") or "").strip()

    if entity_type:
        query = query.filter(ActivityLog.entity_type == entity_type)
    if user_id:
        query = query.filter(ActivityLog.user_id == user_id)
    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(ActivityLog.action.ilike(like),
                   ActivityLog.detail.ilike(like),
                   ActivityLog.entity_label.ilike(like))
        )

    page = max(request.args.get("page", type=int) or 1, 1)
    per_page = 100
    total = query.count()
    logs = (query.order_by(ActivityLog.created_at.desc())
            .offset((page - 1) * per_page).limit(per_page).all())

    present = [row[0] for row in db.session.query(ActivityLog.entity_type)
               .distinct().order_by(ActivityLog.entity_type).all() if row[0]]

    return render_template(
        "admin/audit_log.html",
        logs=logs,
        total=total,
        page=page,
        pages=max((total + per_page - 1) // per_page, 1),
        entity_types=present,
        entity_labels=ActivityLog.ENTITY_LABELS,
        actors=User.query.order_by(User.full_name).all(),
        filters=request.args,
    )
