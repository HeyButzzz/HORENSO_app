import os
import uuid
from datetime import datetime
from flask import current_app
from werkzeug.utils import secure_filename
from app.extensions import db
from app.timezone import now_utc
from app.models import (
    ProblemCard, Notification, ActivityLog, Attachment, User,
    ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR, ROLE_SENIOR,
    ESCALATION_CHAIN, CROSS_DEPARTMENT_ROLES, ROLE_RANK,
)


def generate_problem_code():
    from app.timezone import now_wib
    year = now_wib().year
    prefix = f"PRB-{year}-"
    existing = ProblemCard.query.filter(ProblemCard.code.like(f"{prefix}%")).all()
    max_seq = 0
    for p in existing:
        try:
            seq = int(p.code.split("-")[-1])
            max_seq = max(max_seq, seq)
        except ValueError:
            continue
    return f"{prefix}{max_seq + 1:05d}"


def _request_ip():
    try:
        from flask import request, has_request_context
        if not has_request_context():
            return None
        forwarded = request.headers.get("X-Forwarded-For", "")
        return (forwarded.split(",")[0].strip() or request.remote_addr) if forwarded else request.remote_addr
    except Exception:
        return None


def log_activity(problem, user, action, detail=None):
    """Record a change to a problem card."""
    entry = ActivityLog(
        problem_id=problem.id,
        entity_type="problem",
        entity_id=problem.id,
        entity_label=problem.code,
        user_id=user.id if user else None,
        action=action,
        detail=detail,
        ip_address=_request_ip(),
    )
    db.session.add(entry)
    return entry


def log_change(entity_type, entity_id, entity_label, action, detail=None, user=None):
    """Record a change anywhere else in the app — users, master data, branding.

    Everything that alters stored state should call this so the audit log is a
    complete record rather than only a problem-card history.
    """
    from flask_login import current_user

    if user is None:
        try:
            user = current_user if getattr(current_user, "is_authenticated", False) else None
        except Exception:
            user = None
    entry = ActivityLog(
        problem_id=None,
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=(entity_label or "")[:160] or None,
        user_id=user.id if user else None,
        action=action,
        detail=detail,
        ip_address=_request_ip(),
    )
    db.session.add(entry)
    return entry


def describe_changes(before, after, labels=None):
    """"field: old -> new" for every value that actually moved.

    Keeps the audit detail readable and skips fields nobody touched.
    """
    labels = labels or {}
    parts = []
    for key, old in before.items():
        new = after.get(key)
        if old == new:
            continue
        name = labels.get(key, key)
        parts.append("%s: %s → %s" % (name, old if old not in (None, "") else "-",
                                      new if new not in (None, "") else "-"))
    return "; ".join(parts)


def notify(user_id, message, problem=None, ntype="general"):
    if user_id is None:
        return None
    note = Notification(
        user_id=user_id,
        problem_id=problem.id if problem else None,
        type=ntype,
        message=message,
    )
    db.session.add(note)
    return note


def notify_many(user_ids, message, problem=None, ntype="general"):
    seen = set()
    for uid in user_ids:
        if uid and uid not in seen:
            seen.add(uid)
            notify(uid, message, problem=problem, ntype=ntype)


def _active(role):
    return User.query.filter(User.role == role, User.active == True)  # noqa: E712


def _tier_members(role, department_id, exclude_user_id=None):
    """Active holders of one tier who cover a department.

    Asst. Manager and Manager cover every department, so they are returned
    regardless of where the report came from.
    """
    q = _active(role)
    if role not in CROSS_DEPARTMENT_ROLES and department_id:
        q = q.filter(User.department_id == department_id)
    elif role not in CROSS_DEPARTMENT_ROLES:
        return []
    rows = q.order_by(User.full_name).all()
    return [u for u in rows if u.id != exclude_user_id]


# Public name for the tier lookup, used by the escalation endpoints.
def tier_members(role, department_id, exclude_user_id=None):
    """Active holders of one tier who cover a department."""
    return _tier_members(role, department_id, exclude_user_id=exclude_user_id)


def escalation_ladder(department_id, exclude_user_id=None):
    """The full ladder for a department, lowest tier first.

    Returns a list of {role, label, members} — Senior, Supervisor,
    Asst. Manager, Manager — with empty tiers left in place so the UI can show
    where the line is broken.
    """
    from app.models import ROLE_LABELS

    return [
        {
            "role": role,
            "label": ROLE_LABELS[role],
            "members": _tier_members(role, department_id, exclude_user_id=exclude_user_id),
        }
        for role in ESCALATION_CHAIN
    ]


def first_responders(department_id, exclude_user_id=None):
    """Who a fresh report goes to first.

    A report from a user lands on the Senior of that department. If the
    department has no Senior it climbs the ladder — Supervisor, then
    Asst. Manager, then Manager — and finally falls back to Admin, so a report
    is never left without a recipient.
    """
    for role in ESCALATION_CHAIN:
        members = _tier_members(role, department_id, exclude_user_id=exclude_user_id)
        if members:
            return members, role
    fallback = [u for u in _active(ROLE_ADMIN).order_by(User.full_name).all()
                if u.id != exclude_user_id]
    return fallback, ROLE_ADMIN


