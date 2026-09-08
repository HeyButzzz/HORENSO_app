from functools import wraps

from flask import abort
from flask_login import current_user

from app.models import (
    ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR, ROLE_SENIOR, ROLE_USER,
    ROLES_ACTION_ANY_DEPARTMENT,
)


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(401)
            if current_user.role not in roles:
                abort(403)
            return f(*args, **kwargs)
        return wrapped
    return decorator


def admin_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            abort(401)
        if current_user.role != ROLE_ADMIN:
            abort(403)
        return f(*args, **kwargs)
    return wrapped


def can_view_problem(user, problem):
    """Who may open a problem card.

    Admin / Manager / Asst. Manager  every department
    Supervisor                       every department (read-only outside their own)
    Senior                           their own department only
    User                             only cards they reported or own as PIC
    """
    if user.role in (ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR):
        return True
    if user.role == ROLE_SENIOR:
        return problem.department_id == user.department_id
    return problem.reporter_id == user.id or problem.pic_id == user.id


def can_manage_problem(user, problem):
    """Who may change a card: assign, re-prioritise, resolve, act.

    Asst. Manager and Manager act anywhere. A Supervisor may read another
    department's card but only act on their own. A Senior acts within their own
    department. A reporting User acts on nothing.
    """
    if user.role in ROLES_ACTION_ANY_DEPARTMENT:
        return True
    if user.role in (ROLE_SUPERVISOR, ROLE_SENIOR):
        return (
            user.department_id is not None
            and problem.department_id == user.department_id
        )
    return False


def can_delete_problem(user, problem=None):
    """Deleting a problem card is destructive and permanent: admin only."""
    return user.is_authenticated and user.role == ROLE_ADMIN


def view_only_reason(user, problem):
    """Why a viewer cannot act, phrased for the UI. None when they can act."""
    if can_manage_problem(user, problem):
        return None
    if user.role == ROLE_SUPERVISOR:
        return (
            "Anda dapat melihat laporan departemen lain, namun tindakan hanya "
            "dapat dilakukan oleh Supervisor departemen terkait atau Asst. Manager ke atas."
        )
    if user.role == ROLE_SENIOR:
        return "Laporan ini berada di luar departemen Anda."
    if user.role == ROLE_USER:
        return "Sebagai pelapor, Anda dapat memantau dan menambahkan komentar pada laporan ini."
    return None
