from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI(
    title="Participation Architecture API",
    version="0.1.0",
    description="API for measuring Delegate Fatigue in Arbitrum DAO"
)

# --- MODELE (Zdefiniowane wewnątrz, żeby niczego nie importować) ---
class HealthCheck(BaseModel):
    status: str
    version: str

class FatigueResponse(BaseModel):
    address: str
    fatigue_score: int
    risk_level: str
    participation_rate: float
    last_vote_date: str

# --- ENDPOINTS ---

@app.get("/", tags=["System"])
async def root():
    return {"message": "Participation Architecture API is running. Go to /docs for Swagger."}

@app.get("/health", response_model=HealthCheck, tags=["System"])
async def health_check():
    return HealthCheck(status="ok", version="0.1.0")

@app.get("/v1/delegates/{address}/fatigue", response_model=FatigueResponse, tags=["Delegates"])
async def get_delegate_fatigue(address: str):
    """
    [MOCK] Zwraca wynik zmęczenia dla delegata.
    """
    # Symulacja 404
    if address == "0x000":
        raise HTTPException(status_code=404, detail="Delegate not found")
    
    # Mock Data (twarde dane na start)
    return FatigueResponse(
        address=address,
        fatigue_score=85,
        risk_level="HIGH",
        participation_rate=0.45,
        last_vote_date="2024-12-25"
    )