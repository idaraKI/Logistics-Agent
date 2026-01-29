import streamlit as st
import os
import requests
from datetime import datetime
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from tavily import TavilyClient
from datetime import datetime, timedelta


load_dotenv()

NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
COUNTRY = "za"

# --- STREAMLIT CONFIGURATON ---
st.set_page_config(
    page_title="Logistics Disruption Monitor",
    layout="wide"
)
st.title("Logistics Risk Agent")
st.caption("Logistics Disruption Monitor")

# ---  MODELS ---
LLM = ChatOpenAI(model="gpt-4o-mini", temperature=0)

tavily = TavilyClient(api_key=TAVILY_API_KEY)

# --- PROMPTS ---
prompt = PromptTemplate(
    input_variables=["events"],
    template="""
You are a logistics analyst for South Africa.

Analyze the following events and report ONLY those that are actively happening RIGHT NOW
and are currently disrupting package delivery or transport.

For each event:
- Assign severity: LOW, MEDIUM, HIGH
- Describe the actual impact on package delivery
- Ignore events that are potential, past, or irrelevant

Events:
{events}

Format:
Event:
Severity:
Impact on package delivery:
"""
)

chain = prompt | LLM | StrOutputParser()

# --- FILTER KEYWORDS ---
ACTIVE_KEYWORDS = [
    "border closed", "port closed", "strike ongoing", "road blocked",
    "shipment delayed", "warehouse fire", "customs backlog",
    "transport disruption", "freight delay", "package delay"
]

def filter_active_events(events):
    filtered = []
    for e in events:
        if any(k.lower() in e.lower() for k in ACTIVE_KEYWORDS):
            filtered.append(e)
    return filtered

# --- FIRST DATA SOURCE ---
NEWSDATA_URL = "https://newsdata.io/api/1/news"

def fetch_newsdata():
    try:
        yesterday = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        params = {
            "apikey": NEWSDATA_API_KEY,
            "country": "za",
            "language": "en",
            "from_date": yesterday,
            "q": "strike OR port OR transport OR shipment OR delivery OR customs OR warehouse"
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
            query="South Africa holiday strike protest port disruption transport delay custom shipment",
            search_depth="advanced",
            max_results=10
        )
        return [r.get("content", "") for r in result.get("results", [])]
    except Exception as e:
        st.error(f"Tavily fetch failed: {e}")
        return []

# --- COMBINE AND REMOVE DUPLICATES ---
def get_new_headlines():
    newsdata_articles = fetch_newsdata()
    tavily_event = fetch_tavily()

    all_headlines = list(set(tavily_event + newsdata_articles))
    active_events = filter_active_events(all_headlines)

    if not active_events:
        return None
    
    return chain.invoke({"events": "\n".join(all_headlines)})

# --- SIDE BAR ---
st.sidebar.header("Controls")
run_now = st.sidebar.button("Run Logistics Check")

# --- MAIN UI ---
if run_now:
    with st.spinner("Fetching active disruptions..."):
        report = get_new_headlines()
        st.subheader("📊 Active Logistics Disruption Report")
        if report:
            # Simple color-coded severity highlighting
            for block in report.split("\n\n"):
                if "HIGH" in block:
                    st.markdown(f"<div style='background-color:#ff4c4c;padding:10px;border-radius:5px'>{block}</div>", unsafe_allow_html=True)
                elif "MEDIUM" in block:
                    st.markdown(f"<div style='background-color:#ffcc00;padding:10px;border-radius:5px'>{block}</div>", unsafe_allow_html=True)
                elif "LOW" in block:
                    st.markdown(f"<div style='background-color:#90ee90;padding:10px;border-radius:5px'>{block}</div>", unsafe_allow_html=True)
                else:
                    st.text(block)
            st.success(f"Last updated: {datetime.now()}")
        else:
            st.info("No active disruptions detected at this time.")