"""Lightweight, idempotent schema/data migrations.

This project has no Alembic setup: `db.create_all()` creates missing tables but
never alters existing ones. These steps close that gap so an existing
instance/horensu.db keeps working after a model change. Every step checks the
current shape first, so running them repeatedly is safe.
"""
from sqlalchemy import inspect, text

from app.extensions import db


# Categories carry a "reference" line so a reporter can tell at a glance what
# belongs where. Wording follows how testing journals describe each area.
CATEGORY_REFERENCES = {
    "Instrument": (
        "Instrumen uji (HPLC, GC, GC-MS, LC-MS/MS, AAS, ICP-OES, Spektrofotometer UV-Vis/FTIR), "
        "peralatan penunjang pengujian (timbangan analitik, pH meter, oven, inkubator, water bath, sonikator, "
        "sentrifus, mikropipet), bagian sistem kromatografi (kolom, detektor, pompa, autosampler, injektor)"
    ),
    "Material": (
        "Reagen dan pelarut (pro analysis, HPLC grade), baku pembanding dan standar (CRM, working standard), "
        "gas kromatografi (helium, nitrogen, hidrogen, udara zero), media dan kultur, "
        "consumable (vial, septa, filter membran, kolom, tip mikropipet), air suling atau purified water"
    ),
    "Process": (
        "Preparasi sampel (penimbangan, ekstraksi, pengenceran, filtrasi, derivatisasi), "
        "kondisi analisis (gradien, laju alir, suhu kolom, panjang gelombang), "
        "penerimaan dan penanganan sampel, uji kesesuaian sistem (system suitability), "
        "verifikasi dan validasi metode, pengolahan data dan perhitungan hasil"
    ),
    "Documentation": (
        "Jurnal atau logbook pengujian, worksheet dan raw data, sertifikat analisis (CoA), "
        "protokol dan laporan validasi, SOP dan instruksi kerja, "
        "rekaman kalibrasi dan kualifikasi (IQ/OQ/PQ), pencatatan penyimpangan (deviasi) dan CAPA"
    ),
    "Safety": (
        "Penanganan bahan kimia berbahaya (B3) dan MSDS, tumpahan atau paparan bahan kimia, "
        "alat pelindung diri (APD), fume hood dan ventilasi, limbah laboratorium B3, "
        "keselamatan listrik dan gas bertekanan, kondisi darurat (kebakaran, eye wash, safety shower)"
    ),
    "Kalibrasi & Kualifikasi": (
        "Kalibrasi internal dan eksternal, jadwal kalibrasi terlewat, sertifikat kalibrasi, "
        "kualifikasi instrumen (IQ/OQ/PQ), verifikasi harian instrumen, "
        "ketertelusuran standar, penyimpangan hasil kalibrasi"
    ),
    "Utility & Lingkungan": (
        "Listrik dan UPS/genset, pasokan gas, air (aquadest, purified water), "
        "suhu dan kelembapan ruang, tekanan dan aliran udara, sistem pendingin (chiller, AC), "
        "kebersihan dan kondisi ruang pengujian"
    ),
}

# Categories that did not exist before but are standard headings in testing
# journals. Only inserted when the table already holds the original seed set.
EXTRA_CATEGORIES = ["Kalibrasi & Kualifikasi", "Utility & Lingkungan"]

# Role rename: the PIC tier became "Senior" when the ladder was split out.
ROLE_RENAMES = {"pic": "senior"}


def _columns(table):
    inspector = inspect(db.engine)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def _add_column(table, column, ddl_type):
    if table not in inspect(db.engine).get_table_names():
        return False
    if column in _columns(table):
        return False
    db.session.execute(text('ALTER TABLE %s ADD COLUMN %s %s' % (table, column, ddl_type)))
    db.session.commit()
    return True


