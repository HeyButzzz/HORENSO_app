from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, request, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_
from app.extensions import db
from app.models import (
    ProblemCard, Status, Action, Consultation, Notification,
    Department, Category, Priority, User, STATUS_RESOLVED, STATUS_CLOSED,
    ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR, ROLE_SENIOR, ROLE_USER,
)
from app.problems import _visible_problems

main_bp = Blueprint("main", __name__)


def _scope_to_visible(query, user):
    """Narrow a query already joined to ProblemCard to what `user` may see."""
    if user.role in (ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR):
        return query
    if user.role == ROLE_SENIOR:
        return query.filter(ProblemCard.department_id == user.department_id)
    return query.filter(
        or_(ProblemCard.reporter_id == user.id, ProblemCard.pic_id == user.id)
    )


@main_bp.route("/branding/<path:filename>")
def branding_file(filename):
    """Serve an uploaded logo/favicon.

    Deliberately not login-protected: the login screen has to show the logo
    and favicon before anyone has signed in. Only the branding folder is
    exposed, and `send_from_directory` refuses paths that escape it.
    """
    from flask import send_from_directory, current_app
    return send_from_directory(
        current_app.config["BRANDING_FOLDER"], filename, max_age=3600
    )


def _greeting():
    from app.timezone import now_wib

    hour = now_wib().hour  # greet on the Jakarta clock, not the server's
    if hour < 11:
        return "Selamat pagi"
    if hour < 15:
        return "Selamat siang"
    if hour < 18:
        return "Selamat sore"
    return "Selamat malam"


@main_bp.route("/")
@login_required
def dashboard():
    user = current_user

    my_problems = ProblemCard.query.filter(
        or_(ProblemCard.reporter_id == user.id, ProblemCard.pic_id == user.id)
    )
    status_counts = {}
    for s in Status.query.order_by(Status.order).all():
        status_counts[s.code] = my_problems.filter(ProblemCard.status_id == s.id).count()

    # Problems requiring my action
    action_problems = []
    if user.role != ROLE_USER:
        pending_actions = (
            Action.query.filter(Action.pic_id == user.id, Action.status != "COMPLETED")
            .join(ProblemCard)
            .filter(ProblemCard.status_id.isnot(None))
            .all()
        )
        seen = set()
        for a in pending_actions:
            if a.problem_id not in seen:
                seen.add(a.problem_id)
                action_problems.append(a.problem)
    my_pic_open = ProblemCard.query.join(Status).filter(
        ProblemCard.pic_id == user.id, Status.code.notin_([STATUS_RESOLVED, STATUS_CLOSED])
    ).all()
    for p in my_pic_open:
        if p not in action_problems:
            action_problems.append(p)

    # Problems waiting for decision (scoped by role)
    waiting_q = Consultation.query.filter(Consultation.status == "OPEN").join(ProblemCard)
    waiting_q = _scope_to_visible(waiting_q, user)
    waiting_decision = [c.problem for c in waiting_q.order_by(Consultation.requested_at.desc()).limit(8).all()]

    visible = _visible_problems(user)
    total_open = visible.join(Status).filter(Status.code.notin_([STATUS_CLOSED])).count()
    overdue_count = sum(
        1 for p in _visible_problems(user).join(Status)
        .filter(Status.code.notin_([STATUS_RESOLVED, STATUS_CLOSED])).all()
        if p.is_overdue
    )
    pending_ack = [
        p for p in _visible_problems(user).filter(ProblemCard.resolved_at.isnot(None)).all()
        if p.needs_acknowledgement_from(user)
    ]

    return render_template(
        "dashboard.html",
        greeting=_greeting(),
        status_counts=status_counts,
        action_problems=action_problems[:8],
        waiting_decision=waiting_decision,
        total_open=total_open,
        overdue_count=overdue_count,
        pending_ack=pending_ack[:8],
    )


@main_bp.route("/notifications")
@login_required
def notifications():
    notes = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).limit(50).all()
    return render_template("notifications.html", notifications=notes)


@main_bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_notification_read(notif_id):
    note = Notification.query.get_or_404(notif_id)
    if note.user_id == current_user.id:
        note.is_read = True
        db.session.commit()
    if note.problem_id:
        return redirect(url_for("problems.detail", problem_id=note.problem_id))
    return redirect(url_for("main.notifications"))


@main_bp.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return redirect(url_for("main.notifications"))


@main_bp.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        like = f"%{q}%"
        query = _visible_problems(current_user).outerjoin(User, ProblemCard.reporter_id == User.id).filter(
            or_(
                ProblemCard.code.ilike(like),
                ProblemCard.title.ilike(like),
                ProblemCard.description.ilike(like),
                User.full_name.ilike(like),
            )
        )
        results = query.order_by(ProblemCard.created_at.desc()).limit(30).all()
    return render_template("search_results.html", q=q, results=results)
