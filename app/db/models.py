from sqlalchemy import Column, String, Integer, Float, Text, DateTime, Boolean
from datetime import datetime
from app.db.session import Base

class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    state = Column(String)     # 'closed', 'active'
    author = Column(String)    # adres portfela autora
    
    # Metryki głosowania
    votes = Column(Integer, default=0)
    scores_total = Column(Float, default=0.0)
    
    # Czas (Unix Timestamp)
    start = Column(Integer)
    end = Column(Integer)
    
    # Metadane systemowe
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Pola dla Twojego algorytmu (Fatigue Index)
    is_signal = Column(Boolean, default=False)
    fatigue_score = Column(Float, default=0.0)