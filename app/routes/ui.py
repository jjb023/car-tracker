from datetime import datetime, timezone
from itertools import groupby
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .. import models, services
from ..auth import is_logged_in, require_login
from ..config import REPO_ROOT
from ..db import get_db
from ..models import SPACE_KINDS

router = APIRouter(dependencies=[Depends(require_login)])
templates = Jinja2Templates(directory=str(REPO_ROOT / "app" / "templates"))


def _ctx(request: Request, **extra) -> dict:
    return {"logged_in": is_logged_in(request), **extra}


def _parse_local_dt(value: str) -> datetime:
    """<input type="datetime-local"> gives "YYYY-MM-DDTHH:MM" (no TZ). Treat as naive UTC."""
    return datetime.fromisoformat(value)


# ---------- Dashboard ----------


@router.get("/")
def dashboard(request: Request, db: Session = Depends(get_db)):
    buildings = list(
        db.execute(
            select(models.Building)
            .options(selectinload(models.Building.spaces))
            .order_by(models.Building.name)
        ).scalars()
    )

    space_cars: dict[int, list[models.Car]] = {}
    for building in buildings:
        for space in building.spaces:
            space_cars[space.id] = services.cars_in_space(db, space.id)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        _ctx(
            request,
            buildings=buildings,
            space_cars=space_cars,
            offsite_cars=services.cars_offsite(db),
        ),
    )


# ---------- Cars ----------


@router.get("/cars")
def cars_list(request: Request, q: Optional[str] = None, db: Session = Depends(get_db)):
    stmt = select(models.Car).order_by(models.Car.reg)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(models.Car.reg.ilike(like), models.Car.make_model.ilike(like)))
    cars = list(db.execute(stmt).scalars())
    loc_by_car: dict[int, models.CarLocation] = {}
    if cars:
        loc_rows = db.execute(
            select(models.CarLocation)
            .options(selectinload(models.CarLocation.space).selectinload(models.Space.building))
            .where(
                models.CarLocation.car_id.in_([c.id for c in cars]),
                models.CarLocation.left_at.is_(None),
            )
        ).scalars()
        loc_by_car = {loc.car_id: loc for loc in loc_rows}
    pairs = [(c, loc_by_car.get(c.id)) for c in cars]
    return templates.TemplateResponse(
        request, "cars.html", _ctx(request, cars=pairs, q=q)
    )


