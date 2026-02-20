import os
import time
import requests
import schedule
from datetime import datetime
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from tavily import TavilyClient


load_dotenv()

NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# --- KEEPS TRACKS OF NEWS ALREADY SEEN ---
seen_titles = set()

# ---  MODELS ---
LLM_GATHER = ChatOpenAI(
    model="openai/gpt-4o",
    temperature=0,
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

LLM_SUMMARIZE = ChatOpenAI(
    model="openai/gpt-4o-mini",
    temperature=0.2,
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY
)

tavily = TavilyClient(api_key=TAVILY_API_KEY)

# --- PROMPTS ---
gather_prompt = PromptTemplate.from_template(
    """
You are a strict logistics risk analyst for {country_name}.
Time period: {date_display}

First: identify if the period includes any major public holiday in {country_name}
that causes significant logistics impact (closed ports/customs/warehouses, reduced transport).

Then filter events.

Return ONLY:
- HIGH severity disruptions: HIGH | short description | logistics impact
- If relevant: Holiday Impact: [holiday name] - brief logistics effect (only if HIGH risk)

If nothing qualifies as HIGH risk → return exactly:
NO_HIGH_RISK_EVENTS

Events:
{events}
"""
)

gather_chain = gather_prompt | LLM_GATHER | StrOutputParser()

# --- SUMMARY PROMPT ---
summary_prompt = PromptTemplate.from_template(
    """
You are a concise logistics alert writer.

Input is a list of confirmed HIGH severity disruptions and/or major holiday impacts.

Turn them into a very short alert summary (2–3 sentences maximum).
Be direct, urgent, and factual.

If input is "NO_HIGH_RISK_EVENTS" → return exactly:
No high-risk logistics disruptions or major holiday impacts detected in {date_display}.

Input:
{filtered_events}

Country: {country_name}
Time period: {date_display}
"""
)

summary_chain = summary_prompt | LLM_SUMMARIZE | StrOutputParser()

# --- FIRST DATA SOURCE ---
NEWSDATA_URL = "https://newsdata.io/api/1/news"

def fetch_newsdata():
    try:
        params = {
            "apikey": NEWSDATA_API_KEY,
            "country": "za",
            "language": "en",
            "q": "holiday strike logistics transport port"
        }
        response = requests.get(NEWSDATA_URL, params=params, timeout=10)
        response.raise_for_status()
        results = response.json().get("results", [])
        return [
            f"{r.get('title')} - {r.get('description')}"
            for r in results
            if r.get("title")
        ]
    except Exception as e:
        print(f"[{datetime.now()}] NewsData fetch failed: {e}")
        return []
    
# --- SECOND SOURCE ---
def fetch_tavily():
    try:
        result = tavily.search(
            query="South Africa holiday strike protest port disruption transport delay",
            search_depth="advanced",
            max_results=10
        )
        return [r.get("content", "") for r in result.get("results", [])]
    except Exception as e:
        print(f"[{datetime.now()}] Tavily fetch failed: {e}")
        return []

    
# --- COMBINE AND REMOVE DUPLICATES ---
def get_new_headlines():
    newsdata_articles = fetch_newsdata()
    tavily_event = fetch_tavily()

    all_headlines = list(set(tavily_event + newsdata_articles))

    print("\n==============================")
    print("ENTERPRISE LOGISTICS ALERT")
    print("Region: South Africa")
    print(f"Date: {datetime.now()}")
    print("==============================\n")

    if not all_headlines:
        print("No logistics-impacting events detected today.")
        return

    try:
        report = chain.run(events="\n".join(all_headlines))
        print(report)
    except Exception as e:
        print(f"[{datetime.now()}] Analysis failed: {e}")

# --- DAILY SCHEDULER ---
def start_scheduler():
    schedule.every().day.at("07:00").do(get_new_headlines)
    print(f"[{datetime.now()}] Logistics agent scheduled to run daily at 07:00")

    while True:
        schedule.run_pending()
        time.sleep(60)

# --- ENTRY POINT ---
if __name__ == "__main__":
    start_scheduler()