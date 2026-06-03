import pytest

# Only run if SQLAlchemy is installed (optional dependency)
pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.realtime import job_automation_models as jam


def test_job_models_basic_smoke():
    # Basic import and enum checks
    assert jam.ConsentChannelEnum.UI.value == "ui"
    assert hasattr(jam, "Candidate")

    # Create tables in sqlite memory and insert a Candidate
    engine = create_engine("sqlite:///:memory:")
    jam.create_all_tables(engine)
    Session = sessionmaker(bind=engine)
    sess = Session()

    c = jam.Candidate(candidate_id="c_bridge", first_name="B", last_name="R", email="b@r.com", created_by="u1")
    sess.add(c)
    sess.commit()

    row = sess.query(jam.Candidate).first()
    assert row.email == "b@r.com"
