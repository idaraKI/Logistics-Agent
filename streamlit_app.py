import streamlit as st
import os
import requests
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from tavily import TavilyClient
from datetime import datetime, timedelta

if os.path.exists(".env"):  
    load_dotenv()

NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- STREAMLIT CONFIGURATON ---
st.set_page_config( 
    page_title="Logistics Disruption Monitor",
    layout="wide"
)

# --- SIDEBAR(SELECTION OF COUNTRIES) ---
with st.sidebar:
    st.header("Monitoring Settings")

    countries = [
        ("South Africa", "za"),
        ("Kenya", "ke"),
        ("Colombia", "co"),
        ("United Kingdom", "gb"),
        ("Brazil", "br"),
        ("India", "in"),
        ("Morocco", "ma"),
        ("Egypt", "eg"),
        ("Nigeria", "ng"),
    ]

    selected = st.selectbox(
        "Country to monitor",
        options=countries,
        format_func=lambda x: x[0],
        index=0
    )

    country_name, country_code = selected
    st.caption(f"Selected: {country_name} ({country_code})")

    # --- DATE SELECTION ---
    date_mode = st.radio(
        "Date mode",
        options=["Single date", "Date range"],
        horizontal=True,
        index=0
    )
    
    today = datetime.today().date()
    default_start = today - timedelta(days=7)   # last week by default
    
    if date_mode == "Single date":
        selected_date = st.date_input(
            "Check events as of",
            value=today,
            max_value=today,                    # cannot select future
            help="News will be fetched from this date backwards"
        )
        from_date_str = selected_date.strftime("%Y-%m-%d")
        date_display = selected_date.strftime("%B %d, %Y")
    else:
        date_range = st.date_input(
            "Date range",
            value=(default_start, today),
            min_value=default_start - timedelta(days=30),
            max_value=today,
            help="Fetch events in this period"
        )
        if len(date_range) == 2:
            start_date, end_date = date_range
            from_date_str = start_date.strftime("%Y-%m-%d")
            date_display = f"{start_date.strftime('%B %d, %Y')} –{end_date.strftime('%B %d, %Y')}"
        else:
            # Incomplete range – fallback to single today
            from_date_str = today.strftime("%Y-%m-%d")
            date_display = today.strftime("%B %d, %Y")
    
    st.caption(f"Period: {date_display}")

st.title("Logistics Risk Agent")
st.caption("Logistics Disruption Monitor")

# ---  MODELS ---
LLM = ChatOpenAI(model="gpt-4o-mini", temperature=0)

tavily = TavilyClient(api_key=TAVILY_API_KEY)

# --- PROMPTS ---
prompt = PromptTemplate.from_template(
    """
You are a logistics analyst for {country_name}.

Time period: {date_display}

Analyze the following events/news items.

Report **only** the items that have a realistic current or near-term impact on:
- package / freight delivery
- road / port / airport / rail transport
- customs clearance
- warehousing
- strikes / protests / blockades affecting logistics

Ignore:
- pure political news without transport impact
- weather / accidents without confirmed logistics effect
- very old events without ongoing consequences
- general news not related to freight movement

For each relevant event:
- Severity: LOW, MEDIUM, HIGH
- Short description of impact on logistics

Also mention any public holidays or closures that could affect operations.

Events:
{events}

Format:
Disruption:
Severity:
Impact:

Holiday / Closure Note (if applicable):
"""
)

chain = prompt | LLM | StrOutputParser()

# --- FIRST DATA SOURCE ---
NEWSDATA_URL = "https://newsdata.io/api/1/news"

def fetch_newsdata():
    try:
        params = {
            "apikey": NEWSDATA_API_KEY,
            "country": country_code,
            "language": "en",
            "from_date": from_date_str,
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
        query = f"{country_name} disruption transport delay customs port strike holiday closure since:{from_date_str}"
        result = tavily.search(
            query =query,
            search_depth="advanced",
            max_results=10
        )
        return [r.get("content", "") for r in result.get("results", [])]
    except Exception as e:
        st.error(f"Tavily fetch failed: {e}")
        return []

# --- MAIN UI ---
if st.button("Run Logistics Check", type="primary"):
    with st.spinner(f"Scanning {country_name} for {date_display}..."):
        # Fetch data
        news_items = fetch_newsdata()
        tavily_items = fetch_tavily()

        # --- COMBINE AND REMOVE DUPLICATES —--
        all_items = news_items + tavily_items

        if not all_items:
            st.info("No events found in the selected period from either source.")
        else:
            try:
                report = chain.invoke({
                    "events": "\n\n".join(all_items),
                    "country_name": country_name,
                    "date_display": date_display
                })

                st.subheader("Logistics Disruption & Holiday Report")

                st.markdown(report)

                st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S WAT')}")
            except Exception as e:
                st.error(f"Report generation failed: {str(e)}")


            
           
           