from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from app.extensions import db
from app.timezone import now_utc

# ---- Role constants ----
# The escalation ladder a report climbs:
#   User (pelapor) -> Senior -> Supervisor -> Asst. Manager -> Manager
# Admin sits outside the ladder: it administers the system and sees everything.
ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_ASST_MANAGER = "asst_manager"
ROLE_SUPERVISOR = "supervisor"
ROLE_SENIOR = "senior"
ROLE_USER = "user"

ROLES = [ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR, ROLE_SENIOR, ROLE_USER]

ROLE_LABELS = {
    ROLE_ADMIN: "Admin",
    ROLE_MANAGER: "Manager",
    ROLE_ASST_MANAGER: "Asst. Manager",
    ROLE_SUPERVISOR: "Supervisor",
    ROLE_SENIOR: "Senior",
    ROLE_USER: "User / Reporter",
}

# The tiers a report escalates through, lowest first. Senior is the first tier
# to receive a report from a user.
ESCALATION_CHAIN = [ROLE_SENIOR, ROLE_SUPERVISOR, ROLE_ASST_MANAGER, ROLE_MANAGER]

# Seniority used for "who still has to acknowledge" and for permission checks.
ROLE_RANK = {
    ROLE_USER: 0,
    ROLE_SENIOR: 1,
    ROLE_SUPERVISOR: 2,
    ROLE_ASST_MANAGER: 3,
    ROLE_MANAGER: 4,
    ROLE_ADMIN: 5,
}

# Roles whose remit spans every department.
CROSS_DEPARTMENT_ROLES = (ROLE_ASST_MANAGER, ROLE_MANAGER, ROLE_ADMIN)

# Roles that may act on (not merely read) a card outside their own department.
ROLES_ACTION_ANY_DEPARTMENT = (ROLE_ASST_MANAGER, ROLE_MANAGER, ROLE_ADMIN)

# ---- HORENSO stage constants ----
STAGE_REPORT = "report"
STAGE_INFORM = "inform"
STAGE_CONSULT = "consult"
STAGE_ACTION = "action"
STAGE_FOLLOWUP = "followup"
STAGE_RESOLUTION = "resolution"
STAGE_CLOSURE = "closure"

# ---- Status codes (seeded, editable by admin) ----
STATUS_NEW = "NEW"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_WAITING_DECISION = "WAITING_DECISION"
STATUS_RESOLVED = "RESOLVED"
STATUS_CLOSED = "CLOSED"


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_USER)
    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    active = db.Column(db.Boolean, default=True, nullable=False)
    avatar_color = db.Column(db.String(20), default="#6366F1")
    created_at = db.Column(db.DateTime, default=now_utc)
    last_login_at = db.Column(db.DateTime)
    reset_token = db.Column(db.String(64))
    reset_token_expires = db.Column(db.DateTime)

    department = db.relationship("Department", back_populates="users")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_active(self):
        return self.active

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    @property
    def rank(self):
        return ROLE_RANK.get(self.role, 0)

    @property
    def is_cross_department(self):
        """Sees every department rather than only their own."""
        return self.role in CROSS_DEPARTMENT_ROLES

    def outranks(self, other_role):
        return self.rank > ROLE_RANK.get(other_role, 0)

    @property
    def initials(self):
        parts = self.full_name.split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.full_name[:2].upper()

    def has_role(self, *roles):
        return self.role in roles

    def __repr__(self):
        return f"<User {self.username}>"


class Department(db.Model):
    __tablename__ = "departments"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    code = db.Column(db.String(20))
    is_active = db.Column(db.Boolean, default=True)

    users = db.relationship("User", back_populates="department")

    def __repr__(self):
        return f"<Department {self.name}>"


class Category(db.Model):
    __tablename__ = "problem_categories"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    icon = db.Column(db.String(50), default="tag")
    is_active = db.Column(db.Boolean, default=True)
    # Worked examples that tell a reporter what belongs in this category,
    # phrased the way the testing journals do (comma separated).
    reference = db.Column(db.Text)

    @property
    def reference_items(self):
        """The reference split into chips.

        Commas inside brackets belong to the example they enumerate — splitting
        on them would turn "Instrumen uji (HPLC, GC)" into two broken chips —
        so only top-level commas separate items.
        """
        if not self.reference:
            return []
        items, current, depth = [], [], 0
        for ch in self.reference:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth = max(0, depth - 1)
            if ch == "," and depth == 0:
                items.append("".join(current).strip())
                current = []
            else:
                current.append(ch)
        items.append("".join(current).strip())
        return [item for item in items if item]

    def __repr__(self):
        return f"<Category {self.name}>"


