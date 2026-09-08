"""Seed demo data for HORENSO. Usage:
    python seed.py          # seed only if database is empty
    python seed.py --reset  # drop everything and reseed from scratch
"""
import sys
from datetime import datetime, timedelta
from app import create_app
from app.extensions import db
from app.models import (
    User, Department, Category, Priority, Status, ProblemCard, Communication,
    Consultation, Decision, Action, Comment, ActivityLog, RootCauseAnalysis, ThemeSetting,
    Acknowledgement,
    ROLE_ADMIN, ROLE_MANAGER, ROLE_ASST_MANAGER, ROLE_SUPERVISOR, ROLE_SENIOR, ROLE_USER,
    STATUS_NEW, STATUS_IN_PROGRESS, STATUS_WAITING_DECISION, STATUS_RESOLVED, STATUS_CLOSED,
)

app = create_app()

PRIORITIES = [
    ("LOW", "Low", "Tidak berdampak signifikan terhadap pekerjaan.", "#10B981", 1, 168),
    ("MEDIUM", "Medium", "Mengganggu pekerjaan tetapi masih ada workaround.", "#F59E0B", 2, 72),
    ("HIGH", "High", "Menghambat pekerjaan utama.", "#F97316", 3, 24),
    ("CRITICAL", "Critical", "Berpotensi menyebabkan major impact, butuh perhatian segera.", "#EF4444", 4, 4),
]

STATUSES = [
    (STATUS_NEW, "New", "#6366F1", 1, False),
    (STATUS_IN_PROGRESS, "In Progress", "#0EA5E9", 2, False),
    (STATUS_WAITING_DECISION, "Waiting Decision", "#F59E0B", 3, False),
    (STATUS_RESOLVED, "Resolved", "#10B981", 4, False),
    (STATUS_CLOSED, "Closed", "#64748B", 5, True),
]

DEPARTMENTS = [("Quality Control", "QC"), ("Produksi", "PRD"), ("Gudang", "WH"), ("Maintenance", "MTC")]
# Categories carry a reference line describing what belongs in them; the text
# lives in app/migrations.py so the seed and an existing database stay in sync.
from app.migrations import CATEGORY_REFERENCES  # noqa: E402

CATEGORIES = [
    "Instrument", "Material", "Process", "Documentation", "Safety",
    "Kalibrasi & Kualifikasi", "Utility & Lingkungan",
]

USERS = [
    dict(username="farhan", email="farhan@siglaboratory.co.id", full_name="Farhan", role=ROLE_ADMIN, dept="Quality Control", password="farhan123", color="#4F46E5"),
    dict(username="hendra", email="hendra@siglaboratory.co.id", full_name="Hendra Gunawan", role=ROLE_MANAGER, dept="Quality Control", password="horensu123", color="#7C3AED"),
    dict(username="maya", email="maya@siglaboratory.co.id", full_name="Maya Puspita", role=ROLE_ASST_MANAGER, dept="Quality Control", password="horensu123", color="#DB2777"),
    dict(username="siti", email="siti@siglaboratory.co.id", full_name="Siti Nurhaliza", role=ROLE_SUPERVISOR, dept="Quality Control", password="horensu123", color="#0EA5E9"),
    dict(username="budi", email="budi@siglaboratory.co.id", full_name="Budi Santoso", role=ROLE_SENIOR, dept="Quality Control", password="horensu123", color="#F59E0B"),
    dict(username="rina", email="rina@siglaboratory.co.id", full_name="Rina Wulandari", role=ROLE_USER, dept="Produksi", password="horensu123", color="#EC4899"),
    dict(username="agus", email="agus@siglaboratory.co.id", full_name="Agus Prasetyo", role=ROLE_SUPERVISOR, dept="Produksi", password="horensu123", color="#14B8A6"),
    dict(username="joko", email="joko@siglaboratory.co.id", full_name="Joko Prasetyo", role=ROLE_SENIOR, dept="Produksi", password="horensu123", color="#059669"),
    dict(username="dedi", email="dedi@siglaboratory.co.id", full_name="Dedi Kurniawan", role=ROLE_SENIOR, dept="Maintenance", password="horensu123", color="#8B5CF6"),
    dict(username="wati", email="wati@siglaboratory.co.id", full_name="Wati Setiawati", role=ROLE_USER, dept="Gudang", password="horensu123", color="#F43F5E"),
]