def recommended_recipients(department_id, exclude_user_id=None):
    """Renraku recipients for a new report: the first tier that can act."""
    members, _role = first_responders(department_id, exclude_user_id=exclude_user_id)
    return members


def recommended_seniors(department_id, exclude_user_id=None):
    """Seniors of a department — the natural PIC for the Action stage."""
    return _tier_members(ROLE_SENIOR, department_id, exclude_user_id=exclude_user_id)


def acknowledgers_above(role, department_id):
    """Tiers that only have to tick "mengetahui" once `role` has resolved it."""
    resolver_rank = ROLE_RANK.get(role, 0)
    out = []
    for tier in ESCALATION_CHAIN:
        if ROLE_RANK[tier] <= resolver_rank:
            continue
        out.extend(_tier_members(tier, department_id))
    return out


def assignment_recommendations(problem, exclude_user_id=None):
    """Everything the UI needs to route and staff a problem card."""
    department_id = problem.department_id
    responders, responder_role = first_responders(department_id, exclude_user_id=exclude_user_id)
    ladder = escalation_ladder(department_id, exclude_user_id=exclude_user_id)
    already_informed = {c.recipient_user_id for c in problem.communications if c.recipient_user_id}

    return {
        # The tier a fresh report should reach first.
        "responders": responders,
        "responder_role": responder_role,
        "responder_label": {
            ROLE_SENIOR: "Senior",
            ROLE_SUPERVISOR: "Supervisor",
            ROLE_ASST_MANAGER: "Asst. Manager",
            ROLE_MANAGER: "Manager",
            ROLE_ADMIN: "Admin",
        }.get(responder_role, responder_role),
        # True when the department has no Senior and the report had to climb.
        "is_escalated": responder_role != ROLE_SENIOR,
        "ladder": ladder,
        "seniors": recommended_seniors(department_id, exclude_user_id=exclude_user_id),
        "informed_ids": already_informed,
    }


def allowed_file(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in current_app.config["ALLOWED_EXTENSIONS"]


def _file_size(file_storage):
    """Byte length of an upload without reading it into memory."""
    file_storage.stream.seek(0, os.SEEK_END)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    return size


def save_branding_image(file_storage, kind):
    """Store an uploaded logo or favicon. Returns (filename, error_message).

    `kind` is "logo" or "favicon"; each has its own extension whitelist and
    size ceiling so a huge image can never end up on the login screen.
    """
    if not file_storage or not file_storage.filename:
        return None, None

    cfg = current_app.config
    if kind == "favicon":
        allowed, max_bytes, hint = cfg["FAVICON_EXTENSIONS"], cfg["MAX_FAVICON_BYTES"], cfg["FAVICON_RECOMMENDED"]
    else:
        allowed, max_bytes, hint = cfg["LOGO_EXTENSIONS"], cfg["MAX_LOGO_BYTES"], cfg["LOGO_RECOMMENDED"]

    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in allowed:
        return None, "Format %s tidak didukung. Gunakan %s." % (
            ext.upper() or "file", ", ".join(sorted(e.upper() for e in allowed)))

    size = _file_size(file_storage)
    if size == 0:
        return None, "File kosong."
    if size > max_bytes:
        return None, "Ukuran file %s KB melebihi batas %s KB. Disarankan: %s." % (
            size // 1024, max_bytes // 1024, hint)

    folder = cfg["BRANDING_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    stored = "%s-%s.%s" % (kind, uuid.uuid4().hex[:12], ext)
    file_storage.save(os.path.join(folder, stored))
    return stored, None


def delete_branding_image(filename):
    """Remove a previously uploaded branding file, ignoring anything missing."""
    if not filename:
        return
    path = os.path.join(current_app.config["BRANDING_FOLDER"], os.path.basename(filename))
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        current_app.logger.warning("Could not remove branding file %s", path)


def save_attachment(file_storage, entity_type, entity_id, user_id):
    if not file_storage or file_storage.filename == "":
        return None
    if not allowed_file(file_storage.filename):
        return None
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    stored = f"{uuid.uuid4().hex}.{ext}" if ext else uuid.uuid4().hex
    folder = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, stored)
    file_storage.save(path)
    size = os.path.getsize(path)
    att = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        original_filename=original,
        stored_filename=stored,
        file_size=size,
        uploaded_by_id=user_id,
    )
    db.session.add(att)
    return att


def find_similar_problems(problem, days=30, limit=5):
    from datetime import timedelta
    cutoff = now_utc() - timedelta(days=days)
    q = ProblemCard.query.filter(
        ProblemCard.id != problem.id,
        ProblemCard.category_id == problem.category_id,
        ProblemCard.department_id == problem.department_id,
        ProblemCard.created_at >= cutoff,
    ).order_by(ProblemCard.created_at.desc())
    return q.limit(limit).all()
