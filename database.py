import os
from supabase import create_client, Client
from supabase.client import ClientOptions
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from dotenv import load_dotenv

load_dotenv()

ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

def get_supabase() -> Client:
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
        options=ClientOptions()          # 👈 fixes the AttributeError
    )

def init_db():
    print("✅ Supabase client ready")

def hash_password(password: str) -> str:
    return ph.hash(password)

def verify_password(plain_password: str, stored_hash: str) -> bool:
    try:
        ph.verify(stored_hash, plain_password)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False

def create_user(username: str, password: str):
    supabase = get_supabase()
    try:
        supabase.table("users").insert({
            "username": username,
            "hashed_password": hash_password(password)
        }).execute()
        return True
    except Exception as e:
        if "duplicate" in str(e).lower() or "unique" in str(e).lower() or "23505" in str(e):
            return False
        raise e

def get_user(username: str):
    supabase = get_supabase()
    result = supabase.table("users").select("*").eq("username", username).execute()
    if result.data:
        return result.data[0]
    return None