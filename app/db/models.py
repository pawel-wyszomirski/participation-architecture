from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class Delegate(Base):
    __tablename__ = "delegates"

    address = Column(String, primary_key=True, index=True)
    ens_name = Column(String, nullable=True)
    first_seen = Column(DateTime, default=datetime.utcnow)
    
    votes = relationship("Vote", back_populates="delegate")

class Proposal(Base):
    __tablename__ = "proposals"

    id = Column(String, primary_key=True)  # Snapshot ID
    title = Column(String, nullable=False)
    body = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)
    
    # Intelligence Layer Fields
    is_signal = Column(Boolean, default=False)
    classification_confidence = Column(Float, nullable=True)
    
    votes = relationship("Vote", back_populates="proposal")

class Vote(Base):
    __tablename__ = "votes"

    id = Column(String, primary_key=True)
    delegate_address = Column(String, ForeignKey("delegates.address"))
    proposal_id = Column(String, ForeignKey("proposals.id"))
    choice = Column(Integer)
    created = Column(DateTime)
    
    delegate = relationship("Delegate", back_populates="votes")
    proposal = relationship("Proposal", back_populates="votes")