class Priority(db.Model):
    __tablename__ = "priorities"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)  # LOW, MEDIUM, HIGH, CRITICAL
    label = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255))
    color = db.Column(db.String(20), nullable=False, default="#6B7280")
    icon = db.Column(db.String(10), default="")
    level = db.Column(db.Integer, nullable=False, default=1)  # ordering, higher = more severe
    sla_hours = db.Column(db.Integer, nullable=False, default=72)

    def __repr__(self):
        return f"<Priority {self.code}>"


class Status(db.Model):
    __tablename__ = "statuses"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False)
    label = db.Column(db.String(60), nullable=False)
    color = db.Column(db.String(20), default="#6B7280")
    order = db.Column(db.Integer, default=0)
    is_terminal = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Status {self.code}>"


class ProblemCard(db.Model):
    __tablename__ = "problem_cards"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    impact = db.Column(db.Text)
    area_process = db.Column(db.String(150))
    date_discovered = db.Column(db.DateTime, default=now_utc)

    department_id = db.Column(db.Integer, db.ForeignKey("departments.id"))
    category_id = db.Column(db.Integer, db.ForeignKey("problem_categories.id"))
    priority_id = db.Column(db.Integer, db.ForeignKey("priorities.id"))
    status_id = db.Column(db.Integer, db.ForeignKey("statuses.id"))

    reporter_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    pic_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    consultation_requested = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=now_utc)
    updated_at = db.Column(db.DateTime, default=now_utc, onupdate=now_utc)

    resolution_description = db.Column(db.Text)
    resolution_evidence_note = db.Column(db.String(255))
    resolved_at = db.Column(db.DateTime)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    # Tier that actually closed the problem out. Everyone above it only has to
    # acknowledge ("mengetahui"), never to re-do the work.
    resolved_by_role = db.Column(db.String(20))

    closed_at = db.Column(db.DateTime)
    closed_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    closing_comment = db.Column(db.Text)

    department = db.relationship("Department")
    category = db.relationship("Category")
    priority = db.relationship("Priority")
    status = db.relationship("Status")
    reporter = db.relationship("User", foreign_keys=[reporter_id])
    pic = db.relationship("User", foreign_keys=[pic_id])
    resolved_by = db.relationship("User", foreign_keys=[resolved_by_id])
    closed_by = db.relationship("User", foreign_keys=[closed_by_id])

    communications = db.relationship("Communication", backref="problem", cascade="all, delete-orphan", order_by="Communication.notified_at")
    consultations = db.relationship("Consultation", backref="problem", cascade="all, delete-orphan", order_by="Consultation.requested_at")
    actions = db.relationship("Action", backref="problem", cascade="all, delete-orphan", order_by="Action.created_at")
    comments = db.relationship("Comment", backref="problem", cascade="all, delete-orphan", order_by="Comment.created_at")
    activity_logs = db.relationship("ActivityLog", backref="problem", cascade="all, delete-orphan", order_by="ActivityLog.created_at")
    root_causes = db.relationship("RootCauseAnalysis", backref="problem", cascade="all, delete-orphan")
    acknowledgements = db.relationship("Acknowledgement", backref="problem", cascade="all, delete-orphan", order_by="Acknowledgement.acknowledged_at")
    escalations = db.relationship("EscalationRequest", backref="problem", cascade="all, delete-orphan", order_by="EscalationRequest.requested_at")

    # ---- HORENSO stage progress ----
    @property
    def stage_report_done(self):
        return True  # a card only exists once reported

    @property
    def stage_inform_done(self):
        return len(self.communications) > 0

    @property
    def stage_consult_done(self):
        if not self.consultation_requested:
            return True
        return any(c.status == "DECIDED" for c in self.consultations)

    @property
    def stage_action_done(self):
        if not self.actions:
            return False
        return all(a.status == "COMPLETED" for a in self.actions)

    @property
    def stage_resolution_done(self):
        return self.resolved_at is not None

    @property
    def stage_closure_done(self):
        return self.closed_at is not None

    @property
    def current_stage(self):
        if not self.stage_inform_done:
            return STAGE_INFORM
        if not self.stage_consult_done:
            return STAGE_CONSULT
        if not self.actions:
            return STAGE_ACTION
        if not self.stage_action_done:
            return STAGE_ACTION
        if not self.stage_resolution_done:
            return STAGE_RESOLUTION
        if not self.stage_closure_done:
            return STAGE_CLOSURE
        return STAGE_CLOSURE

    @property
    def age(self):
        end = self.closed_at or now_utc()
        return end - self.created_at

    @property
    def age_display(self):
        delta = self.age
        total_seconds = int(delta.total_seconds())
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes = rem // 60
        if days > 0:
            return f"{days}h {hours}j"
        if hours > 0:
            return f"{hours}j {minutes}m"
        return f"{minutes}m"

    @property
    def is_overdue(self):
        if self.status and self.status.code in (STATUS_RESOLVED, STATUS_CLOSED):
            return False
        if not self.priority:
            return False
        sla_seconds = self.priority.sla_hours * 3600
        return self.age.total_seconds() > sla_seconds

    # ---- Escalation & acknowledgement ------------------------------------
    @property
    def resolved_by_role_label(self):
        return ROLE_LABELS.get(self.resolved_by_role, self.resolved_by_role or "-")

    @property
    def open_escalation(self):
        """The escalation still waiting for a response, if any."""
        for e in reversed(self.escalations):
            if e.status == "OPEN":
                return e
        return None

    @property
    def handled_by_role(self):
        """Which tier currently owns this card.

        Starts at the PIC's tier (or Senior by default) and moves up with every
        accepted escalation; an open request already counts as "sitting with"
        the tier it was sent to, since that is who has to respond.
        """
        if self.resolved_by_role:
            return self.resolved_by_role
        tier = None
        for e in self.escalations:
            if e.status in ("OPEN", "ACCEPTED"):
                if tier is None or ROLE_RANK.get(e.to_role, 0) > ROLE_RANK.get(tier, 0):
                    tier = e.to_role
        if tier:
            return tier
        if self.pic and self.pic.role in ESCALATION_CHAIN:
            return self.pic.role
        return ESCALATION_CHAIN[0]

    @property
    def handled_by_role_label(self):
        return ROLE_LABELS.get(self.handled_by_role, self.handled_by_role)

    def next_tier_above(self, role):
        """The single tier a given role may escalate to, or None at the top."""
        if role not in ESCALATION_CHAIN:
            return None
        index = ESCALATION_CHAIN.index(role)
        if index + 1 >= len(ESCALATION_CHAIN):
            return None
        return ESCALATION_CHAIN[index + 1]

    @property
    def stage_map(self):
        """The HORENSO journey as a list the UI can render as a stepper.

        Each entry is {key, label, sub, done, current}. "current" marks the one
        step the card is waiting on right now.
        """
        steps = [
            ("report", "Hokoku", "Laporan dibuat", True),
            ("inform", "Renraku", "Pihak terkait diinformasikan", self.stage_inform_done),
            ("consult", "Sodan", "Konsultasi & keputusan", self.stage_consult_done),
            ("action", "Action", "Tindakan dikerjakan", self.stage_action_done),
            ("resolution", "Resolution", "Dinyatakan selesai", self.stage_resolution_done),
            ("closure", "Closure", "Diverifikasi & ditutup", self.stage_closure_done),
        ]
        current = self.current_stage
        # current_stage never reports "report"; the first unfinished step wins.
        first_open = next((key for key, _l, _s, done in steps if not done), None)
        out = []
        for key, label, sub, done in steps:
            out.append({
                "key": key,
                "label": label,
                "sub": sub,
                "done": bool(done),
                "current": (key == current and not done) or (key == first_open and current not in
                                                             [s[0] for s in steps]),
            })
        return out

    @property
    def progress_percent(self):
        steps = self.stage_map
        return round(sum(1 for s in steps if s["done"]) / len(steps) * 100)

    @property
    def acknowledged_user_ids(self):
        return {a.user_id for a in self.acknowledgements}

    def required_acknowledgers(self):
        """Tiers above the one that resolved this card.

        Once a Senior settles a problem the tiers above it do not redo the work
        — they only tick "mengetahui". The same holds when a Supervisor settles
        it: only Asst. Manager and Manager are left to acknowledge.
        """
        if not self.resolved_at or not self.resolved_by_role:
            return []
        resolver_rank = ROLE_RANK.get(self.resolved_by_role, 0)
        higher = [r for r in ESCALATION_CHAIN if ROLE_RANK[r] > resolver_rank]
        if not higher:
            return []

        rows = User.query.filter(User.role.in_(higher), User.active == True).all()  # noqa: E712
        out = []
        for u in rows:
            # Asst. Manager and Manager span every department; Supervisor and
            # Senior only acknowledge cards from their own department.
            if u.role in CROSS_DEPARTMENT_ROLES or u.department_id == self.department_id:
                out.append(u)
        out.sort(key=lambda u: (ROLE_RANK[u.role], u.full_name))
        return out

    @property
    def pending_acknowledgers(self):
        done = self.acknowledged_user_ids
        return [u for u in self.required_acknowledgers() if u.id not in done]

    @property
    def acknowledgement_complete(self):
        return self.resolved_at is not None and not self.pending_acknowledgers

    def needs_acknowledgement_from(self, user):
        if not self.resolved_at or user is None:
            return False
        if user.id in self.acknowledged_user_ids:
            return False
        return any(u.id == user.id for u in self.required_acknowledgers())

    def __repr__(self):
        return f"<ProblemCard {self.code}>"


