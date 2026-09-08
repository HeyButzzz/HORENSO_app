import os
import uuid
from datetime import datetime
from flask import (
    Blueprint, render_template, redirect, url_for, request, flash, session, abort, current_app, send_from_directory
)
from flask_login import login_required, current_user
from sqlalchemy import or_
from app.extensions import db
from app.models import (
    ProblemCard, Department, Category, Priority, Status, User, Communication,
    Consultation, Decision, Action, Comment, RootCauseAnalysis, Attachment,
    Acknowledgement, EscalationRequest, Notification, ActivityLog,
    ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR, ROLE_SENIOR, ROLE_USER,
    ROLES_ACTION_ANY_DEPARTMENT, ROLE_LABELS, ROLE_RANK, ESCALATION_CHAIN,
    STATUS_NEW, STATUS_IN_PROGRESS, STATUS_WAITING_DECISION, STATUS_RESOLVED, STATUS_CLOSED,
)
from app.decorators import (
    can_view_problem, can_manage_problem, can_delete_problem, view_only_reason,
)
from app.timezone import now_utc, parse_local
from app.utils import (
    generate_problem_code, log_activity, notify, notify_many,
    recommended_recipients, recommended_seniors, first_responders,
    acknowledgers_above, assignment_recommendations, escalation_ladder,
    tier_members,
    save_attachment, find_similar_problems, allowed_file,
)

problems_bp = Blueprint("problems", __name__)

WIZARD_KEY = "problem_wizard"


def _status(code):
    return Status.query.filter_by(code=code).first()


def _visible_problems(user):
    """Query of the cards a user may open — the SQL twin of can_view_problem.

    Admin / Manager / Asst. Manager / Supervisor  every department
    Senior                                        their own department
    User                                          only their own cards
    """
    query = ProblemCard.query
    if user.role in (ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR):
        return query
    if user.role == ROLE_SENIOR:
        return query.filter(ProblemCard.department_id == user.department_id)
    return query.filter(
        or_(ProblemCard.reporter_id == user.id, ProblemCard.pic_id == user.id)
    )


def _set_status(problem, code, user=None, note=None):
    old = problem.status.code if problem.status else None
    new_status = _status(code)
    if new_status and new_status.id != problem.status_id:
        problem.status_id = new_status.id
        log_activity(problem, user, "Mengubah status", f"{old or '-'} -> {code}" + (f" ({note})" if note else ""))


# ---------------------------------------------------------------- LIST -----

@problems_bp.route("/")
@login_required
def list_problems():
    user = current_user
    query = _visible_problems(user)

    status_code = request.args.get("status")
    priority_code = request.args.get("priority")
    department_id = request.args.get("department", type=int)
    category_id = request.args.get("category", type=int)
    reporter_id = request.args.get("reporter", type=int)
    pic_id = request.args.get("pic", type=int)
    stage = request.args.get("stage")
    aging = request.args.get("aging")  # 'overdue'

    if status_code:
        query = query.join(Status).filter(Status.code == status_code)
    if priority_code:
        query = query.join(Priority).filter(Priority.code == priority_code)
    if department_id:
        query = query.filter(ProblemCard.department_id == department_id)
    if category_id:
        query = query.filter(ProblemCard.category_id == category_id)
    if reporter_id:
        query = query.filter(ProblemCard.reporter_id == reporter_id)
    if pic_id:
        query = query.filter(ProblemCard.pic_id == pic_id)

    problems = query.order_by(ProblemCard.created_at.desc()).all()

    if stage:
        problems = [p for p in problems if p.current_stage == stage]
    if aging == "overdue":
        problems = [p for p in problems if p.is_overdue]

    return render_template(
        "problems/list.html",
        problems=problems,
        summary=_summarise(problems, user),
        statuses=Status.query.order_by(Status.order).all(),
        priorities=Priority.query.order_by(Priority.level).all(),
        departments=Department.query.filter_by(is_active=True).all(),
        categories=Category.query.filter_by(is_active=True).all(),
        users=User.query.filter_by(active=True).order_by(User.full_name).all(),
        filters=request.args,
    )


# Stage colours mirror the HORENSO stepper on the card itself.
_STAGE_COLOURS = {
    "inform": "#6366F1",
    "consult": "#F59E0B",
    "action": "#0EA5E9",
    "resolution": "#8B5CF6",
    "closure": "#10B981",
}
_STAGE_LABELS = {
    "inform": "Renraku",
    "consult": "Sodan",
    "action": "Action",
    "resolution": "Resolution",
    "closure": "Closure",
}


