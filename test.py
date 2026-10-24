
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.event import RunEvent
from app.services.run_service import create_run, transition_run


def main():
    db: Session = SessionLocal()

    try:
        # Test 1: Create a fresh run.
        run = create_run(db)
        run_id = run.id
        print("PASS: Run created:", run_id)
        assert run.status == "pending"

        # Test 2: pending -> running.
        run = transition_run(db, run_id, "running")
        assert run.status == "running"
        print("PASS: pending -> running")

        # Test 3: running -> succeeded.
        run = transition_run(db, run_id, "succeeded")
        assert run.status == "succeeded"
        print("PASS: running -> succeeded")

        # Test 4: A terminal state cannot be restarted.
        try:
            transition_run(db, run_id, "running")
            raise AssertionError("Invalid transition was accepted")
        except ValueError:
            print("PASS: succeeded -> running rejected")

        # Test 5: Verify the persisted event history.
        events = (
            db.query(RunEvent)
            .filter(RunEvent.run_id == run_id)
            .order_by(RunEvent.seq)
            .all()
        )

        expected_types = [
            "run_created",
            "run_status_changed",
            "run_status_changed",
        ]

        assert [event.type for event in events] == expected_types
        assert [event.seq for event in events] == [1, 2, 3]
        assert events[1].payload == {
            "from": "pending",
            "to": "running",
        }
        assert events[2].payload == {
            "from": "running",
            "to": "succeeded",
        }

        print("PASS: Event history persisted correctly")
        print("PASS: Event sequence is 1, 2, 3")
        print("\nAll state-machine checks passed!")

    finally:
        db.close()


if __name__ == "__main__":
    main()
