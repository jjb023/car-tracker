from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class BuildingIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class BuildingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str


class SpaceIn(BaseModel):
    building_id: int
    name: str = Field(min_length=1, max_length=100)
    kind: str = "general"
    capacity: int = 1
    notes: str = ""


class SpaceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    building_id: int
    name: str
    kind: str
    capacity: int
    notes: str


class CarIn(BaseModel):
    reg: str = Field(min_length=1, max_length=20)
    make_model: str = ""
    notes: str = ""


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
    space_id: Optional[int] = None  # None = off-site
    notes: str = ""


class BookingIn(BaseModel):
    car_id: int
    space_id: int
    start_at: datetime
    end_at: datetime
    purpose: str = ""
    notes: str = ""
    created_by: str = ""


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