def _summarise(problems, user):
    """Counts and mapping for the strip above the report list."""
    total = len(problems)
    done = sum(1 for p in problems if p.closed_at)
    overdue = sum(1 for p in problems if p.is_overdue)

    stage_counts = {key: 0 for key in _STAGE_LABELS}
    for p in problems:
        stage = p.current_stage
        if stage in stage_counts:
            stage_counts[stage] += 1

    stages = [
        {
            "key": key,
            "label": _STAGE_LABELS[key],
            "count": stage_counts[key],
            "color": _STAGE_COLOURS[key],
            "percent": round(stage_counts[key] / total * 100, 2) if total else 0,
        }
        for key in ["inform", "consult", "action", "resolution", "closure"]
    ]

    tier_counts = {role: 0 for role in ESCALATION_CHAIN}
    for p in problems:
        role = p.handled_by_role
        if role in tier_counts:
            tier_counts[role] += 1
    tiers = [{"role": r, "label": ROLE_LABELS[r], "count": tier_counts[r]} for r in ESCALATION_CHAIN]

    return {
        "total": total,
        "done": done,
        "open": total - done,
        "overdue": overdue,
        "stages": stages,
        "tiers": tiers,
        "escalating": sum(1 for p in problems if p.open_escalation),
        "pending_ack": sum(1 for p in problems if p.needs_acknowledgement_from(user)),
    }


# ------------------------------------------------------------------ WIZARD -

@problems_bp.route("/new")
@login_required
def new_problem():
    session[WIZARD_KEY] = {}
    return redirect(url_for("problems.wizard_step", step=1))


@problems_bp.route("/new/step/<int:step>", methods=["GET", "POST"])
@login_required
def wizard_step(step):
    draft = session.get(WIZARD_KEY, {})

    if step == 1:
        if request.method == "POST":
            draft["title"] = request.form.get("title", "").strip()
            draft["date_discovered"] = request.form.get("date_discovered") or ""
            draft["department_id"] = request.form.get("department_id", type=int)
            draft["area_process"] = request.form.get("area_process", "").strip()
            draft["category_id"] = request.form.get("category_id", type=int)
            draft["description"] = request.form.get("description", "").strip()
            draft["impact"] = request.form.get("impact", "").strip()
            draft["priority_id"] = request.form.get("priority_id", type=int)

            if not draft["title"] or not draft["department_id"] or not draft["priority_id"]:
                flash("Mohon lengkapi judul, departemen, dan tingkat prioritas.", "danger")
                session[WIZARD_KEY] = draft
                return redirect(url_for("problems.wizard_step", step=1))

            file = request.files.get("attachment")
            if file and file.filename and allowed_file(file.filename):
                folder = current_app.config["UPLOAD_FOLDER"]
                os.makedirs(folder, exist_ok=True)
                ext = file.filename.rsplit(".", 1)[-1].lower()
                stored = f"{uuid.uuid4().hex}.{ext}"
                file.save(os.path.join(folder, stored))
                draft["tmp_attachment"] = stored
                draft["tmp_attachment_original"] = file.filename

            session[WIZARD_KEY] = draft
            return redirect(url_for("problems.wizard_step", step=2))

        return render_template(
            "problems/wizard_step1.html",
            draft=draft,
            step=1,
            departments=Department.query.filter_by(is_active=True).all(),
            categories=Category.query.filter_by(is_active=True).all(),
            priorities=Priority.query.order_by(Priority.level).all(),
        )

    if step == 2:
        if "title" not in draft:
            return redirect(url_for("problems.new_problem"))

        department_id = draft.get("department_id")
        # A report goes to the Senior of the department first; if that tier is
        # empty it climbs the ladder on its own.
        recommended, responder_role = first_responders(department_id, exclude_user_id=current_user.id)
        department = Department.query.get(department_id) if department_id else None

        if request.method == "POST":
            recipient_ids = request.form.getlist("recipients", type=int)
            draft["recipient_ids"] = recipient_ids
            session[WIZARD_KEY] = draft
            return redirect(url_for("problems.wizard_step", step=3))

        return render_template(
            "problems/wizard_step2.html",
            draft=draft,
            step=2,
            recommended=recommended,
            responder_role=responder_role,
            responder_label=ROLE_LABELS.get(responder_role, responder_role),
            is_escalated=responder_role != ROLE_SENIOR,
            department=department,
            ladder=escalation_ladder(department_id, exclude_user_id=current_user.id),
            all_users=User.query.filter_by(active=True).order_by(User.full_name).all(),
        )

    if step == 3:
        if "title" not in draft:
            return redirect(url_for("problems.new_problem"))

        if request.method == "POST":
            needs_consult = request.form.get("needs_consultation") == "yes"
            draft["needs_consultation"] = needs_consult
            if needs_consult:
                draft["consult_question"] = request.form.get("question", "").strip()
                draft["consult_decision_needed"] = request.form.get("decision_needed", "").strip()
                draft["consult_suggested"] = request.form.get("suggested_solution", "").strip()
                draft["consult_options"] = request.form.get("options_text", "").strip()
                draft["consult_deadline"] = request.form.get("deadline", "")

            problem = _finalize_problem(draft)
            session.pop(WIZARD_KEY, None)
            flash(f"Problem Card {problem.code} berhasil dibuat.", "success")
            return redirect(url_for("problems.detail", problem_id=problem.id))

        return render_template("problems/wizard_step3.html", draft=draft, step=3)

    abort(404)


