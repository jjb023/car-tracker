from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BuildingIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["LRW HQ (Kiln Farm)", "LRW Train Shed"])


class BuildingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class SpaceIn(BaseModel):
    building_id: int = Field(examples=[1])
    name: str = Field(min_length=1, max_length=100, examples=["Cell 1"])
    kind: str = Field(
        default="general",
        description="One of: general, bay, emissions, dyno, other.",
        examples=["dyno"],
    )
    capacity: int = Field(default=1, examples=[1])
    notes: str = Field(default="", examples=["4WD-capable rolling road"])


class SpaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    building_id: int
    name: str
    kind: str
    capacity: int
    notes: str


class CarIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "reg": "AB12 CDE",
                    "make_model": "Aston Martin DB12",
                    "notes": "DMTL Testing",
                }
            ]
        }
    )
    reg: str = Field(
        min_length=1,
        max_length=20,
        description="UK-style registration plate. Stored uppercase; spaces are preserved as entered.",
        examples=["AB12 CDE"],
    )
    make_model: str = Field(default="", examples=["Aston Martin DB12"])
    notes: str = Field(default="", examples=["DMTL Testing"])


class CarOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    reg: str
    make_model: str
    notes: str
    archived: bool
    current_space_id: Optional[int] = None
    current_space_name: Optional[str] = None


class MoveIn(BaseModel):
    space_id: Optional[int] = Field(
        default=None,
        description="Target space id. Pass null to mark the car as off-site.",
        examples=[3],
    )
    notes: str = Field(default="", examples=["Returned from customer site"])


class BookingIn(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "car_id": 7,
                    "space_id": 3,
                    "start_at": "2026-04-28T09:00:00",
                    "end_at": "2026-04-28T17:00:00",
                    "purpose": "Emissions test",
                    "notes": "",
                    "created_by": "Josh Beal",
                }
            ]
        }
    )
    car_id: int = Field(
        description="Id of the car to book. Resolve from a registration plate via listCars first.",
        examples=[7],
    )
    space_id: int = Field(
        description="Id of the space to reserve. Resolve from a space name via listSpaces first.",
        examples=[3],
    )
    start_at: datetime = Field(
        description="Booking start time, ISO 8601. Local time assumed if no timezone is given.",
        examples=["2026-04-28T09:00:00"],
    )
    end_at: datetime = Field(
        description="Booking end time, ISO 8601. Must be after start_at.",
        examples=["2026-04-28T17:00:00"],
    )
    purpose: str = Field(default="", examples=["Emissions test"])
    notes: str = Field(default="", examples=[""])
    created_by: str = Field(
        default="",
        description="Free-text name or username of the person making the booking.",
        examples=["Josh Beal"],
    )


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    car_id: int
    space_id: int
    start_at: datetime
    end_at: datetime
    purpose: str
    notes: str
    status: str
    created_by: str