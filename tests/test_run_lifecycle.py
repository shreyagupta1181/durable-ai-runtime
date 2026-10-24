
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import delete
from app.db.database import SessionLocal
from app.models.event import RunEvent
from app.models.run import Run
from app.models.job import Job
from app.services.run_service import create_run, transition_run


@pytest.fixture
def db():
    session: Session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def run(db):
    created_run = create_run(db)
    yield created_run

    # Clean up test data after each test.
    db.rollback()

    db.query(Job).filter(Job.run_id == created_run.id).delete(
        synchronize_session=False
    )
    db.query(RunEvent).filter(
        RunEvent.run_id == created_run.id
    ).delete(synchronize_session=False)
    db.query(Run).filter(
        Run.id == created_run.id
    ).delete(synchronize_session=False)

    db.commit()


def test_create_run_persists_initial_event(db, run):
    assert run.status == "pending"

    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run.id)
        .order_by(RunEvent.seq)
        .all()
    )

    assert len(events) == 1
    assert events[0].seq == 1
    assert events[0].type == "run_created"
    assert events[0].payload == {"status": "pending"}


def test_valid_transitions_are_persisted(db, run):
    run_id = run.id

    transition_run(db, run_id, "running")
    transition_run(db, run_id, "succeeded")

    db.expire_all()
    saved_run = db.get(Run, run_id)

    assert saved_run.status == "succeeded"

    events = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .order_by(RunEvent.seq)
        .all()
    )

    assert [event.seq for event in events] == [1, 2, 3]
    assert events[1].payload == {
        "from": "pending",
        "to": "running",
    }
    assert events[2].payload == {
        "from": "running",
        "to": "succeeded",
    }


def test_invalid_transition_changes_nothing(db, run):
    run_id = run.id

    with pytest.raises(ValueError, match="Invalid transition"):
        transition_run(db, run_id, "succeeded")

    db.expire_all()
    saved_run = db.get(Run, run_id)

    assert saved_run.status == "pending"

    event_count = (
        db.query(RunEvent)
        .filter(RunEvent.run_id == run_id)
        .count()
    )
    assert event_count == 1


def test_duplicate_event_sequence_is_rejected(db, run):
    duplicate = RunEvent(
        id=uuid.uuid4(),
        run_id=run.id,
        seq=1,
        type="duplicate_test",
        payload={},
        timestamp=datetime.now(timezone.utc),
    )

    db.add(duplicate)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()

    count = (
        db.query(RunEvent)
        .filter(
            RunEvent.run_id == run.id,
            RunEvent.seq == 1,
        )
        .count()
    )
    assert count == 1


def test_event_for_nonexistent_run_is_rejected(db):
    event = RunEvent(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        seq=1,
        type="orphan_test",
        payload={},
        timestamp=datetime.now(timezone.utc),
    )

    db.add(event)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()

def test_create_run_creates_queued_job(db, run):
    job = (
        db.query(Job)
        .filter(Job.run_id == run.id)
        .first()
    )

    assert job is not None
    assert job.status == "queued"
    assert job.attempts == 0
    assert job.max_attempts == 3
    assert job.locked_by is None
    assert job.locked_at is None
