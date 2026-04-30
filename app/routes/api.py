from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status 
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload
from datetime import datetime, timedelta

from .. import models, schemas, services
from ..auth import require_api_key_or_login
from ..db import get_db

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key_or_login)], tags=["api"])


def _car_to_out(db: Session, car: models.Car) -> schemas.CarOut:
    loc = services.current_location(db, car.id)
    space = loc.space if loc is not None else None
    return schemas.CarOut(
        id=car.id,
        reg=car.reg,
        make_model=car.make_model,
        notes=car.notes,
        archived=car.archived,
        current_space_id=(space.id if space else None),
        current_space_name=(space.name if space else None),
    )


# ---------- Buildings & spaces ----------


@router.get(
    "/buildings",
    response_model=list[schemas.BuildingOut],
    summary="List all buildings",
    description="Returns every building (site/office) where cars can be parked. Use this to resolve a building name the user mentioned to its id, or to enumerate sites.",
    operation_id="listBuildings",
)
def list_buildings(db: Session = Depends(get_db)):
    return list(db.execute(select(models.Building).order_by(models.Building.name)).scalars())


@router.get(
    "/spaces",
    response_model=list[schemas.SpaceOut],
    summary="List spaces, optionally filtered by building",
    description="Returns parking/work spaces (general bay, dyno, emissions box, etc.). Pass building_id to list only spaces in one building. Use this to resolve a space name like 'Dyno 1' to its id before booking or moving a car.",
    operation_id="listSpaces",
)
def list_spaces(building_id: Optional[int] = None, db: Session = Depends(get_db)):
    stmt = select(models.Space).order_by(models.Space.name)
    if building_id is not None:
        stmt = stmt.where(models.Space.building_id == building_id)
    return list(db.execute(stmt).scalars())


# ---------- Cars ----------


@router.get(
    "/cars",
    response_model=list[schemas.CarOut],
    summary="List cars with their current location",
    description="Returns every active car and the space it is currently in (or null if off-site). Set include_archived=true to also return retired cars. Use this to find a car by registration plate or to show fleet status.",
    operation_id="listCars",
)
def list_cars(include_archived: bool = False, db: Session = Depends(get_db)):
    stmt = select(models.Car).order_by(models.Car.reg)
    if not include_archived:
        stmt = stmt.where(models.Car.archived.is_(False))
    cars = list(db.execute(stmt).scalars())
    return [_car_to_out(db, c) for c in cars]


@router.get(
    "/cars/{car_id}",
    response_model=schemas.CarOut,
    summary="Get a single car by id",
    description="Returns one car with its current space. Returns 404 if the car does not exist. Resolve the registration to a car_id via listCars first if the user only gave a plate.",
    operation_id="getCar",
)
def get_car(car_id: int, db: Session = Depends(get_db)):
    car = db.get(models.Car, car_id)
    if car is None:
        raise HTTPException(404, "Car not found")
    return _car_to_out(db, car)


@router.post(
    "/cars",
    response_model=schemas.CarOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new car to the fleet",
    description="Registers a new car. The reg is normalised to uppercase and must be unique; returns 409 if a car with that reg already exists. The new car starts off-site (no current space).",
    operation_id="createCar",
)
def create_car(payload: schemas.CarIn, db: Session = Depends(get_db)):
    reg_clean = payload.reg.strip().upper()
    existing = db.execute(
        select(models.Car).where(models.Car.reg == reg_clean)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"Car {reg_clean} already exists")
    car = models.Car(reg=reg_clean, make_model=payload.make_model, notes=payload.notes)
    db.add(car)
    db.commit()
    db.refresh(car)
    return _car_to_out(db, car)


@router.post(
    "/cars/{car_id}/move",
    response_model=schemas.CarOut,
    summary="Move a car to a space, or off-site",
    description="Records that a car has been physically moved into a space. Pass space_id=null to mark the car as off-site. The previous location is preserved in movement history. Returns 400 if the space does not exist or the car is archived.",
    operation_id="moveCar",
)
def move_car(car_id: int, payload: schemas.MoveIn, db: Session = Depends(get_db)):
    try:
        services.move_car(db, car_id, payload.space_id, notes=payload.notes)
    except services.ServiceError as exc:
        raise HTTPException(400, str(exc))
    return _car_to_out(db, db.get(models.Car, car_id))


# ---------- Bookings ----------