def _widen_activity_logs():
    """Make activity_logs able to record changes outside a problem card.

    SQLite cannot drop a NOT NULL constraint in place, so the table is rebuilt:
    create the new shape, copy every row across, swap the names. Wrapped in one
    transaction, so a failure leaves the original table untouched.
    """
    inspector = inspect(db.engine)
    if "activity_logs" not in inspector.get_table_names():
        return False
    cols = {c["name"]: c for c in inspector.get_columns("activity_logs")}
    already_nullable = cols.get("problem_id", {}).get("nullable", False)
    if already_nullable and "entity_type" in cols:
        return False

    db.session.execute(text("DROP TABLE IF EXISTS activity_logs__new"))
    db.session.execute(text("""
        CREATE TABLE activity_logs__new (
            id INTEGER NOT NULL PRIMARY KEY,
            problem_id INTEGER REFERENCES problem_cards (id),
            user_id INTEGER REFERENCES users (id),
            entity_type VARCHAR(30),
            entity_id INTEGER,
            entity_label VARCHAR(160),
            action VARCHAR(120) NOT NULL,
            detail TEXT,
            ip_address VARCHAR(45),
            created_at DATETIME
        )
    """))
    db.session.execute(text("""
        INSERT INTO activity_logs__new
            (id, problem_id, user_id, entity_type, entity_id, entity_label, action, detail, created_at)
        SELECT id, problem_id, user_id, 'problem', problem_id, NULL, action, detail, created_at
        FROM activity_logs
    """))
    db.session.execute(text("DROP TABLE activity_logs"))
    db.session.execute(text("ALTER TABLE activity_logs__new RENAME TO activity_logs"))
    db.session.execute(text("CREATE INDEX ix_activity_logs_problem_id ON activity_logs (problem_id)"))
    db.session.execute(text("CREATE INDEX ix_activity_logs_entity_type ON activity_logs (entity_type)"))
    db.session.execute(text("CREATE INDEX ix_activity_logs_created_at ON activity_logs (created_at)"))
    db.session.commit()
    return True


def _rename_app(done):
    """HORENSU -> HORENSO across stored branding text."""
    from app.models import ThemeSetting

    changed = 0
    for theme in ThemeSetting.query.all():
        for field in ("app_name", "company_name", "welcome_message", "login_tagline", "footer_text"):
            value = getattr(theme, field, None)
            if value and "HORENSU" in value:
                setattr(theme, field, value.replace("HORENSU", "HORENSO"))
                changed += 1
    if changed:
        db.session.commit()
        done.append("%d branding field(s) renamed to HORENSO" % changed)


def apply_pending():
    """Run every migration step. Returns a list of human-readable changes."""
    done = []

    # 1. New columns on existing tables.
    if _add_column("problem_categories", "reference", "TEXT"):
        done.append("problem_categories.reference added")
    if _add_column("problem_cards", "resolved_by_role", "VARCHAR(20)"):
        done.append("problem_cards.resolved_by_role added")
    if _add_column("theme_settings", "logo_filename", "VARCHAR(255)"):
        done.append("theme_settings.logo_filename added")
    if _add_column("theme_settings", "favicon_filename", "VARCHAR(255)"):
        done.append("theme_settings.favicon_filename added")

    # 1b. Audit log now covers every entity, not just problem cards.
    if _widen_activity_logs():
        done.append("activity_logs widened to cover every entity")

    # 2. Rename the PIC role to Senior.
    for old, new in ROLE_RENAMES.items():
        result = db.session.execute(
            text("UPDATE users SET role = :new WHERE role = :old"), {"new": new, "old": old}
        )
        if result.rowcount:
            done.append("%d user(s) moved from role '%s' to '%s'" % (result.rowcount, old, new))
    db.session.commit()

    # 3. Backfill the resolving tier for cards resolved before the column existed.
    from app.models import ProblemCard, User, ROLE_SENIOR

    backfilled = 0
    for problem in ProblemCard.query.filter(
        ProblemCard.resolved_at.isnot(None), ProblemCard.resolved_by_role.is_(None)
    ).all():
        resolver = User.query.get(problem.resolved_by_id) if problem.resolved_by_id else None
        problem.resolved_by_role = resolver.role if resolver else ROLE_SENIOR
        backfilled += 1
    if backfilled:
        db.session.commit()
        done.append("%d resolved card(s) backfilled with a resolving tier" % backfilled)

    # 4. Category references.
    from app.models import Category

    existing = {c.name: c for c in Category.query.all()}
    for name in EXTRA_CATEGORIES:
        if name not in existing and existing:
            category = Category(name=name)
            db.session.add(category)
            existing[name] = category
            done.append("category '%s' added" % name)

    filled = 0
    for name, reference in CATEGORY_REFERENCES.items():
        category = existing.get(name)
        if category is not None and not category.reference:
            category.reference = reference
            filled += 1
    if filled or done:
        db.session.commit()
    if filled:
        done.append("%d category reference(s) filled in" % filled)

    # 5. Product rename.
    _rename_app(done)

    return done