def _finalize_problem(draft):
    date_discovered = parse_local(draft.get("date_discovered")) or now_utc()

    needs_consult = draft.get("needs_consultation", False)
    status_code = STATUS_WAITING_DECISION if needs_consult else STATUS_NEW

    problem = ProblemCard(
        code=generate_problem_code(),
        title=draft["title"],
        description=draft.get("description", ""),
        impact=draft.get("impact", ""),
        area_process=draft.get("area_process", ""),
        date_discovered=date_discovered,
        department_id=draft.get("department_id"),
        category_id=draft.get("category_id"),
        priority_id=draft.get("priority_id"),
        status_id=_status(status_code).id if _status(status_code) else None,
        reporter_id=current_user.id,
        consultation_requested=needs_consult,
    )
    db.session.add(problem)
    db.session.flush()

    log_activity(problem, current_user, "Membuat Problem Card", problem.title)

    if draft.get("tmp_attachment"):
        att = Attachment(
            entity_type="problem",
            entity_id=problem.id,
            original_filename=draft.get("tmp_attachment_original", draft["tmp_attachment"]),
            stored_filename=draft["tmp_attachment"],
            uploaded_by_id=current_user.id,
        )
        db.session.add(att)

    recipient_ids = draft.get("recipient_ids") or []
    for uid in recipient_ids:
        comm = Communication(problem_id=problem.id, recipient_user_id=uid, notified_by_id=current_user.id)
        db.session.add(comm)
    if recipient_ids:
        log_activity(problem, current_user, "Menginformasikan pihak terkait", f"{len(recipient_ids)} orang diberi tahu")
        notify_many(recipient_ids, f"Anda diinformasikan mengenai {problem.code}: {problem.title}", problem=problem, ntype="inform")

    if needs_consult:
        deadline = parse_local(draft.get("consult_deadline"))
        consultation = Consultation(
            problem_id=problem.id,
            question=draft.get("consult_question", ""),
            decision_needed=draft.get("consult_decision_needed", ""),
            suggested_solution=draft.get("consult_suggested", ""),
            options_text=draft.get("consult_options", ""),
            deadline=deadline,
            requested_by_id=current_user.id,
        )
        db.session.add(consultation)
        log_activity(problem, current_user, "Meminta konsultasi", consultation.question)
        escalate_to = recommended_recipients(problem.department_id, exclude_user_id=current_user.id)
        notify_many([u.id for u in escalate_to],
                    f"Konsultasi dibutuhkan untuk {problem.code}", problem=problem, ntype="consult")

    db.session.commit()
    return problem


# ----------------------------------------------------------------- DETAIL -

