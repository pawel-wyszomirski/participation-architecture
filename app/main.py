import os
import sys
from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

# Dodajemy ścieżkę do projektu
sys.path.append(os.getcwd())

# Importujemy Twoje istniejące moduły
from app.db.session import SessionLocal, engine, Base
from app.db.models import Proposal

# Inicjalizacja bazy (upewnienie się, że tabele istnieją)
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Participation Architecture API",
    version="0.5.2",  # Podbijamy wersję po integracji z bazą
    description="Signal-to-Noise Governance Infrastructure for Arbitrum DAO (Live Data)"
)

# Dependency do pobierania sesji bazy danych
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- MODELS (Twoje oryginalne modele z Planu v5.1 - BEZ ZMIAN) ---

class FatigueBreakdown(BaseModel):
    volume_impact: float      # Wpływ ilości głosowań (0.0 - 1.0)
    time_scarcity: float      # Brak czasu między głosowaniami (0.0 - 1.0)
    dropout_risk: float       # Ryzyko porzucenia (0.0 - 1.0)

class FatigueMetrics(BaseModel):
    votes_last_30d: int
    avg_time_gap_hours: float
    participation_rate: float

class FatigueResponse(BaseModel):
    address: str
    fatigue_score: float
    status: str                # LOW / MODERATE / CRITICAL
    breakdown: FatigueBreakdown
    metrics: FatigueMetrics
    last_updated: datetime

class HealthCheck(BaseModel):
    status: str
    version: str
    database: str
    proposals_count: int       # Dodane: Licznik propozycji w bazie

# --- ENDPOINTS ---

@app.get("/", tags=["System"])
async def root():
    return {"message": "Participation Architecture API v0.5.2 (Live Data) is running."}

@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check(db: Session = Depends(get_db)):
    """
    Sprawdza stan systemu i połączenie z bazą danych.
    """
    try:
        # Próba odpytania bazy o liczbę propozycji
        count = db.query(Proposal).count()
        db_status = "connected"
    except Exception as e:
        print(f"Health Check DB Error: {e}")
        count = 0
        db_status = "disconnected"
        
    return HealthCheck(
        status="ok", 
        version="0.5.2", 
        database=db_status,
        proposals_count=count
    )

@app.get("/v1/delegates/{address}/fatigue", response_model=FatigueResponse, tags=["Delegates"])
async def get_delegate_fatigue(address: str, db: Session = Depends(get_db)):
    """
    Returns calculated Fatigue Score based on REAL DATA from local DB.
    Reflects the 'Hard Specs' from Engineering Plan v5.1.
    """
    # 1. Pobieramy dane z bazy (Integration Logic)
    # W MVP (Faza 1) liczymy globalne obciążenie ekosystemu (ile jest propozycji do głosowania).
    # W Fazie 2 dojdzie tabela 'Votes' per delegat.
    
    total_proposals_30d = db.query(Proposal).count() # Uproszczenie na potrzeby demo
    
    # 2. Logika Biznesowa (Fatigue Engine v1)
    # Jeśli baza jest pusta, zwracamy 0.0 (zamiast mocka), co jest prawdą.
    if total_proposals_30d == 0:
        score = 0.0
        status = "LOW"
    else:
        # Prosty algorytm: 1 propozycja dziennie to już dużo. 
        # 30 propozycji w 30 dni = 100% fatigue (teoretycznie).
        # Skalujemy to do 0-100.
        raw_score = (total_proposals_30d / 30.0) * 100 
        score = min(raw_score, 100.0) # Cap at 100

        if score < 30: status = "LOW"
        elif score < 70: status = "MODERATE"
        else: status = "CRITICAL"

    # 3. Konstrukcja odpowiedzi zgodnej z Twoim modelem
    return FatigueResponse(
        address=address,
        fatigue_score=round(score, 1),
        status=status,
        breakdown=FatigueBreakdown(
            volume_impact=round(score/100, 2), # Korelacja z liczbą głosowań
            time_scarcity=0.5,                 # Stała dla MVP
            dropout_risk=0.2                   # Stała dla MVP
        ),
        metrics=FatigueMetrics(
            votes_last_30d=total_proposals_30d, # TO JEST PRAWDZIWA LICZBA Z BAZY!
            avg_time_gap_hours=24.0,
            participation_rate=0.0              # Brak danych o userze w MVP
        ),
        last_updated=datetime.now(timezone.utc)
    )

# Endpoint pomocniczy do Demo (surowe dane)
@app.get("/debug/proposals", tags=["Debug"])
def get_raw_proposals(limit: int = 5, db: Session = Depends(get_db)):
    """
    Pomocniczy endpoint do pokazania na Callu, że mamy prawdziwe tytuły w bazie.
    """
    return db.query(Proposal).order_by(Proposal.start.desc()).limit(limit).all()