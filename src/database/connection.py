import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def get_db_connection():
    """Cria e retorna uma conexão com o banco PostGIS."""
    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "smartpass"),
        user=os.getenv("DB_USER", "smartpass_user"),
        password=os.getenv("DB_PASS", "smartpass_password"),
        port=os.getenv("DB_PORT", "5432")
    )
    return conn