class Communication(db.Model):
    __tablename__ = "problem_communications"
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"), nullable=False)
    recipient_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recipient_label = db.Column(db.String(120))  # e.g. "QC Supervisor" when no specific user
    method = db.Column(db.String(30), default="in-app")
    status = db.Column(db.String(20), default="SENT")  # SENT, ACKNOWLEDGED
    notified_at = db.Column(db.DateTime, default=now_utc)
    notified_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))

    recipient_user = db.relationship("User", foreign_keys=[recipient_user_id])
    notified_by = db.relationship("User", foreign_keys=[notified_by_id])


class Consultation(db.Model):
    __tablename__ = "consultations"
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"), nullable=False)
    question = db.Column(db.Text, nullable=False)
    decision_needed = db.Column(db.Text)
    suggested_solution = db.Column(db.Text)
    options_text = db.Column(db.Text)
    deadline = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="OPEN")  # OPEN, DECIDED
    requested_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    requested_at = db.Column(db.DateTime, default=now_utc)

    requested_by = db.relationship("User")
    decisions = db.relationship("Decision", backref="consultation", cascade="all, delete-orphan")


class Decision(db.Model):
    __tablename__ = "decisions"
    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(db.Integer, db.ForeignKey("consultations.id"), nullable=False)
    decision_text = db.Column(db.Text, nullable=False)
    decided_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    decided_at = db.Column(db.DateTime, default=now_utc)

    decided_by = db.relationship("User")


