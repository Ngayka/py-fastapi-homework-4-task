from datetime import datetime

from fastapi import (
    APIRouter,
    status,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    Path,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_s3_storage_client, get_jwt_auth_manager
from database import get_db, UserProfileModel, UserModel

from database.models.accounts import GenderEnum
from exceptions import S3FileUploadError, TokenExpiredError, InvalidTokenError
from security.http import get_token
from security.token_manager import JWTAuthManager
from schemas.profiles import UserProfileResponseSchema, UserProfileRequestSchema
from storages import S3StorageInterface
from validation import validate_image

router = APIRouter()


async def get_current_user(
    token=Depends(get_token),
    jwt_manager: JWTAuthManager = Depends(get_jwt_auth_manager),
    db: AsyncSession = Depends(get_db),
) -> UserModel:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token missing"
        )

    try:
        payload = jwt_manager.decode_access_token(token)
    except TokenExpiredError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired."
        )
    except InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )

    user_id = payload.get("user_id")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active.",
        )
    result = await db.execute(select(UserModel).where(UserModel.id == user_id))
    current_user = result.scalars().first()
    if not current_user or not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or not active.",
        )
    return current_user


@router.post(
    "/users/{user_id}/profile/",
    response_model=UserProfileResponseSchema,
    summary="Create user profile",
    status_code=status.HTTP_201_CREATED,
)
async def create_user_profile(
    current_user: UserModel = Depends(get_current_user),
    user_id: int = Path(...),
    first_name: str = Form(...),
    last_name: str = Form(...),
    gender: GenderEnum = Form(...),
    date_of_birth: str = Form(...),
    info: str = Form(...),
    avatar: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    s3_client: S3StorageInterface = Depends(get_s3_storage_client),
):
    if current_user.id != user_id and current_user.group_id != 3:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You don't have permission to edit this profile.",
        )

    stmt = select(UserProfileModel).filter(UserProfileModel.user_id == user_id)
    result = await db.execute(stmt)
    existing_profile = result.scalars().first()
    if existing_profile:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already has a profile.",
        )

    try:
        validate_image(avatar)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)
        )

    try:
        date_of_birth_obj = datetime.strptime(date_of_birth, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid date format. Use YYYY-MM-DD.",
        )

    profile = UserProfileModel(
        user_id=user_id,
        first_name=first_name.strip().lower(),
        last_name=last_name.strip().lower(),
        gender=gender,
        date_of_birth=date_of_birth_obj,
        avatar=f"avatars/{user_id}_avatar.jpg",
        info=info.strip() or None,
    )

    db.add(profile)

    try:
        file_data = await avatar.read()
        await s3_client.upload_file(file_name=profile.avatar, file_data=file_data)
        await db.commit()
        await db.refresh(profile)
        avatar_url = await s3_client.get_file_url(file_name=profile.avatar)
    except S3FileUploadError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload avatar. Please try again later.",
        )

    return UserProfileResponseSchema(
        id=profile.id,
        user_id=profile.user_id,
        first_name=profile.first_name,
        last_name=profile.last_name,
        gender=profile.gender,
        date_of_birth=profile.date_of_birth,
        info=profile.info,
        avatar=avatar_url,
    )
