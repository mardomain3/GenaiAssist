import os
import uuid
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request, Form,Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import timedelta
from services.query_services import run_query, get_columns
from database import init_db, create_user, get_user, verify_password,get_supabase
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse

from auth import (
    create_access_token,
    get_current_user_api,
    get_current_user_cookie,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

# ─── App Setup ──────────────────────────────────────────────
app = FastAPI(
    title="GenAI Query Assistant",
    description="Upload an Excel dataset and ask natural language questions",
    version="1.0.0"
)

templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ─── Init DB on startup ─────────────────────────────────────
@app.on_event("startup")
def startup():
    init_db()

# ─── In-memory file store ───────────────────────────────────
file_store = {}  # { file_id: file_path }

# ─── Pydantic Models ────────────────────────────────────────
class Token(BaseModel):
    access_token: str
    token_type: str

class UserCreate(BaseModel):
    username: str
    password: str

class QueryRequest(BaseModel):
    file_id: str
    question: str


# ══════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    registered = request.query_params.get("registered")
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"registered": registered, "error": error}
    )

@app.post("/login", response_class=HTMLResponse)
def login_form(request: Request, username: str = Form(...), password: str = Form(...)):
    user = get_user(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": "Invalid username or password"}
        )
    access_token = create_access_token(
        data={"sub": username},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(key="access_token", value=f"Bearer {access_token}", httponly=True)
    return response
@app.get("/me")
def get_me(request: Request):
    """Returns current logged-in username — called by index.html on load"""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")
    try:
        from jose import jwt
        from auth import SECRET_KEY, ALGORITHM
        token_value = token.replace("Bearer ", "")
        payload = jwt.decode(token_value, SECRET_KEY, algorithms=[ALGORITHM])
        username = payload.get("sub")
        return {"username": username}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
# OAuth2 token endpoint — for Swagger UI /docs

@app.post("/token", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    user = get_user(form_data.username)
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token = create_access_token(
        data={"sub": user["username"]},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/register")
def register(user: UserCreate):
    success = create_user(user.username, user.password)
    if not success:
        raise HTTPException(status_code=400, detail="Username already exists")
    return {"message": "User created successfully"}

@app.get("/logout")
def logout():
    response = RedirectResponse(url="/login")
    response.delete_cookie("access_token")
    return response


# ══════════════════════════════════════════════════════════════
#  PROTECTED: STATIC + FRONTEND
# ══════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    # Redirect to login if no cookie
    token = request.cookies.get("access_token")
    if not token:
        return RedirectResponse(url="/login")
    return FileResponse("static/index.html")


# Mount static AFTER the / route so it doesn't intercept it
app.mount("/static", StaticFiles(directory="static"), name="static")


# ══════════════════════════════════════════════════════════════
#  PROTECTED: GENAI API ROUTES
# ══════════════════════════════════════════════════════════════

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user_cookie)   # ✅ cookie
):
    if not file.filename.endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported")

    file_id = str(uuid.uuid4())
    save_path = f"data/{file_id}_{file.filename}"
    os.makedirs("data", exist_ok=True)

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    file_store[file_id] = save_path
    return {"message": "File uploaded successfully", "file_id": file_id, "filename": file.filename}


@app.get("/columns/{file_id}")
def columns(
    file_id: str,
    current_user=Depends(get_current_user_cookie)   # ✅ cookie
):
    if file_id not in file_store:
        raise HTTPException(status_code=404, detail="File not found")
    cols = get_columns(file_store[file_id])
    return {"file_id": file_id, "columns": cols}


@app.post("/query")
def query(
    request: QueryRequest,
    current_user=Depends(get_current_user_cookie)   # ✅ cookie (was get_current_user_api)
):
    if request.file_id not in file_store:
        raise HTTPException(status_code=404, detail="File not found. Upload first.")
    result = run_query(file_store[request.file_id], request.question)
    return result

@app.get("/admin/users")
def list_users(request: Request):
    secret = request.query_params.get("secret")
    if secret != "mardomain333":
        raise HTTPException(status_code=403, detail="Forbidden")
    
    from database import get_supabase
    supabase = get_supabase()
    result = supabase.table("users").select("id, username, created_at").execute()
    users = result.data

    return {
        "total_users": len(users),
        "users": users
    }

@app.get("/auth/google")
def google_login():
    supabase_url = os.getenv("SUPABASE_URL")
    redirect_to = os.getenv("REDIRECT_URL")
    
    # Build Supabase OAuth URL directly
    url = (
        f"{supabase_url}/auth/v1/authorize"
        f"?provider=google"
        f"&redirect_to={redirect_to}"
    )
    return RedirectResponse(url=url)


@app.get("/auth/callback")
def google_callback(request: Request, code: str = None, error: str = None):
    if error:
        print(f"❌ Error from Google: {error}")
        return RedirectResponse(url="/login?error=google_failed")

    # With implicit flow, token comes as URL fragment (#access_token=...)
    # We need a small HTML page to extract it and send to backend
    return HTMLResponse("""
        <html>
        <script>
            // Extract token from URL fragment
            const hash = window.location.hash.substring(1);
            const params = new URLSearchParams(hash);
            const access_token = params.get('access_token');
            const refresh_token = params.get('refresh_token');

            if (access_token) {
                // Send token to backend
                fetch('/auth/session', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ access_token, refresh_token })
                })
                .then(res => res.json())
                .then(data => {
                    if (data.success) {
                        window.location.href = '/';
                    } else {
                        window.location.href = '/login?error=google_failed';
                    }
                });
            } else {
                window.location.href = '/login?error=google_failed';
            }
        </script>
        <body>Completing sign in...</body>
        </html>
    """)


@app.post("/auth/session")
def handle_session(request: Request, body: dict = Body(...)):
    """Receive token from frontend and set cookie"""
    from database import get_supabase
    from pydantic import BaseModel

    access_token = body.get("access_token")
    if not access_token:
        raise HTTPException(status_code=400, detail="No token")

    try:
        supabase = get_supabase()
        # Get user info from token
        user = supabase.auth.get_user(access_token)
        email = user.user.email
        username = email.split("@")[0]

        # Create user in our table if not exists
        existing = get_user(username)
        if not existing:
            import secrets
            create_user(username, secrets.token_hex(32))

        # Set our JWT cookie
        token = create_access_token(
            data={"sub": username},
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        response = JSONResponse({"success": True})
        response.set_cookie(key="access_token", value=f"Bearer {token}", httponly=True)
        return response

    except Exception as e:
        print(f"❌ Session error: {e}")
        return JSONResponse({"success": False})