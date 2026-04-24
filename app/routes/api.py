from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas, services
from ..auth import require_api_key
from ..db import get_db

router = APIRouter(prefix="/api", dependencies=[Depends(require_api_key)], tags=["api"])


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


@router.get("/buildings", response_model=list[schemas.BuildingOut])
def list_buildings(db: Session = Depends(get_db)):
    return list(db.execute(select(models.Building).order_by(models.Building.name)).scalars())


@router.get("/spaces", response_model=list[schemas.SpaceOut])
def list_spaces(building_id: Optional[int] = None, db: Session = Depends(get_db)):
    stmt = select(models.Space).order_by(models.Space.name)
    if building_id is not None:
        stmt = stmt.where(models.Space.building_id == building_id)
    return list(db.execute(stmt).scalars())


# ---------- Cars ----------


@router.get("/cars", response_model=list[schemas.CarOut])
def list_cars(include_archived: bool = False, db: Session = Depends(get_db)):
    stmt = select(models.Car).order_by(models.Car.reg)
    if not include_archived:
        stmt = stmt.where(models.Car.archived.is_(False))
    cars = list(db.execute(stmt).scalars())
    return [_car_to_out(db, c) for c in cars]


@router.get("/cars/{car_id}", response_model=schemas.CarOut)
def get_car(car_id: int, db: Session = Depends(get_db)):
    car = db.get(models.Car, car_id)
    if car is None:
        raise HTTPException(404, "Car not found")
    return _car_to_out(db, car)


@router.post("/cars", response_model=schemas.CarOut, status_code=status.HTTP_201_CREATED)
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


@router.post("/cars/{car_id}/move", response_model=schemas.CarOut)
def move_car(car_id: int, payload: schemas.MoveIn, db: Session = Depends(get_db)):
    try:
        services.move_car(db, car_id, payload.space_id, notes=payload.notes)
    except services.ServiceError as exc:
        raise HTTPException(400, str(exc))
    return _car_to_out(db, db.get(models.Car, car_id))


# ---------- Bookings ----------


@router.get("/bookings", response_model=list[schemas.BookingOut])
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


@router.post("/bookings", response_model=schemas.BookingOut, status_code=status.HTTP_201_CREATED)
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
        )
    except services.ServiceError as exc:
        raise HTTPException(409, str(exc))
    return booking


@router.post("/bookings/{booking_id}/cancel", response_model=schemas.BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db)):
    try:
        return services.cancel_booking(db, booking_id)
    except services.ServiceError as exc:
        raise HTTPException(404, str(exc))