@router.get(
    "/bookings",
    response_model=list[schemas.BookingOut],
    summary="List bookings, optionally filtered",
    description="Returns bookings ordered by start time. By default only active (not cancelled) bookings are returned; set active_only=false to include cancelled ones. Filter by car_id or space_id to check a specific car's schedule or a space's availability.",
    operation_id="listBookings",
)
def list_bookings(
    active_only: bool = True,
    car_id: Optional[int] = None,
    space_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    stmt = select(models.Booking).order_by(models.Booking.start_at)
    if active_only:
        stmt = stmt.where(models.Booking.status == "active")
    if car_id is not None:
        stmt = stmt.where(models.Booking.car_id == car_id)
    if space_id is not None:
        stmt = stmt.where(models.Booking.space_id == space_id)
    return list(db.execute(stmt).scalars())


@router.post(
    "/bookings",
    response_model=schemas.BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Reserve a space for a car for a time window",
    description="Creates a booking that reserves a space for a car between start_at and end_at (ISO 8601 timestamps). Returns 409 if the space is already booked for any overlapping window. Resolve car and space ids via listCars / listSpaces first.",
    operation_id="createBooking",
)
def create_booking(payload: schemas.BookingIn, db: Session = Depends(get_db)):
    try:
        booking = services.create_booking(
            db,
            car_id=payload.car_id,
            space_id=payload.space_id,
            start_at=payload.start_at,
            end_at=payload.end_at,
            purpose=payload.purpose,
            notes=payload.notes,
            created_by=payload.created_by,
            test_type_id=payload.test_type_id,
            setup_minutes=payload.setup_minutes,
            test_minutes=payload.test_minutes,
            analysis_minutes=payload.analysis_minutes,
            down_minutes=payload.down_minutes,
        )
    except services.ServiceError as exc:
        raise HTTPException(409, str(exc))
    return booking


@router.post(
    "/bookings/{booking_id}/cancel",
    response_model=schemas.BookingOut,
    summary="Cancel an existing booking",
    description="Marks a booking as cancelled, freeing the space for that window. Returns 404 if the booking id does not exist. Cancelled bookings are still visible via listBookings with active_only=false.",
    operation_id="cancelBooking",
)
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    try:
        return services.cancel_booking(db, booking_id)
    except services.ServiceError as exc:
        raise HTTPException(404, str(exc))
    
    # ---------- Test types ----------


@router.get(
    "/test-types",
    response_model=list[schemas.TestTypeOut],
    summary="List test types (booking templates)",
    description="Returns every configured test type with its phase durations. By default archived templates are hidden; set include_archived=true to also return them. Filter by space_kind to find tests valid for a given bed kind (e.g. 'dyno', 'emissions').",
    operation_id="listTestTypes",
)
def list_test_types(
    include_archived: bool = False,
    space_kind: Optional[str] = None,
    db: Session = Depends(get_db),
):
    stmt = select(models.TestType).order_by(models.TestType.name)
    if not include_archived:
        stmt = stmt.where(models.TestType.archived.is_(False))
    if space_kind:
        # Empty space_kind on a TestType means 'any', so include those too
        stmt = stmt.where(
            (models.TestType.space_kind == space_kind) | (models.TestType.space_kind == "")
        )
    rows = list(db.execute(stmt).scalars())
    return [
        schemas.TestTypeOut.model_validate(
            {**r.__dict__, "total_minutes": r.total_minutes}
        )
        for r in rows
    ]


@router.post(
    "/test-types",
    response_model=schemas.TestTypeOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a test type",
    operation_id="createTestType",
)
def create_test_type(payload: schemas.TestTypeIn, db: Session = Depends(get_db)):
    existing = db.execute(
        select(models.TestType).where(models.TestType.name == payload.name)
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(409, f"Test type {payload.name!r} already exists")
    if payload.space_kind and payload.space_kind not in models.SPACE_KINDS:
        raise HTTPException(400, f"Unknown space_kind {payload.space_kind!r}")
    tt = models.TestType(**payload.model_dump())
    db.add(tt)
    db.commit()
    db.refresh(tt)
    return schemas.TestTypeOut.model_validate(
        {**tt.__dict__, "total_minutes": tt.total_minutes}
    )


@router.post(
    "/test-types/{test_type_id}",
    response_model=schemas.TestTypeOut,
    summary="Update a test type",
    operation_id="updateTestType",
)
def update_test_type(
    test_type_id: int, payload: schemas.TestTypeIn, db: Session = Depends(get_db)
):
    tt = db.get(models.TestType, test_type_id)
    if tt is None:
        raise HTTPException(404, "Test type not found")
    if payload.space_kind and payload.space_kind not in models.SPACE_KINDS:
        raise HTTPException(400, f"Unknown space_kind {payload.space_kind!r}")
    for k, v in payload.model_dump().items():
        setattr(tt, k, v)
    db.commit()
    db.refresh(tt)
    return schemas.TestTypeOut.model_validate(
        {**tt.__dict__, "total_minutes": tt.total_minutes}
    )


@router.post(
    "/test-types/{test_type_id}/delete",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive a test type (soft delete)",
    operation_id="archiveTestType",
)
def archive_test_type(test_type_id: int, db: Session = Depends(get_db)):
    tt = db.get(models.TestType, test_type_id)
    if tt is None:
        raise HTTPException(404, "Test type not found")
    tt.archived = True
    db.commit()
    return None


# ---------- Next-slot helper ----------


@router.get(
    "/spaces/{space_id}/next-slot",
    summary="Find the next free slot of a given length on a space",
    description="Walks forward from `after` (defaults to now) and returns the earliest start time at which `duration_minutes` is unoccupied on the given space. Returns 404 if no gap is found within the search horizon.",
    operation_id="nextSlot",
)
def next_slot(
    space_id: int,
    duration_minutes: int = Query(gt=0),
    after: Optional[datetime] = None,
    horizon_days: int = 30,
    db: Session = Depends(get_db),
):
    if db.get(models.Space, space_id) is None:
        raise HTTPException(404, "Space not found")
    try:
        start = services.next_available_slot(
            db,
            space_id=space_id,
            duration_minutes=duration_minutes,
            after=after,
            horizon_days=horizon_days,
        )
    except services.ServiceError as exc:
        raise HTTPException(400, str(exc))
    if start is None:
        raise HTTPException(404, f"No free {duration_minutes}-minute slot in {horizon_days} days")
    return {
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(minutes=duration_minutes)).isoformat(),
    }