@router.post("/cars")
def cars_create(
    reg: str = Form(...),
    make_model: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    reg_clean = reg.strip().upper()
    existing = db.execute(select(models.Car).where(models.Car.reg == reg_clean)).scalar_one_or_none()
    if existing is not None:
        return RedirectResponse(
            url=f"/cars/{existing.id}", status_code=status.HTTP_303_SEE_OTHER
        )
    car = models.Car(reg=reg_clean, make_model=make_model.strip(), notes=notes)
    db.add(car)
    db.commit()
    db.refresh(car)
    return RedirectResponse(url=f"/cars/{car.id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/cars/{car_id}")
def car_detail(request: Request, car_id: int, db: Session = Depends(get_db)):
    car = db.execute(
        select(models.Car)
        .options(
            selectinload(models.Car.locations).selectinload(models.CarLocation.space).selectinload(models.Space.building)
        )
        .where(models.Car.id == car_id)
    ).scalar_one_or_none()
    if car is None:
        return RedirectResponse(url="/cars", status_code=status.HTTP_303_SEE_OTHER)
    buildings = list(
        db.execute(
            select(models.Building)
            .options(selectinload(models.Building.spaces))
            .order_by(models.Building.name)
        ).scalars()
    )
    bookings = list(
        db.execute(
            select(models.Booking)
            .options(selectinload(models.Booking.space).selectinload(models.Space.building))
            .where(models.Booking.car_id == car_id)
            .order_by(models.Booking.start_at.desc())
        ).scalars()
    )
    current = next((l for l in car.locations if l.left_at is None), None)
    return templates.TemplateResponse(
        request,
        "car_detail.html",
        _ctx(
            request,
            car=car,
            current_loc=current,
            buildings=buildings,
            bookings=bookings,
            error=None,
        ),
    )


@router.post("/cars/{car_id}")
def car_edit(
    car_id: int,
    reg: str = Form(...),
    make_model: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    car = db.get(models.Car, car_id)
    if car is None:
        return RedirectResponse(url="/cars", status_code=status.HTTP_303_SEE_OTHER)
    car.reg = reg.strip().upper()
    car.make_model = make_model.strip()
    car.notes = notes
    db.commit()
    return RedirectResponse(url=f"/cars/{car_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/cars/{car_id}/archive")
def car_archive(car_id: int, db: Session = Depends(get_db)):
    car = db.get(models.Car, car_id)
    if car is not None:
        car.archived = not car.archived
        db.commit()
    return RedirectResponse(url=f"/cars/{car_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/cars/{car_id}/move")
def car_move(
    car_id: int,
    space_id: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    target: Optional[int] = int(space_id) if space_id.strip() else None
    try:
        services.move_car(db, car_id, target, notes=notes)
    except services.ServiceError:
        pass  # re-render would be nicer; for now just go back
    return RedirectResponse(url=f"/cars/{car_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------- Bookings ----------


@router.get("/bookings")
def bookings_page(request: Request, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    stmt = (
        select(models.Booking)
        .options(
            selectinload(models.Booking.car),
            selectinload(models.Booking.space).selectinload(models.Space.building),
        )
        .order_by(models.Booking.start_at)
    )
    all_bookings = list(db.execute(stmt).scalars())
    upcoming = [b for b in all_bookings if b.status == "active" and b.end_at >= now]
    past = [b for b in all_bookings if not (b.status == "active" and b.end_at >= now)]

    upcoming_by_day = [
        (day, list(items))
        for day, items in groupby(upcoming, key=lambda b: b.start_at.date())
    ]
    cars = list(
        db.execute(
            select(models.Car).where(models.Car.archived.is_(False)).order_by(models.Car.reg)
        ).scalars()
    )
    buildings = list(
        db.execute(
            select(models.Building)
            .options(selectinload(models.Building.spaces))
            .order_by(models.Building.name)
        ).scalars()
    )
    return templates.TemplateResponse(
        request,
        "bookings.html",
        _ctx(
            request,
            upcoming_by_day=upcoming_by_day,
            past=past,
            cars=cars,
            buildings=buildings,
            form={},
            error=None,
        ),
    )


@router.post("/bookings")
def booking_create(
    request: Request,
    car_id: int = Form(...),
    space_id: int = Form(...),
    start_at: str = Form(...),
    end_at: str = Form(...),
    purpose: str = Form(""),
    notes: str = Form(""),
    created_by: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        start_dt = _parse_local_dt(start_at)
        end_dt = _parse_local_dt(end_at)
    except ValueError:
        return _render_bookings_error(
            request, db, "Invalid start/end time.", locals()
        )
    try:
        services.create_booking(
            db,
            car_id=car_id,
            space_id=space_id,
            start_at=start_dt,
            end_at=end_dt,
            purpose=purpose,
            notes=notes,
            created_by=created_by,
        )
    except services.ServiceError as exc:
        return _render_bookings_error(request, db, str(exc), locals())
    return RedirectResponse(url="/bookings", status_code=status.HTTP_303_SEE_OTHER)


def _render_bookings_error(request: Request, db: Session, msg: str, form_locals: dict):
    form = {
        "car_id": str(form_locals.get("car_id", "")),
        "space_id": str(form_locals.get("space_id", "")),
        "start_at": form_locals.get("start_at", ""),
        "end_at": form_locals.get("end_at", ""),
        "purpose": form_locals.get("purpose", ""),
        "notes": form_locals.get("notes", ""),
        "created_by": form_locals.get("created_by", ""),
    }
    now = datetime.now(timezone.utc)
    all_bookings = list(
        db.execute(
            select(models.Booking)
            .options(
                selectinload(models.Booking.car),
                selectinload(models.Booking.space).selectinload(models.Space.building),
            )
            .order_by(models.Booking.start_at)
        ).scalars()
    )
    upcoming = [b for b in all_bookings if b.status == "active" and b.end_at >= now]
    past = [b for b in all_bookings if not (b.status == "active" and b.end_at >= now)]
    upcoming_by_day = [
        (day, list(items)) for day, items in groupby(upcoming, key=lambda b: b.start_at.date())
    ]
    cars = list(db.execute(select(models.Car).order_by(models.Car.reg)).scalars())
    buildings = list(
        db.execute(
            select(models.Building)
            .options(selectinload(models.Building.spaces))
            .order_by(models.Building.name)
        ).scalars()
    )
    return templates.TemplateResponse(
        request,
        "bookings.html",
        _ctx(
            request,
            upcoming_by_day=upcoming_by_day,
            past=past,
            cars=cars,
            buildings=buildings,
            form=form,
            error=msg,
        ),
        status_code=status.HTTP_409_CONFLICT,
    )


@router.post("/bookings/{booking_id}/cancel")
def booking_cancel(booking_id: int, db: Session = Depends(get_db)):
    try:
        services.cancel_booking(db, booking_id)
    except services.ServiceError:
        pass
    return RedirectResponse(url="/bookings", status_code=status.HTTP_303_SEE_OTHER)


# ---------- Admin (buildings + spaces) ----------


@router.get("/admin")
def admin(request: Request, db: Session = Depends(get_db)):
    buildings = list(
        db.execute(
            select(models.Building)
            .options(selectinload(models.Building.spaces))
            .order_by(models.Building.name)
        ).scalars()
    )
    return templates.TemplateResponse(
        request,
        "admin.html",
        _ctx(request, buildings=buildings, space_kinds=SPACE_KINDS, error=None),
    )


@router.post("/buildings")
def building_create(name: str = Form(...), db: Session = Depends(get_db)):
    name_clean = name.strip()
    if name_clean:
        existing = db.execute(
            select(models.Building).where(models.Building.name == name_clean)
        ).scalar_one_or_none()
        if existing is None:
            db.add(models.Building(name=name_clean))
            db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/buildings/{building_id}/delete")
def building_delete(building_id: int, db: Session = Depends(get_db)):
    b = db.get(models.Building, building_id)
    if b is not None:
        db.delete(b)
        db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/spaces")
def space_create(
    building_id: int = Form(...),
    name: str = Form(...),
    kind: str = Form("general"),
    capacity: int = Form(1),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    if kind not in SPACE_KINDS:
        kind = "general"
    name_clean = name.strip()
    if name_clean and db.get(models.Building, building_id) is not None:
        db.add(
            models.Space(
                building_id=building_id,
                name=name_clean,
                kind=kind,
                capacity=max(1, capacity),
                notes=notes,
            )
        )
        db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/spaces/{space_id}/delete")
def space_delete(space_id: int, db: Session = Depends(get_db)):
    s = db.get(models.Space, space_id)
    if s is not None:
        db.delete(s)
        db.commit()
    return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)