from datetime import datetime

from fastapi import APIRouter, status, Depends, HTTPException, UploadFile, File, Form
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_s3_storage_client, get_jwt_auth_manager
from database import (get_db, UserProfileModel, UserModel)
from jose import JWTError, ExpiredSignatureError

from database.models.accounts import GenderEnum
from security.http import get_token
from security.token_manager import JWTAuthManager
from schemas.profiles import ProfileResponseSchema, UserProfileRequestSchema
from storages import S3StorageInterface
from validation import validate_image

router = APIRouter()


security = HTTPBearer()


async def get_current_user(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
        db: AsyncSession = Depends(get_db)
):
    token = credentials.credentials
    try:
        payload = jwt_manager.decode_access_token(token)
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired."
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active."
        )
    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    current_user = result.scalars().first()
    if not current_user or not current_user.is_active:
        raise HTTPException(status_code= status.HTTP_401_UNAUTHORIZED,
                            detail="User not found or not active.")
    return current_user

@router.post(
    "/profile/",
    response_model=ProfileResponseSchema,
    summary="Create user profile",
    status_code=status.HTTP_201_CREATED
)
async def create_user_profile(
        first_name: str = Form(...),
        last_name: str = Form(...),
        gender: GenderEnum = Form(...),
        date_of_birth: str = Form(...),
        info: str = Form(...),
        avatar: UploadFile = File(...),
        db: AsyncSession = Depends(get_db),
        current_user: UserModel = Depends(get_current_user),
        s3_client: S3StorageInterface = Depends(get_s3_storage_client)
):
    stmt = select(UserProfileModel).filter(UserProfileModel.id == current_user.id)
    result = await db.execute(stmt)
    existing_profile = result.scalars().first()
    if existing_profile:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="User already has a profile.")

    try:
        validate_image(avatar)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    try:
        date_of_birth = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid data format")

    profile = UserProfileModel(
        user_id=current_user.id,
        first_name=first_name,
        last_name=last_name,
        gender=gender,
        date_of_birth=date_of_birth,
        info=info
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    file_name = avatar.filename
    file_data = await avatar.read()
    await s3_client.upload_file(file_name=file_name, file_data=file_data)
    avatar_url = await s3_client.get_file_url(file_name=file_name)
    profile.avatar = avatar_url
    await db.commit()
    await db.refresh(profile)

    return profile
