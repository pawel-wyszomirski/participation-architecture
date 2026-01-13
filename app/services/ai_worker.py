import asyncio
import os
# import openai  # Requires: pip install openai

# This is a DRAFT implementation for Milestone 2.
# It demonstrates the logic for processing proposal text using an LLM.

class AIClassificationEngine:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        # self.client = openai.AsyncOpenAI(api_key=self.api_key)

    async def analyze_proposal_text(self, title: str, body: str) -> dict:
        """
        Sends proposal content to an LLM for classification.
        """
        system_prompt = """
        You are a governance expert for Arbitrum DAO.
        Your task is to evaluate whether the following proposal is "SIGNAL" (strategic, important)
        or "NOISE" (operational, report, low impact).
        
        Return the result in JSON format:
        {
            "classification": "SIGNAL" | "NOISE",
            "confidence": 0-100,
            "reasoning": "Short justification (max 1 sentence)",
            "tags": ["Security", "Treasury", "Constitutional", "Ops"]
        }
        """
        
        user_prompt = f"Title: {title}\n\nBody: {body[:2000]}" # Truncate body

        # Mock response (simulating AI behavior without an API key)
        print(f"🤖 [AI WORKER] Analysing proposal: {title}")
        await asyncio.sleep(1) # Simulate API latency
        
        # Example "Safety Valve" logic (Hard Rules override AI)
        if "security" in title.lower() or "hack" in title.lower():
            return {
                "classification": "SIGNAL", 
                "confidence": 100, 
                "reasoning": "Hard Rule: Security Keyword Detected",
                "tags": ["Security", "Risk"]
            }

        return {
            "classification": "NOISE",
            "confidence": 85,
            "reasoning": "Routine operational report detected.",
            "tags": ["Ops", "Report"]
        }

    async def process_queue(self):
        """
        Main worker loop - fetches unprocessed proposals from the database.
        """
        print("🚀 Starting AI Classification Worker...")
        while True:
            # Here we would fetch from DB: 
            # proposals = db.query(Proposal).filter(Proposal.ai_analyzed == False).limit(5)
            
            # For each proposal:
            # result = await self.analyze_proposal_text(p.title, p.body)
            # p.is_signal = (result['classification'] == 'SIGNAL')
            # p.ai_analyzed = True
            # db.commit()
            
            await asyncio.sleep(10) # Rest

if __name__ == "__main__":
    worker = AIClassificationEngine()
    asyncio.run(worker.process_queue())