class Action(db.Model):
    __tablename__ = "actions"
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"), nullable=False)
    description = db.Column(db.Text, nullable=False)
    pic_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    due_date = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="TODO")  # TODO, IN_PROGRESS, COMPLETED
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=now_utc)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    completed_at = db.Column(db.DateTime)

    pic = db.relationship("User", foreign_keys=[pic_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])


class Attachment(db.Model):
    __tablename__ = "attachments"
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(30), nullable=False)  # problem, action, resolution, comment
    entity_id = db.Column(db.Integer, nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    uploaded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    uploaded_at = db.Column(db.DateTime, default=now_utc)

    uploaded_by = db.relationship("User")


class Comment(db.Model):
    __tablename__ = "comments"
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=now_utc)

    user = db.relationship("User")


class Notification(db.Model):
    __tablename__ = "notifications"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"))
    type = db.Column(db.String(40))
    message = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=now_utc)

    problem = db.relationship("ProblemCard")


class ActivityLog(db.Model):
    """Every change made anywhere in the app.

    `problem_id` is optional: a card's own history still points at it, while
    changes to users, departments, categories, priorities, statuses, branding
    and sessions are recorded against `entity_type` / `entity_id` instead.
    """

    __tablename__ = "activity_logs"
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    entity_type = db.Column(db.String(30), default="problem", index=True)
    entity_id = db.Column(db.Integer)
    entity_label = db.Column(db.String(160))
    action = db.Column(db.String(120), nullable=False)
    detail = db.Column(db.Text)
    ip_address = db.Column(db.String(45))
    created_at = db.Column(db.DateTime, default=now_utc, index=True)

    user = db.relationship("User")

    ENTITY_LABELS = {
        "problem": "Problem Card",
        "user": "User",
        "department": "Departemen",
        "category": "Kategori",
        "priority": "Prioritas",
        "status": "Status",
        "theme": "Tampilan",
        "session": "Sesi",
        "account": "Akun",
    }

    @property
    def entity_type_label(self):
        return self.ENTITY_LABELS.get(self.entity_type, (self.entity_type or "Lainnya").title())

    @property
    def target_label(self):
        """What was changed, as a person would name it."""
        if self.problem_id and self.problem:
            return "#" + self.problem.code
        return self.entity_label or "-"


