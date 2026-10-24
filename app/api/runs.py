
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.run import RunResponse
from app.services.run_service import create_run, get_run
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.run import RunStatusUpdate, RunResponse
from app.services.run_service import transition_run

router = APIRouter(prefix="/runs", tags=["Runs"])


@router.post(
    "",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_run_endpoint(db: Session = Depends(get_db)):
    return create_run(db)


@router.get("/{run_id}", response_model=RunResponse)
def get_run_endpoint(
    run_id: UUID,
    db: Session = Depends(get_db),
):
    run = get_run(db, run_id)

    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Run not found",
        )

    return run

@router.patch("/runs/{run_id}/status", response_model=RunResponse)
def update_run_status(
    run_id: UUID,
    request: RunStatusUpdate,
    db: Session = Depends(get_db),
):
    try:
        return transition_run(db, run_id, request.status)
    except ValueError as exc:
        message = str(exc)

        if message == "Run not found":
            raise HTTPException(status_code=404, detail=message)

        raise HTTPException(status_code=409, detail=message)