def reset_db():
    db.drop_all()
    db.create_all()


def get_or_create_lookup():
    dep_map = {}
    for name, code in DEPARTMENTS:
        dep = Department.query.filter_by(name=name).first()
        if not dep:
            dep = Department(name=name, code=code)
            db.session.add(dep)
            db.session.flush()
        dep_map[name] = dep

    cat_map = {}
    for name in CATEGORIES:
        cat = Category.query.filter_by(name=name).first()
        if not cat:
            cat = Category(name=name, reference=CATEGORY_REFERENCES.get(name))
            db.session.add(cat)
            db.session.flush()
        elif not cat.reference:
            cat.reference = CATEGORY_REFERENCES.get(name)
        cat_map[name] = cat

    pr_map = {}
    for code, label, desc, color, level, sla in PRIORITIES:
        pr = Priority.query.filter_by(code=code).first()
        if not pr:
            pr = Priority(code=code, label=label, description=desc, color=color, level=level, sla_hours=sla)
            db.session.add(pr)
            db.session.flush()
        pr_map[code] = pr

    st_map = {}
    for code, label, color, order, terminal in STATUSES:
        st = Status.query.filter_by(code=code).first()
        if not st:
            st = Status(code=code, label=label, color=color, order=order, is_terminal=terminal)
            db.session.add(st)
            db.session.flush()
        st_map[code] = st

    db.session.commit()
    return dep_map, cat_map, pr_map, st_map


def get_or_create_users(dep_map):
    user_map = {}
    for u in USERS:
        existing = User.query.filter_by(username=u["username"]).first()
        if existing:
            user_map[u["username"]] = existing
            continue
        user = User(
            username=u["username"], email=u["email"], full_name=u["full_name"],
            role=u["role"], department_id=dep_map[u["dept"]].id, avatar_color=u["color"],
        )
        user.set_password(u["password"])
        db.session.add(user)
        db.session.flush()
        user_map[u["username"]] = user
    db.session.commit()
    return user_map