class RootCauseAnalysis(db.Model):
    __tablename__ = "root_cause_analyses"
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"), nullable=False)
    immediate_cause = db.Column(db.Text)
    root_cause = db.Column(db.Text)
    corrective_action = db.Column(db.Text)
    preventive_action = db.Column(db.Text)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=now_utc)

    created_by = db.relationship("User")


class EscalationRequest(db.Model):
    """One tier asking the tier directly above it to take over.

    Senior -> Supervisor -> Asst. Manager -> Manager. Only ever one step: a
    Senior cannot jump straight to the Manager, so the chain of custody stays
    intact and every level sees what reached it and why.
    """

    __tablename__ = "escalation_requests"
    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"), nullable=False, index=True)

    from_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    from_role = db.Column(db.String(20))
    to_role = db.Column(db.String(20), nullable=False)

    reason = db.Column(db.Text, nullable=False)
    needed_action = db.Column(db.Text)

    # OPEN -> ACCEPTED (taken over) or DECLINED (handed back down)
    status = db.Column(db.String(20), default="OPEN", index=True)
    requested_at = db.Column(db.DateTime, default=now_utc)

    responded_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    responded_at = db.Column(db.DateTime)
    response_note = db.Column(db.Text)

    from_user = db.relationship("User", foreign_keys=[from_user_id])
    responded_by = db.relationship("User", foreign_keys=[responded_by_id])

    @property
    def from_role_label(self):
        return ROLE_LABELS.get(self.from_role, self.from_role or "-")

    @property
    def to_role_label(self):
        return ROLE_LABELS.get(self.to_role, self.to_role or "-")

    @property
    def status_label(self):
        return {
            "OPEN": "Menunggu tanggapan",
            "ACCEPTED": "Diterima & ditangani",
            "DECLINED": "Dikembalikan",
        }.get(self.status, self.status)

    @property
    def is_open(self):
        return self.status == "OPEN"


class Acknowledgement(db.Model):
    """A higher tier ticking "mengetahui" on a problem someone below resolved."""

    __tablename__ = "acknowledgements"
    __table_args__ = (db.UniqueConstraint("problem_id", "user_id", name="uq_ack_problem_user"),)

    id = db.Column(db.Integer, primary_key=True)
    problem_id = db.Column(db.Integer, db.ForeignKey("problem_cards.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    role_at_time = db.Column(db.String(20))
    note = db.Column(db.Text)
    acknowledged_at = db.Column(db.DateTime, default=now_utc)

    user = db.relationship("User")

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role_at_time, self.role_at_time or "-")


class ThemeSetting(db.Model):
    __tablename__ = "theme_settings"
    id = db.Column(db.Integer, primary_key=True)
    app_name = db.Column(db.String(100), default="HORENSO")
    company_name = db.Column(db.String(150), default="SIG Laboratory")
    # Logo and favicon are uploaded files served from /branding/<file>. The
    # columns still hold a URL so an externally hosted image keeps working.
    logo_url = db.Column(db.String(255))
    favicon_url = db.Column(db.String(255))
    logo_filename = db.Column(db.String(255))
    favicon_filename = db.Column(db.String(255))
    primary_color = db.Column(db.String(20), default="#4F46E5")
    secondary_color = db.Column(db.String(20), default="#0EA5E9")
    accent_color = db.Column(db.String(20), default="#F59E0B")
    background_color = db.Column(db.String(20), default="#F8FAFC")
    font_family = db.Column(db.String(80), default="Inter")
    sidebar_style = db.Column(db.String(20), default="light")
    welcome_message = db.Column(db.String(255), default="Let's solve it together.")
    login_tagline = db.Column(db.String(255), default="Every problem is a chance to improve.")
    footer_text = db.Column(db.String(255), default="HORENSO Problem Card System")

    def _asset(self, filename, url):
        """Prefer an uploaded file; fall back to a URL typed in earlier.

        Built without requiring a request context, so the value is also usable
        from a shell, a background job, or a test.
        """
        if filename:
            try:
                from flask import url_for, has_request_context
                if has_request_context():
                    return url_for("main.branding_file", filename=filename)
            except Exception:
                pass
            return "/branding/%s" % filename
        return url or None

    @property
    def logo_src(self):
        return self._asset(self.logo_filename, self.logo_url)

    @property
    def favicon_src(self):
        return self._asset(self.favicon_filename, self.favicon_url)


class SystemSetting(db.Model):
    __tablename__ = "system_settings"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(80), unique=True, nullable=False)
    value = db.Column(db.String(255))
    description = db.Column(db.String(255))
