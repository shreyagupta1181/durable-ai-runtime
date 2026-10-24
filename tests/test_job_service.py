from app.models.job import Job
from app.services.job_service import claim_next_job


def test_claim_next_job(db, run):
    job = db.query(Job).filter(Job.run_id == run.id).one()
    expected_job_id = job.id

    # Ensure this job is eligible for claiming.
    job.status = "queued"
    db.commit()

    claimed_job = claim_next_job(db, "worker-1")

    assert claimed_job is not None
    assert claimed_job.id == expected_job_id
    assert claimed_job.status == "running"
    assert claimed_job.locked_by == "worker-1"
    assert claimed_job.locked_at is not None
    assert claimed_job.attempts == 1


def test_claim_returns_none_when_queue_is_empty(db):
    claimed_job = claim_next_job(db, "worker-1")
