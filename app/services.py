"""Shared business logic used by both the UI routes and the JSON API."""

from datetime import datetime, timedelta

from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from . import models

BOOKING_STEP_MINUTES = 5


class ServiceError(Exception):
    """Raised when an operation fails a business rule (409-ish)."""


def _now() -> datetime:
    return datetime.utcnow()


def _as_naive_utc(dt: datetime) -> datetime:
    """Drop tz info, converting to UTC first if aware. DB stores naive UTC."""
    if dt.tzinfo is not None:
        offset = dt.utcoffset()
        if offset is not None:
            dt = dt - offset
        dt = dt.replace(tzinfo=None)
    return dt


def _round_to_step(dt: datetime, *, up: bool = False) -> datetime:
    """Round a datetime to the nearest BOOKING_STEP_MINUTES boundary.
    Default is floor; pass up=True for ceil. Seconds/microseconds are dropped.
    """
    dt = dt.replace(second=0, microsecond=0)
    rem = dt.minute % BOOKING_STEP_MINUTES
    if rem == 0:
        return dt
    if up:
        return dt + timedelta(minutes=BOOKING_STEP_MINUTES - rem)
    return dt - timedelta(minutes=rem)


def current_location(db: Session, car_id: int) -> Optional[models.CarLocation]:
    stmt = (
        select(models.CarLocation)
        .where(models.CarLocation.car_id == car_id, models.CarLocation.left_at.is_(None))
        .order_by(models.CarLocation.arrived_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def move_car(
    db: Session, car_id: int, space_id: Optional[int], notes: str = ""
) -> models.CarLocation:
    car = db.get(models.Car, car_id)
    if car is None:
        raise ServiceError(f"Car {car_id} not found")
    if space_id is not None and db.get(models.Space, space_id) is None:
        raise ServiceError(f"Space {space_id} not found")

    now = _now()
    open_row = current_location(db, car_id)
    if open_row is not None:
        if open_row.space_id == space_id:
            return open_row  # already there, idempotent
        open_row.left_at = now

    new_row = models.CarLocation(
        car_id=car_id, space_id=space_id, arrived_at=now, notes=notes
    )
    db.add(new_row)
    db.commit()
    db.refresh(new_row)
    return new_row


def find_booking_conflict(
    db: Session,
    space_id: int,
    start_at: datetime,
    end_at: datetime,
    exclude_id: Optional[int] = None,
) -> Optional[models.Booking]:
    """Return the first active booking on this space overlapping [start_at, end_at), if any."""
    stmt = select(models.Booking).where(
        models.Booking.space_id == space_id,
        models.Booking.status == "active",
        and_(models.Booking.start_at < end_at, models.Booking.end_at > start_at),
    )
    if exclude_id is not None:
        stmt = stmt.where(models.Booking.id != exclude_id)
    return db.execute(stmt.limit(1)).scalar_one_or_none()


def next_available_slot(
    db: Session,
    space_id: int,
    duration_minutes: int,
    after: Optional[datetime] = None,
    horizon_days: int = 30,
) -> Optional[datetime]:
    """First gap >= duration on this space at/after `after`. None if none within horizon."""
    if duration_minutes <= 0:
        raise ServiceError("Total test duration must be greater than zero")
    cur = _round_to_step(_as_naive_utc(after or _now()), up=True)
    horizon = cur + timedelta(days=horizon_days)
    duration = timedelta(minutes=duration_minutes)

    stmt = (
        select(models.Booking)
        .where(
            models.Booking.space_id == space_id,
            models.Booking.status == "active",
            models.Booking.end_at > cur,
            models.Booking.start_at < horizon,
        )
        .order_by(models.Booking.start_at)
    )
    for b in db.execute(stmt).scalars():
        if b.start_at - cur >= duration:
            return cur
        if b.end_at > cur:
            cur = _round_to_step(b.end_at, up=True)
    if horizon - cur >= duration:
        return cur
    return None


def create_booking(
    db: Session,
    *,
    car_id: int,
    space_id: int,
    start_at: datetime,
    end_at: datetime,
    purpose: str = "",
    notes: str = "",
    created_by: str = "",
    test_type_id: Optional[int] = None,
    setup_minutes: int = 0,
    test_minutes: int = 0,
    analysis_minutes: int = 0,
    down_minutes: int = 0,

) -> models.Booking:
    start_at = _round_to_step(_as_naive_utc(start_at))
    end_at = _round_to_step(_as_naive_utc(end_at), up=True)
    if end_at <= start_at:
        raise ServiceError("End time must be after start time")
    if db.get(models.Car, car_id) is None:
        raise ServiceError(f"Car {car_id} not found")
    if db.get(models.Space, space_id) is None:
        raise ServiceError(f"Space {space_id} not found")

    conflict = find_booking_conflict(db, space_id, start_at, end_at)
    if conflict is not None:
        raise ServiceError(
            f"Space already booked from {conflict.start_at:%Y-%m-%d %H:%M} "
            f"to {conflict.end_at:%Y-%m-%d %H:%M}"
        )

    booking = models.Booking(
        car_id=car_id,
        space_id=space_id,
        start_at=start_at,
        end_at=end_at,
        purpose=purpose,
        notes=notes,
        created_by=created_by,
        test_type_id=test_type_id,
        setup_minutes=setup_minutes,
        test_minutes=test_minutes,
        analysis_minutes=analysis_minutes,
        down_minutes=down_minutes,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def update_booking(
    db: Session,
    booking_id: int,
    *,
    car_id: int,
    space_id: int,
    start_at: datetime,
    end_at: datetime,
    purpose: str = "",
    notes: str = "",
    created_by: str = "",
    test_type_id: Optional[int] = None,
    setup_minutes: int = 0,
    test_minutes: int = 0,
    analysis_minutes: int = 0,
    down_minutes: int = 0,
) -> models.Booking:
    booking = db.get(models.Booking, booking_id)
    if booking is None:
        raise ServiceError(f"Booking {booking_id} not found")
    start_at = _round_to_step(_as_naive_utc(start_at))
    end_at = _round_to_step(_as_naive_utc(end_at), up=True)
    if end_at <= start_at:
        raise ServiceError("End time must be after start time")
    if db.get(models.Car, car_id) is None:
        raise ServiceError(f"Car {car_id} not found")
    if db.get(models.Space, space_id) is None:
        raise ServiceError(f"Space {space_id} not found")

    conflict = find_booking_conflict(
        db, space_id, start_at, end_at, exclude_id=booking_id
    )
    if conflict is not None:
        raise ServiceError(
            f"Space already booked from {conflict.start_at:%Y-%m-%d %H:%M} "
            f"to {conflict.end_at:%Y-%m-%d %H:%M}"
        )
    
    booking.car_id = car_id
    booking.space_id = space_id
    booking.start_at = start_at
    booking.end_at = end_at
    booking.purpose = purpose
    booking.notes = notes
    booking.created_by = created_by
    booking.test_type_id = test_type_id
    booking.setup_minutes = setup_minutes
    booking.test_minutes = test_minutes
    booking.analysis_minutes = analysis_minutes
    booking.down_minutes = down_minutes
    db.commit()
    db.refresh(booking)
    return booking


def cancel_booking(db: Session, booking_id: int) -> models.Booking:
    booking = db.get(models.Booking, booking_id)
    if booking is None:
        raise ServiceError(f"Booking {booking_id} not found")
    booking.status = "cancelled"
    db.commit()
    db.refresh(booking)
    return booking


def cars_with_locations(db: Session, include_archived: bool = False):
    """Return (Car, current CarLocation or None) pairs."""
    stmt = select(models.Car).order_by(models.Car.reg)
    if not include_archived:
        stmt = stmt.where(models.Car.archived.is_(False))
    cars = list(db.execute(stmt).scalars())

    if not cars:
        return []

    loc_stmt = select(models.CarLocation).where(
        models.CarLocation.car_id.in_([c.id for c in cars]),
        models.CarLocation.left_at.is_(None),
    )
    by_car: dict[int, models.CarLocation] = {
        row.car_id: row for row in db.execute(loc_stmt).scalars()
        
    }
    return [(car, by_car.get(car.id)) for car in cars]


def cars_in_space(db: Session, space_id: int) -> list[models.Car]:
    stmt = (
        select(models.Car)
        .join(models.CarLocation, models.CarLocation.car_id == models.Car.id)
        .where(
            models.CarLocation.space_id == space_id,
            models.CarLocation.left_at.is_(None),
            models.Car.archived.is_(False),
        )
        .order_by(models.Car.reg)
    )
    return list(db.execute(stmt).scalars())


def cars_offsite(db: Session) -> list[models.Car]:
    """Cars whose latest location has space_id IS NULL, or who have no location rows."""
    all_cars = list(
        db.execute(
            select(models.Car).where(models.Car.archived.is_(False)).order_by(models.Car.reg)
        ).scalars()
    )
    if not all_cars:
        return []
    loc_stmt = select(models.CarLocation).where(
        models.CarLocation.car_id.in_([c.id for c in all_cars]),
        models.CarLocation.left_at.is_(None),
    )
    by_car = {row.car_id: row for row in db.execute(loc_stmt).scalars()}
    return [c for c in all_cars if by_car.get(c.id) is None or by_car[c.id].space_id is None]