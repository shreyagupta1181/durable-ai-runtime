import pytest

from app.db.database import SessionLocal
from app.models.run import Run
from app.models.event import RunEvent
from app.models.job import Job
from app.services.run_service import create_run


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def run(db):
    created_run = create_run(
        db,
        task="Test task for the durable runtime",
    )

    yield created_run

    # Clean up records created for this test.
    db.rollback()

    db.query(Job).filter(
        Job.run_id == created_run.id
    ).delete(synchronize_session=False)

    db.query(RunEvent).filter(
        RunEvent.run_id == created_run.id
    ).delete(synchronize_session=False)

    db.query(Run).filter(
        Run.id == created_run.id
    ).delete(synchronize_session=False)

    db.commit()