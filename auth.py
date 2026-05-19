from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from datetime import datetime, timedelta
from database import get_user

SECRET_KEY = "your-secret-key-change-this-in-production"  # 🔐 Change this!
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user_api(token: str = Depends(oauth2_scheme)):
    """For API routes — reads Bearer token from Authorization header (Swagger)"""
    return _decode_token(token)

def get_current_user_cookie(request: Request):
    """For browser routes — reads JWT from cookie"""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=303, detail="Not logged in")
    token_value = token.replace("Bearer ", "")
    return _decode_token(token_value)

def _decode_token(token: str):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = get_user(username)
    if user is None:
        raise credentials_exception
    return user