@problems_bp.route("/<int:problem_id>")
@login_required
def detail(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)

    similar = find_similar_problems(problem) if problem.category_id else []

    timeline = []
    for a in problem.activity_logs:
        timeline.append({"time": a.created_at, "kind": "activity", "obj": a})
    for c in problem.comments:
        timeline.append({"time": c.created_at, "kind": "comment", "obj": c})
    timeline.sort(key=lambda x: x["time"])

    return render_template(
        "problems/detail.html",
        problem=problem,
        similar=similar,
        timeline=timeline,
        users=User.query.filter_by(active=True).order_by(User.full_name).all(),
        can_manage=can_manage_problem(current_user, problem),
        can_delete=can_delete_problem(current_user, problem),
        readonly_reason=view_only_reason(current_user, problem),
        needs_ack=problem.needs_acknowledgement_from(current_user),
        esc=_escalation_context(problem, current_user),
        required_ack=problem.required_acknowledgers(),
        acked_ids=problem.acknowledged_user_ids,
        statuses=Status.query.order_by(Status.order).all(),
        priorities=Priority.query.order_by(Priority.level).all(),
        rec=assignment_recommendations(problem, exclude_user_id=current_user.id),
    )


@problems_bp.route("/<int:problem_id>/comment", methods=["POST"])
@login_required
def add_comment(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    body = request.form.get("body", "").strip()
    if body:
        db.session.add(Comment(problem_id=problem.id, user_id=current_user.id, body=body))
        db.session.commit()
        flash("Komentar ditambahkan.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/assign", methods=["POST"])
@login_required
def assign(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not can_manage_problem(current_user, problem):
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat menugaskan PIC pada laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    pic_id = request.form.get("pic_id", type=int)
    if pic_id:
        pic = User.query.get(pic_id)
        old_pic = problem.pic.full_name if problem.pic else "belum ada"
        problem.pic_id = pic_id
        log_activity(problem, current_user, "Menugaskan PIC", f"{old_pic} -> {pic.full_name}")
        notify(pic_id, f"Anda ditugaskan sebagai PIC untuk {problem.code}", problem=problem, ntype="assignment")
        if problem.status and problem.status.code == STATUS_NEW:
            _set_status(problem, STATUS_IN_PROGRESS, current_user)
        db.session.commit()
        flash(f"PIC diubah menjadi {pic.full_name}.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/inform", methods=["POST"])
@login_required
def inform(problem_id):
    """Renraku shortcut: notify the SPV/Manager linear with this department."""
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)

    recipient_ids = request.form.getlist("recipients", type=int)
    if not recipient_ids:
        flash("Pilih minimal satu orang untuk diinformasikan.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    already = {c.recipient_user_id for c in problem.communications if c.recipient_user_id}
    added = []
    for uid in recipient_ids:
        if uid in already:
            continue
        user = User.query.get(uid)
        if not user or not user.active:
            continue
        db.session.add(Communication(
            problem_id=problem.id,
            recipient_user_id=uid,
            notified_by_id=current_user.id,
        ))
        added.append(user)

    if not added:
        flash("Semua orang yang dipilih sudah diinformasikan sebelumnya.", "info")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    names = ", ".join(u.full_name for u in added)
    log_activity(problem, current_user, "Menginformasikan pihak terkait", names)
    notify_many(
        [u.id for u in added],
        f"Anda diinformasikan mengenai {problem.code}: {problem.title}",
        problem=problem,
        ntype="inform",
    )
    db.session.commit()
    flash(f"{names} telah diinformasikan.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/priority", methods=["POST"])
@login_required
def change_priority(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_manage_problem(current_user, problem):
        abort(403)
    priority_id = request.form.get("priority_id", type=int)
    new_priority = Priority.query.get(priority_id)
    if new_priority:
        old_label = problem.priority.label if problem.priority else "-"
        problem.priority_id = new_priority.id
        log_activity(problem, current_user, "Mengubah Prioritas", f"{old_label} -> {new_priority.label}")
        db.session.commit()
        flash("Prioritas diperbarui.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


# --------------------------------------------------------------- SODAN ----

@problems_bp.route("/<int:problem_id>/consultation/new", methods=["POST"])
@login_required
def request_consultation(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not can_manage_problem(current_user, problem) and current_user.id != problem.reporter_id:
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat meminta konsultasi pada laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    question = request.form.get("question", "").strip()
    if not question:
        flash("Mohon tuliskan pertanyaan atau hal yang perlu didiskusikan.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    consultation = Consultation(
        problem_id=problem.id,
        question=question,
        decision_needed=request.form.get("decision_needed", "").strip(),
        suggested_solution=request.form.get("suggested_solution", "").strip(),
        options_text=request.form.get("options_text", "").strip(),
        requested_by_id=current_user.id,
    )
    db.session.add(consultation)
    problem.consultation_requested = True
    _set_status(problem, STATUS_WAITING_DECISION, current_user)
    log_activity(problem, current_user, "Meminta konsultasi", question)
    escalate_to = acknowledgers_above(current_user.role, problem.department_id) \
        or recommended_recipients(problem.department_id, exclude_user_id=current_user.id)
    notify_many([u.id for u in escalate_to if u.id != current_user.id],
                f"Konsultasi dibutuhkan untuk {problem.code}", problem=problem, ntype="consult")
    db.session.commit()
    flash("Permintaan konsultasi terkirim.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/consultation/<int:consultation_id>/decide", methods=["POST"])
@login_required
def decide(problem_id, consultation_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    consultation = Consultation.query.get_or_404(consultation_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not can_manage_problem(current_user, problem):
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat memberi keputusan pada laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    decision_text = request.form.get("decision_text", "").strip()
    if not decision_text:
        flash("Mohon isi keputusan yang diambil.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    decision = Decision(consultation_id=consultation.id, decision_text=decision_text, decided_by_id=current_user.id)
    consultation.status = "DECIDED"
    db.session.add(decision)
    log_activity(problem, current_user, "Memberikan keputusan konsultasi", decision_text)

    if problem.status and problem.status.code == STATUS_WAITING_DECISION:
        _set_status(problem, STATUS_IN_PROGRESS if problem.pic_id else STATUS_NEW, current_user)

    notify_ids = [uid for uid in [problem.reporter_id, problem.pic_id] if uid]
    notify_many(notify_ids, f"Keputusan telah dibuat untuk {problem.code}", problem=problem, ntype="decision")
    db.session.commit()
    flash("Keputusan tersimpan.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


# --------------------------------------------------------------- ACTIONS --

@problems_bp.route("/<int:problem_id>/actions/new", methods=["POST"])
@login_required
def add_action(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not can_manage_problem(current_user, problem):
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat menambah action pada laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    description = request.form.get("description", "").strip()
    pic_id = request.form.get("pic_id", type=int)
    due_date_raw = request.form.get("due_date")
    if not description:
        flash("Mohon isi deskripsi tindakan.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    due_date = parse_local(due_date_raw, "%Y-%m-%d")

    action = Action(
        problem_id=problem.id,
        description=description,
        pic_id=pic_id,
        due_date=due_date,
        created_by_id=current_user.id,
    )
    db.session.add(action)
    log_activity(problem, current_user, "Menambahkan Action", description)
    if pic_id:
        notify(pic_id, f"Anda mendapat tugas baru pada {problem.code}", problem=problem, ntype="action")
    if problem.status and problem.status.code in (STATUS_NEW, STATUS_WAITING_DECISION):
        _set_status(problem, STATUS_IN_PROGRESS, current_user)
    db.session.commit()
    flash("Action ditambahkan.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/actions/<int:action_id>/status", methods=["POST"])
@login_required
def update_action_status(problem_id, action_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    action = Action.query.get_or_404(action_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    # The action's own PIC may always update it; otherwise the usual rule holds.
    if not can_manage_problem(current_user, problem) and action.pic_id != current_user.id:
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat memperbarui action ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    new_status = request.form.get("status")
    notes = request.form.get("notes", "").strip()
    if new_status in ("TODO", "IN_PROGRESS", "COMPLETED"):
        action.status = new_status
        if notes:
            action.notes = notes
        if new_status == "COMPLETED":
            action.completed_at = now_utc()
        log_activity(problem, current_user, f"Memperbarui Action", f"'{action.description}' -> {new_status}")
        db.session.commit()
        flash("Status action diperbarui.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


# ------------------------------------------------------- RESOLUTION/CLOSE -

@problems_bp.route("/<int:problem_id>/resolve", methods=["POST"])
@login_required
def resolve(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not can_manage_problem(current_user, problem):
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat menyelesaikan laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    description = request.form.get("resolution_description", "").strip()
    evidence_note = request.form.get("resolution_evidence_note", "").strip()
    if not description:
        flash("Mohon jelaskan solusi yang telah dilakukan.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    problem.resolution_description = description
    problem.resolution_evidence_note = evidence_note
    problem.resolved_at = now_utc()
    problem.resolved_by_id = current_user.id
    # The tier that settled it. Everyone above only has to acknowledge.
    problem.resolved_by_role = current_user.role

    file = request.files.get("attachment")
    if file and file.filename:
        save_attachment(file, "resolution", problem.id, current_user.id)

    _set_status(problem, STATUS_RESOLVED, current_user)
    log_activity(
        problem, current_user, "Menandai Resolved",
        f"Diselesaikan pada tingkat {current_user.role_label}: {description}",
    )
    if problem.reporter_id:
        notify(problem.reporter_id, f"{problem.code} ditandai selesai, mohon verifikasi.",
               problem=problem, ntype="resolved")

    # Tell the tiers above: they only need to tick "mengetahui".
    above = [u for u in acknowledgers_above(current_user.role, problem.department_id)
             if u.id != current_user.id]
    if above:
        notify_many(
            [u.id for u in above],
            f"{problem.code} telah diselesaikan oleh {current_user.full_name} "
            f"({current_user.role_label}). Mohon konfirmasi mengetahui.",
            problem=problem, ntype="acknowledge",
        )
    db.session.commit()

    if above:
        flash(
            f"Problem diselesaikan pada tingkat {current_user.role_label}. "
            f"{len(above)} atasan diminta konfirmasi mengetahui.",
            "success",
        )
    else:
        flash("Problem ditandai sebagai Resolved. Menunggu verifikasi.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


def _escalation_context(problem, user):
    """What `user` may do about escalation on this card.

    A tier may only ask the tier immediately above it, and only while no
    request is still awaiting a reply.
    """
    open_request = problem.open_escalation
    can_request = False
    next_role = None
    recipients = []

    if user.role in ESCALATION_CHAIN and can_manage_problem(user, problem) \
            and not problem.resolved_at and open_request is None:
        next_role = problem.next_tier_above(user.role)
        if next_role:
            recipients = tier_members(next_role, problem.department_id, exclude_user_id=user.id)
            can_request = bool(recipients)

    # Whoever the open request was addressed to may respond to it.
    can_respond = bool(
        open_request
        and user.role == open_request.to_role
        and (user.role in ROLES_ACTION_ANY_DEPARTMENT
             or user.department_id == problem.department_id)
    )

    return {
        "open": open_request,
        "can_request": can_request,
        "next_role": next_role,
        "next_role_label": ROLE_LABELS.get(next_role, next_role),
        "recipients": recipients,
        "no_recipient_reason": (
            "Belum ada %s aktif yang dapat menerima permintaan ini."
            % ROLE_LABELS.get(next_role, next_role)
        ) if (next_role and not recipients) else None,
        "can_respond": can_respond,
        "at_top": user.role == ESCALATION_CHAIN[-1],
    }


@problems_bp.route("/<int:problem_id>/escalate", methods=["POST"])
@login_required
def escalate(problem_id):
    """Ask the tier directly above to take action on this card."""
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)

    ctx = _escalation_context(problem, current_user)
    if ctx["open"]:
        flash("Masih ada permintaan tindakan yang menunggu tanggapan.", "info")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    if not can_manage_problem(current_user, problem):
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat meminta tindakan pada laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    if current_user.role not in ESCALATION_CHAIN:
        flash("Hanya Senior, Supervisor, dan Asst. Manager yang dapat meminta tindakan ke atas.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    next_role = problem.next_tier_above(current_user.role)
    if not next_role:
        flash("Anda sudah berada pada tingkat tertinggi — tidak ada tingkat di atasnya.", "info")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    reason = request.form.get("reason", "").strip()
    if not reason:
        flash("Mohon jelaskan alasan permintaan tindakan.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    recipients = tier_members(next_role, problem.department_id, exclude_user_id=current_user.id)
    if not recipients:
        flash("Belum ada %s aktif yang dapat menerima permintaan ini." % ROLE_LABELS.get(next_role, next_role), "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    escalation = EscalationRequest(
        problem_id=problem.id,
        from_user_id=current_user.id,
        from_role=current_user.role,
        to_role=next_role,
        reason=reason,
        needed_action=request.form.get("needed_action", "").strip() or None,
    )
    db.session.add(escalation)

    label = ROLE_LABELS.get(next_role, next_role)
    log_activity(
        problem, current_user, "Meminta tindakan ke atas",
        f"{current_user.role_label} -> {label}: {reason}",
    )
    _set_status(problem, STATUS_WAITING_DECISION, current_user, note=f"eskalasi ke {label}")
    notify_many(
        [u.id for u in recipients],
        f"{current_user.full_name} ({current_user.role_label}) meminta tindakan Anda pada {problem.code}.",
        problem=problem, ntype="escalation",
    )
    db.session.commit()
    flash(f"Permintaan tindakan dikirim ke {label} ({len(recipients)} orang).", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/escalation/<int:escalation_id>/respond", methods=["POST"])
@login_required
def respond_escalation(problem_id, escalation_id):
    """The receiving tier takes the card over, or hands it back down."""
    problem = ProblemCard.query.get_or_404(problem_id)
    escalation = EscalationRequest.query.get_or_404(escalation_id)
    if escalation.problem_id != problem.id:
        abort(404)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not escalation.is_open:
        flash("Permintaan ini sudah ditanggapi.", "info")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    if current_user.role != escalation.to_role or not can_manage_problem(current_user, problem):
        flash("Permintaan ini ditujukan kepada %s." % escalation.to_role_label, "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    decision = request.form.get("decision")
    note = request.form.get("response_note", "").strip()
    if decision not in ("accept", "decline"):
        flash("Pilih terima atau kembalikan.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    if decision == "decline" and not note:
        flash("Mohon tuliskan alasan saat mengembalikan permintaan.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    escalation.status = "ACCEPTED" if decision == "accept" else "DECLINED"
    escalation.responded_by_id = current_user.id
    escalation.responded_at = now_utc()
    escalation.response_note = note or None

    if decision == "accept":
        # Taking it over means owning it: the card moves to this tier.
        problem.pic_id = current_user.id
        log_activity(problem, current_user, "Menerima permintaan tindakan",
                     f"Diambil alih oleh {current_user.role_label}" + (f": {note}" if note else ""))
        _set_status(problem, STATUS_IN_PROGRESS, current_user)
        message = f"{current_user.full_name} ({current_user.role_label}) mengambil alih {problem.code}."
    else:
        log_activity(problem, current_user, "Mengembalikan permintaan tindakan",
                     f"Dikembalikan ke {escalation.from_role_label}: {note}")
        _set_status(problem, STATUS_IN_PROGRESS, current_user)
        message = (f"{current_user.full_name} ({current_user.role_label}) mengembalikan "
                   f"{problem.code} kepada Anda: {note}")

    targets = [escalation.from_user_id, problem.reporter_id]
    notify_many([t for t in targets if t and t != current_user.id], message,
                problem=problem, ntype="escalation")
    db.session.commit()
    flash("Tanggapan tersimpan." if decision == "accept" else "Permintaan dikembalikan.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/acknowledge", methods=["POST"])
@login_required
def acknowledge(problem_id):
    """A higher tier ticking "mengetahui" on work settled below them."""
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not problem.resolved_at:
        flash("Laporan ini belum diselesaikan, belum ada yang perlu dikonfirmasi.", "info")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    if not problem.needs_acknowledgement_from(current_user):
        flash("Tidak ada konfirmasi yang menunggu dari Anda pada laporan ini.", "info")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    if not request.form.get("confirm"):
        flash("Centang pernyataan konfirmasi terlebih dahulu.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    resolver = problem.resolved_by.full_name if problem.resolved_by else "PIC terkait"
    db.session.add(Acknowledgement(
        problem_id=problem.id,
        user_id=current_user.id,
        role_at_time=current_user.role,
        note=request.form.get("note", "").strip() or None,
    ))
    log_activity(
        problem, current_user, "Mengetahui penyelesaian",
        f"Mengetahui dan telah diselesaikan oleh {resolver} ({problem.resolved_by_role_label}).",
    )
    if problem.resolved_by_id and problem.resolved_by_id != current_user.id:
        notify(problem.resolved_by_id,
               f"{current_user.full_name} ({current_user.role_label}) mengetahui penyelesaian {problem.code}.",
               problem=problem, ntype="acknowledged")
    db.session.commit()
    flash("Konfirmasi tersimpan. Terima kasih.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/delete", methods=["POST"])
@login_required
def delete_problem(problem_id):
    """Permanently remove a problem card. Admin only."""
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_delete_problem(current_user, problem):
        abort(403)

    # Typing the code is the confirmation step for an irreversible delete.
    typed = (request.form.get("confirm_code") or "").strip()
    if typed != problem.code:
        flash(f"Ketik kode laporan ({problem.code}) dengan tepat untuk menghapus.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))

    code, title = problem.code, problem.title

    # Attachments hang off (entity_type, entity_id) rather than a foreign key,
    # so each owning entity is matched by its own id — never by the problem id
    # alone, which would sweep up another entity that happens to share it.
    owners = [("problem", {problem.id}), ("resolution", {problem.id})]
    owners.append(("action", {a.id for a in problem.actions}))
    owners.append(("comment", {c.id for c in problem.comments}))

    folder = current_app.config["UPLOAD_FOLDER"]
    for entity_type, ids in owners:
        if not ids:
            continue
        for att in Attachment.query.filter(
            Attachment.entity_type == entity_type, Attachment.entity_id.in_(ids)
        ).all():
            path = os.path.join(folder, att.stored_filename)
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                current_app.logger.warning("Could not remove upload %s", path)
            db.session.delete(att)

    # Notifications point at the card but have no cascade rule of their own.
    Notification.query.filter_by(problem_id=problem.id).delete(synchronize_session=False)

    db.session.delete(problem)
    db.session.commit()
    flash(f"Laporan {code} — “{title}” telah dihapus permanen.", "info")
    return redirect(url_for("problems.list_problems"))


@problems_bp.route("/<int:problem_id>/close", methods=["POST"])
@login_required
def close(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    # The reporter verifies their own card; otherwise it takes someone who can
    # act on that department.
    allowed = can_manage_problem(current_user, problem) or current_user.id == problem.reporter_id
    if not allowed:
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat menutup laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    comment = request.form.get("closing_comment", "").strip()
    problem.closing_comment = comment
    problem.closed_at = now_utc()
    problem.closed_by_id = current_user.id
    _set_status(problem, STATUS_CLOSED, current_user)
    log_activity(problem, current_user, "Menutup Problem (Closed)", comment)
    db.session.commit()
    flash("Problem telah ditutup. Terima kasih sudah menyelesaikannya bersama!", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/reopen", methods=["POST"])
@login_required
def reopen(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not can_manage_problem(current_user, problem):
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat membuka kembali laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    problem.resolved_at = None
    problem.resolved_by_role = None
    problem.closed_at = None
    # A reopened card starts its acknowledgement round over.
    for ack in list(problem.acknowledgements):
        db.session.delete(ack)
    _set_status(problem, STATUS_IN_PROGRESS, current_user, note="dibuka kembali")
    log_activity(problem, current_user, "Membuka kembali Problem", request.form.get("reason", ""))
    db.session.commit()
    flash("Problem dibuka kembali.", "info")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/root-cause", methods=["POST"])
@login_required
def add_root_cause(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    if not can_manage_problem(current_user, problem):
        flash(view_only_reason(current_user, problem) or "Anda tidak dapat menambah RCA pada laporan ini.", "danger")
        return redirect(url_for("problems.detail", problem_id=problem.id))
    rca = RootCauseAnalysis(
        problem_id=problem.id,
        immediate_cause=request.form.get("immediate_cause", "").strip(),
        root_cause=request.form.get("root_cause", "").strip(),
        corrective_action=request.form.get("corrective_action", "").strip(),
        preventive_action=request.form.get("preventive_action", "").strip(),
        created_by_id=current_user.id,
    )
    db.session.add(rca)
    log_activity(problem, current_user, "Menambahkan Root Cause Analysis")
    db.session.commit()
    flash("Root Cause Analysis ditambahkan.", "success")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/<int:problem_id>/attachment", methods=["POST"])
@login_required
def upload_attachment(problem_id):
    problem = ProblemCard.query.get_or_404(problem_id)
    if not can_view_problem(current_user, problem):
        abort(403)
    file = request.files.get("attachment")
    if file and file.filename:
        att = save_attachment(file, "problem", problem.id, current_user.id)
        if att:
            log_activity(problem, current_user, "Menambahkan lampiran", att.original_filename)
            db.session.commit()
            flash("Lampiran ditambahkan.", "success")
        else:
            flash("Jenis file tidak didukung.", "danger")
    return redirect(url_for("problems.detail", problem_id=problem.id))


@problems_bp.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], filename)
