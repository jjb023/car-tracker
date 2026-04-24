from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _now() -> datetime:
    # Naive UTC. SQLite stores datetimes without tz info, so keeping everything
    # naive UTC in-process avoids mixing aware/naive during comparisons.
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


SPACE_KINDS = ("general", "bay", "emissions", "dyno", "other")
BOOKING_STATUSES = ("active", "cancelled")


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    spaces: Mapped[list["Space"]] = relationship(
        back_populates="building",
        cascade="all, delete-orphan",
        order_by="Space.name",
    )


class Space(Base):
    __tablename__ = "spaces"
    __table_args__ = (UniqueConstraint("building_id", "name", name="uq_space_building_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    building_id: Mapped[int] = mapped_column(ForeignKey("buildings.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(32), default="general")
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str] = mapped_column(String(500), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    building: Mapped[Building] = relationship(back_populates="spaces")


class Car(Base):
    __tablename__ = "cars"

    id: Mapped[int] = mapped_column(primary_key=True)
    reg: Mapped[str] = mapped_column(String(20), unique=True)
    make_model: Mapped[str] = mapped_column(String(100), default="")
    notes: Mapped[str] = mapped_column(String(1000), default="")
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    locations: Mapped[list["CarLocation"]] = relationship(
        back_populates="car",
        cascade="all, delete-orphan",
        order_by="CarLocation.arrived_at.desc()",
    )


class CarLocation(Base):
    """One row per "stay" at a place. Open row (left_at IS NULL) = current location.

    space_id NULL means the car is off-site.
    """

    __tablename__ = "car_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"))
    space_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("spaces.id", ondelete="SET NULL"), nullable=True
    )
    arrived_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    left_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(String(500), default="")

    car: Mapped[Car] = relationship(back_populates="locations")
    space: Mapped[Optional[Space]] = relationship()


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    car_id: Mapped[int] = mapped_column(ForeignKey("cars.id", ondelete="CASCADE"))
    space_id: Mapped[int] = mapped_column(ForeignKey("spaces.id", ondelete="CASCADE"))
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    purpose: Mapped[str] = mapped_column(String(200), default="")
    notes: Mapped[str] = mapped_column(String(1000), default="")
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_by: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    car: Mapped[Car] = relationship()
    space: Mapped[Space] = relationship()