def make_problem(code_seq, title, description, impact, area, dep, cat, pr_code, status_code,
                  reporter, pic, dep_map, cat_map, pr_map, st_map, days_ago=0, resolved=False,
                  closed=False, consultation=None, actions=None, comments=None):
    year = datetime.utcnow().year
    code = f"PRB-{year}-{code_seq:05d}"
    if ProblemCard.query.filter_by(code=code).first():
        return None

    created_at = datetime.utcnow() - timedelta(days=days_ago, hours=2)
    problem = ProblemCard(
        code=code, title=title, description=description, impact=impact, area_process=area,
        date_discovered=created_at, department_id=dep_map[dep].id, category_id=cat_map[cat].id,
        priority_id=pr_map[pr_code].id, status_id=st_map[status_code].id,
        reporter_id=reporter.id, pic_id=pic.id if pic else None,
        created_at=created_at, updated_at=created_at,
    )
    db.session.add(problem)
    db.session.flush()

    log = ActivityLog(problem_id=problem.id, user_id=reporter.id, action="Membuat Problem Card",
                       detail=title, created_at=created_at)
    db.session.add(log)

    if pic:
        db.session.add(Communication(problem_id=problem.id, recipient_user_id=pic.id,
                                      notified_by_id=reporter.id, notified_at=created_at + timedelta(minutes=5)))
        db.session.add(ActivityLog(problem_id=problem.id, user_id=reporter.id, action="Menginformasikan pihak terkait",
                                    detail=pic.full_name, created_at=created_at + timedelta(minutes=5)))
        db.session.add(ActivityLog(problem_id=problem.id, user_id=reporter.id, action="Menugaskan PIC",
                                    detail=f"-> {pic.full_name}", created_at=created_at + timedelta(minutes=10)))

    if consultation:
        problem.consultation_requested = True
        c = Consultation(problem_id=problem.id, question=consultation["question"],
                          decision_needed=consultation.get("decision_needed", ""),
                          suggested_solution=consultation.get("suggested_solution", ""),
                          requested_by_id=reporter.id, requested_at=created_at + timedelta(minutes=15),
                          status="DECIDED" if consultation.get("decision") else "OPEN")
        db.session.add(c)
        db.session.flush()
        if consultation.get("decision"):
            db.session.add(Decision(consultation_id=c.id, decision_text=consultation["decision"],
                                     decided_by_id=consultation["decided_by"].id,
                                     decided_at=created_at + timedelta(minutes=45)))

    if actions:
        for a in actions:
            act = Action(problem_id=problem.id, description=a["description"], pic_id=a["pic"].id,
                         status=a.get("status", "TODO"), due_date=created_at + timedelta(days=1),
                         created_by_id=reporter.id, created_at=created_at + timedelta(minutes=50),
                         notes=a.get("notes"),
                         completed_at=created_at + timedelta(hours=2) if a.get("status") == "COMPLETED" else None)
            db.session.add(act)

    if comments:
        for c in comments:
            db.session.add(Comment(problem_id=problem.id, user_id=c["user"].id, body=c["body"],
                                    created_at=created_at + timedelta(hours=1)))

    if resolved:
        resolver = pic or reporter
        problem.resolution_description = "Masalah telah ditindaklanjuti dan dipastikan kembali normal."
        problem.resolved_at = created_at + timedelta(hours=3)
        problem.resolved_by_id = resolver.id
        problem.resolved_by_role = resolver.role
        db.session.add(ActivityLog(problem_id=problem.id, user_id=resolver.id, action="Menandai Resolved",
                                    detail=problem.resolution_description, created_at=problem.resolved_at))
        # One tier above has already ticked "mengetahui", the rest still pending.
        for acker in ProblemCard.query.get(problem.id).required_acknowledgers()[:1]:
            db.session.add(Acknowledgement(
                problem_id=problem.id, user_id=acker.id, role_at_time=acker.role,
                acknowledged_at=problem.resolved_at + timedelta(minutes=30),
            ))
            db.session.add(ActivityLog(
                problem_id=problem.id, user_id=acker.id, action="Mengetahui penyelesaian",
                detail=f"Mengetahui dan telah diselesaikan oleh {resolver.full_name} ({resolver.role_label}).",
                created_at=problem.resolved_at + timedelta(minutes=30),
            ))
    if closed:
        problem.closed_at = created_at + timedelta(hours=6)
        problem.closed_by_id = reporter.id
        problem.closing_comment = "Sudah diverifikasi, tidak terjadi lagi."
        db.session.add(ActivityLog(problem_id=problem.id, user_id=reporter.id, action="Menutup Problem (Closed)",
                                    detail=problem.closing_comment, created_at=problem.closed_at))

    return problem


