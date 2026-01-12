import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Konfiguracja URL bazy danych
# Domyślnie używamy SQLite (participation.db) jeśli zmienna DATABASE_URL nie jest ustawiona.
# To pozwala na uruchamianie skryptów lokalnie bez błędów połączenia do 'db'.
# W Docker Compose zmienna DATABASE_URL jest ustawiona na postgresql://...
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./participation.db")

# Dostosowanie URL dla sterownika synchronicznego (jeśli używasz asyncpg w configu)
if "asyncpg" in DATABASE_URL:
    SYNC_DATABASE_URL = DATABASE_URL.replace("+asyncpg", "+psycopg2")
else:
    SYNC_DATABASE_URL = DATABASE_URL

# Opcje specyficzne dla SQLite
connect_args = {}
if "sqlite" in SYNC_DATABASE_URL:
    connect_args = {"check_same_thread": False}

engine = create_engine(SYNC_DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# To jest ta sama klasa Base, której używają Twoje modele
Base = declarative_base()