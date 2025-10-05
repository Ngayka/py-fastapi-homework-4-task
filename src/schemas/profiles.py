from datetime import date
from typing import Optional

from fastapi import UploadFile, Form, File, HTTPException
from pydantic import BaseModel, field_validator, HttpUrl

from database.models.accounts import GenderEnum
from validation import (
    validate_name,
    validate_image,
    validate_gender,
    validate_birth_date
)


class UserProfileRequestSchema(BaseModel):
    first_name: str
    last_name: str
    gender: Optional[GenderEnum] = None
    date_of_birth: Optional[date] = None
    info: Optional[str] = None

    model_config = {
        "from_attributes": True
    }

    @field_validator("first_name")
    @classmethod
    def validate_first_name(cls, name):
        return validate_name(name)

    @field_validator("last_name")
    @classmethod
    def validate_last_name(cls, last_name):
        return validate_name(last_name)


    @field_validator("gender")
    @classmethod
    def validate_user_gender(cls, gender):
        return validate_gender(gender)


    @field_validator("date_of_birth")
    @classmethod
    def validate_date_of_birth(cls, birth_date: date):
        return validate_birth_date(birth_date)


class ProfileResponseSchema(BaseModel):
    id: int
    user_id: int
    first_name: str
    last_name: str
    gender: Optional[str] = None
    date_of_birth: Optional[date] = None
    avatar: Optional[str] = None
    info: Optional[str]
