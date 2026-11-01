
import time
import uuid
import threading

from app.db.database import SessionLocal

from app.services.event_service import append_event
from app.services.agent_service import execute_agent

from app.services.run_service import transition_run

from app.services.job_service import (
    claim_next_job,
    complete_job_and_run,
    handle_job_failure,
    owns_valid_lease,
    recover_expired_jobs,
    renew_job_lease,
)


def heartbeat_loop(
    job_id: uuid.UUID,
    worker_id: str,
    stop_event: threading.Event,
    lease_lost_event: threading.Event,
) -> None:
    """Renew the job lease periodically while processing."""

    while not stop_event.wait(10):

        try:
            with SessionLocal() as db:
                renewed = renew_job_lease(
                    db,
                    job_id,
                    worker_id,
                )

            if not renewed:
                print(
                    f"Heartbeat stopped: lease lost for job {job_id}",
                    flush=True,
                )

                lease_lost_event.set()
                return

            print(
                f"Lease renewed for job {job_id}",
                flush=True,
            )

        except Exception as exc:
            print(
                f"Heartbeat error for job {job_id}: {exc}",
                flush=True,
            )


def process_one_job(worker_id: str = "worker-1") -> bool:
    """Recover expired jobs, then process one queued job."""

    # Step 1: Recover expired jobs and claim the next available job.
    with SessionLocal() as db:

        recovery = recover_expired_jobs(db)

        if recovery["requeued"] or recovery["failed"]:
            print(
                f"Recovered expired jobs: {recovery}",
                flush=True,
            )

        print(
            "Checking for queued jobs...",
            flush=True,
        )

        job = claim_next_job(db, worker_id)

        if job is None:
            print(
                "No queued jobs found.",
                flush=True,
            )
            return False

        job_id = job.id
        run_id = job.run_id

    print(
        f"Claimed job: {job_id}",
        flush=True,
    )

    # Step 2: Start the heartbeat thread.
    heartbeat_stop = threading.Event()
    lease_lost = threading.Event()

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(
            job_id,
            worker_id,
            heartbeat_stop,
            lease_lost,
        ),
        daemon=True,
    )

    heartbeat_thread.start()

    try:

        # Step 3: Transition the run to running.
        with SessionLocal() as db:
            transition_run(
                db,
                run_id,
                "running",
            )

        # Step 4: Record task start and execute the agent.
        with SessionLocal() as db:

            append_event(
                db,
                run_id,
                "task_started",
                {
                    "worker_id": worker_id,
                },
            )

            if lease_lost.is_set():
                raise RuntimeError(
                    "Job lease was lost before agent execution."
                )

            # Execute Gemini agent with the registered tools.
            result = execute_agent(
                db,
                run_id,
            )

            # Record the final task result.
            append_event(
                db,
                run_id,
                "task_completed",
                {
                    "result": {
                        "message": result,
                    },
                },
            )

        # Step 5: Verify lease ownership before completing.
        with SessionLocal() as db:

            if (
                lease_lost.is_set()
                or not owns_valid_lease(
                    db,
                    job_id,
                    worker_id,
                )
            ):
                print(
                    f"Job {job_id}: lease expired or ownership was lost.",
                    flush=True,
                )
                return True

        # Step 6: Complete the job and run atomically.
        with SessionLocal() as db:

            completed = complete_job_and_run(
                db=db,
                job_id=job_id,
                run_id=run_id,
                worker_id=worker_id,
            )

        if not completed:
            print(
                f"Job {job_id}: completion rejected; "
                "lease lost or job changed.",
                flush=True,
            )
            return True

        print(
            f"Job {job_id} and its run completed successfully.",
            flush=True,
        )

        return True

    except Exception as exc:

        print(
            f"Job {job_id} encountered an error: {exc}",
            flush=True,
        )

        try:
            with SessionLocal() as db:

                result_status = handle_job_failure(
                    db=db,
                    job_id=job_id,
                    worker_id=worker_id,
                    error=str(exc),
                )

            if result_status == "queued":
                print(
                    f"Job {job_id} requeued for another attempt.",
                    flush=True,
                )

            elif result_status == "failed":
                print(
                    f"Job {job_id} exhausted its attempts.",
                    flush=True,
                )

            elif result_status == "lease_lost":
                print(
                    f"Job {job_id}: lease lost; "
                    "failure not recorded by this worker.",
                    flush=True,
                )

        except Exception as failure_exc:
            print(
                f"Could not handle failure for job {job_id}: "
                f"{failure_exc}",
                flush=True,
            )

        return True

    finally:

        # Step 7: Stop heartbeat regardless of outcome.
        heartbeat_stop.set()
        heartbeat_thread.join(timeout=2)


def main() -> None:
    """Continuously poll for jobs and recover expired leases."""

    worker_id = f"worker-{uuid.uuid4().hex[:8]}"

    print(
        f"Worker started: {worker_id}",
        flush=True,
    )

    try:
        while True:

            processed = process_one_job(worker_id)

            if not processed:
                time.sleep(1)

    except KeyboardInterrupt:
        print(
            "\nWorker shutdown requested.",
            flush=True,
        )


if __name__ == "__main__":
    main()