def seed():
    dep_map, cat_map, pr_map, st_map = get_or_create_lookup()
    users = get_or_create_users(dep_map)

    farhan, siti, budi, rina, agus, dedi, wati = (
        users["farhan"], users["siti"], users["budi"], users["rina"], users["agus"], users["dedi"], users["wati"]
    )
    hendra, maya, joko = users["hendra"], users["maya"], users["joko"]

    if ProblemCard.query.count() > 0:
        print("Problem cards already exist, skipping problem seed.")
        db.session.commit()
        return

    make_problem(
        125, "HPLC-02 tidak dapat digunakan",
        "HPLC-02 menunjukkan error tekanan tinggi saat digunakan untuk analisis sampel rutin.",
        "Analisis sampel tertunda, berpotensi mempengaruhi jadwal rilis batch.",
        "Lab Instrumen", "Quality Control", "Instrument", "HIGH", "WAITING_DECISION",
        reporter=farhan, pic=budi, dep_map=dep_map, cat_map=cat_map, pr_map=pr_map, st_map=st_map,
        days_ago=0,
        consultation={
            "question": "Apakah kita perlu memindahkan analisis sampel ke HPLC-01 sementara HPLC-02 diperbaiki?",
            "decision_needed": "Persetujuan pemindahan jalur analisis",
            "suggested_solution": "Pindahkan sampel prioritas tinggi ke HPLC-01",
        },
    )

    make_problem(
        124, "Stock reagent hampir habis",
        "Stok reagent mobile phase acetonitrile tersisa kurang dari 10% dari kebutuhan mingguan.",
        "Berisiko menghentikan analisis rutin jika tidak segera diisi ulang.",
        "Gudang Reagent", "Quality Control", "Material", "MEDIUM", "IN_PROGRESS",
        reporter=siti, pic=budi, dep_map=dep_map, cat_map=cat_map, pr_map=pr_map, st_map=st_map,
        days_ago=1,
        actions=[
            {"description": "Cek stok gudang pusat & ajukan pembelian darurat", "pic": budi, "status": "IN_PROGRESS"},
        ],
    )

    make_problem(
        123, "Timbangan analitik tidak stabil",
        "Timbangan AB-204 menunjukkan pembacaan yang berubah-ubah saat kalibrasi harian.",
        "Hasil penimbangan sampel berpotensi tidak akurat.",
        "Lab Kimia", "Quality Control", "Instrument", "LOW", "RESOLVED",
        reporter=rina, pic=dedi, dep_map=dep_map, cat_map=cat_map, pr_map=pr_map, st_map=st_map,
        days_ago=5,
        actions=[{"description": "Kalibrasi ulang & pindahkan ke meja anti-getar", "pic": dedi, "status": "COMPLETED"}],
        resolved=True,
    )

    make_problem(
        122, "Kalibrasi instrumen melewati jadwal",
        "Jadwal kalibrasi tahunan untuk timbangan AB-301 sudah lewat 5 hari.",
        "Data pengukuran tidak dapat digunakan untuk keperluan rilis sampai kalibrasi selesai.",
        "Lab Instrumen", "Quality Control", "Instrument", "HIGH", "IN_PROGRESS",
        reporter=budi, pic=dedi, dep_map=dep_map, cat_map=cat_map, pr_map=pr_map, st_map=st_map,
        days_ago=2,
        actions=[{"description": "Jadwalkan ulang dengan vendor kalibrasi eksternal", "pic": dedi, "status": "TODO"}],
    )

    make_problem(
        121, "Label kemasan tidak terbaca oleh scanner",
        "Barcode pada kemasan batch terbaru tidak dapat dibaca oleh scanner gudang.",
        "Proses pengeluaran barang dari gudang tertunda.",
        "Gudang Produk Jadi", "Gudang", "Process", "MEDIUM", "CLOSED",
        reporter=wati, pic=agus, dep_map=dep_map, cat_map=cat_map, pr_map=pr_map, st_map=st_map,
        days_ago=10,
        actions=[{"description": "Cetak ulang label dengan resolusi lebih tinggi", "pic": agus, "status": "COMPLETED"}],
        resolved=True, closed=True,
    )

    make_problem(
        120, "Kebocoran kecil pada pipa utility line produksi",
        "Ditemukan rembesan air pada sambungan pipa utility dekat mesin filling.",
        "Berpotensi mengganggu kebersihan area produksi bila dibiarkan.",
        "Ruang Produksi 2", "Produksi", "Safety", "CRITICAL", "WAITING_DECISION",
        reporter=rina, pic=None, dep_map=dep_map, cat_map=cat_map, pr_map=pr_map, st_map=st_map,
        days_ago=0,
        consultation={
            "question": "Apakah lini produksi perlu dihentikan sementara untuk perbaikan pipa?",
            "decision_needed": "Keputusan penghentian sementara lini produksi",
        },
    )

    db.session.commit()
    print("Seed data created.")


if __name__ == "__main__":
    with app.app_context():
        if "--reset" in sys.argv:
            reset_db()
        seed()
        print("Done. Demo accounts (password shown, change after first login):")
        for u in USERS:
            print(f"  - {u['username']} / {u['password']}  ({u['role']}, {u['dept']})")
