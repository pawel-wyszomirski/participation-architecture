import asyncio
import os
import json
# import openai  # Requires: pip install openai

# CORE LOGIC BLUEPRINT (PROTOTYPE)
# TODO [Grant Milestone]:
# 1. Integrate langchain/openai for production execution.
# 2. Implement token-limit handling for large proposals.
# 3. Add 'Guardrails' to validate JSON output integrity.

class AIClassificationEngine:
    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY")
        # self.client = openai.AsyncOpenAI(api_key=self.api_key)

    async def analyze_proposal_text(self, title: str, body: str) -> dict:
        """
        Sends proposal content to an LLM for classification using the specialized System Prompt.
        """
        
        # --- THE "MONEY SHOT" PROMPT (Optimized for Decision Memos) ---
        system_prompt = """
        You are a Governance Expert and Senior Analyst for the Arbitrum DAO. Your role is twofold: 
        first, to act as a signal filter classifying proposals by strategic importance, 
        and second, to strip away corporate fluff to provide raw, high-density decision memos for busy delegates. 
        You write in English, using a "Dense Writing" style.

        📌 SECTION 1: TASK
        Perform the following two-step analysis on the provided proposal:

        Step 1: Signal Classification (JSON)
        Evaluate whether the proposal is "SIGNAL" (Strategic, High Impact, Constitutional) or "NOISE" (Operational, Reports, Low Impact). 
        Return this strict JSON object.

        Step 2: Decision Memo (Markdown)
        Generate a structured decision memo that highlights:
        1. The Core Ask: What is being voted on?
        2. Hard Facts: Money, dates, people, technical changes.
        3. The Trade-off: ROI vs. Risk.
        4. Operational Logic: Actor + Action + Metric + Condition.

        ⚙️ SECTION 3: CONSTRAINTS (DENSE WRITING & ZERO-AI ADAPTATION)
        1. DETOXIFY LANGUAGE (Anti-Fluff):
           - BANNED WORDS: delve, landscape, tapestry, testament, underscore, paramount, crucial, leverage, foster, spearhead, realm, symphony.
           - NO FLUFF INTROS: Start directly with the subject or verb.
        2. DENSITY METRICS:
           - Sentence Length: Max 15 words per sentence.
           - Verb-Centric: Use active verbs.
        3. THE "CONCRETE" RULE:
           - Every paragraph must contain at least one number ($, %, date) or hard fact.

        📤 SECTION 5: OUTPUT FORMAT
        You must output TWO distinct blocks.

        BLOCK 1: CLASSIFICATION (Strict JSON)
        {
            "classification": "SIGNAL" | "NOISE",
            "confidence": 0-100,
            "reasoning": "Short justification (max 1 sentence)",
            "tags": ["Security", "Treasury", "Constitutional", "Ops", "Incentives"]
        }

        BLOCK 2: DECISION MEMO (Markdown)
        🗳️ Decision Memo: [Insert Proposal Title]
        TL;DR [2 sentences max]
        💰 Hard Data (The Cost)
        | Metric | Value |
        | :--- | :--- |
        ...
        ⚖️ The Trade-off (Analysis)
        Why YES (Upside): ...
        Why NO (Risks): ...
        ⚠️ Red Flags
        Verdict Signal
        """
        
        user_prompt = f"Title: {title}\n\nBody: {body[:15000]}" # Support larger context

        # Mock response (simulating what the LLM would return based on your prompt)
        print(f"🤖 [AI WORKER] Analysing proposal: {title}")
        print(f"📝 [PROMPT] Injecting 'Dense Writing' system instructions...")
        await asyncio.sleep(1) # Simulate API latency
        
        # Hard Rule Logic (Safety Valve) still applies before/after AI
        if "security" in title.lower() or "hack" in title.lower():
            return {
                "classification": "SIGNAL", 
                "confidence": 100, 
                "reasoning": "Hard Rule: Security Keyword Detected",
                "tags": ["Security", "Risk"]
            }

        # Simulated AI Output (for the RAD proposal example)
        return {
            "classification": "SIGNAL",
            "confidence": 84,
            "reasoning": "Moves up to 7,000,000 ARB toward delegate-pay incentives with OpCo-controlled rules.",
            "tags": ["Treasury", "Incentives", "Ops"]
        }

    async def process_queue(self):
        """
        Main worker loop - fetches unprocessed proposals from the database.
        """
        print("🚀 Starting AI Classification Worker (Milestone 2 Draft)...")
        while True:
            # Here we would fetch from DB: 
            # proposals = db.query(Proposal).filter(Proposal.ai_analyzed == False).limit(5)
            
            # For each proposal:
            # result = await self.analyze_proposal_text(p.title, p.body)
            # p.save_ai_result(result)
            
            await asyncio.sleep(10) # Rest

if __name__ == "__main__":
    worker = AIClassificationEngine()
    asyncio.run(worker.process_queue())