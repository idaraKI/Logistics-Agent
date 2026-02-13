import streamlit as st
import os
import requests
import httpx
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
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

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
    
    if date_mode == "Single date":
        selected_date = st.date_input(
            "Check events as of",
            value=today,
            help="News will be fetched from this date backwards"
        )
        from_date_str = selected_date.strftime("%Y-%m-%d")
        date_display = selected_date.strftime("%B %d, %Y")
        
    else:
        default_start = today - timedelta(days=7)
        date_range = st.date_input(
            "Date range (max 7 days)",
            value=(today, today),
            #min_value=today - timedelta(days=800),
            max_value=today + timedelta(days=800),
            help="You can select up to 7 days at a time"
        )
        if len(date_range) == 2:
            start_date, end_date = date_range
            # Enforce max 7-day span
            if (end_date - start_date).days > 7:
                st.warning("Maximum range is 7 days.")
                end_date = start_date + timedelta(days=6)
                # Force widget update (Streamlit limitation workaround)
                st.session_state["date_range"] = (start_date, end_date)
                st.rerun()

            from_date_str = start_date.strftime("%Y-%m-%d")
            date_display = f"{start_date.strftime('%B %d, %Y')} – {end_date.strftime('%B %d, %Y')}"
            
        else:
            # Incomplete selection → fallback to today
            from_date_str = today.strftime("%Y-%m-%d")
            date_display = today.strftime("%B %d, %Y")
           
    st.caption(f"Period: {date_display}")

st.title("Logistics Risk Agent")
st.caption("Logistics Disruption Monitor")

# ---  MODELS ---
HOLIDAY_LLM = ChatOpenAI(
    model="anthropic/claude-3.5-sonnet",
    temperature=0,
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    client=httpx.Client(timeout=60.0)
)

DISASTER_LLM = ChatOpenAI(
    model="google/gemini-2.0-flash-001",
    temperature=0,
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    client=httpx.Client(timeout=60.0)
)

SUMMARY_LLM = ChatOpenAI(
    model="openai/gpt-4o-mini",
    temperature=0.2,
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    client=httpx.Client(timeout=60.0)
)

tavily = TavilyClient(api_key=TAVILY_API_KEY)
print("API Key:", os.getenv("OPENROUTER_API_KEY"))

# --- PROMPTS ---
holiday_prompt = PromptTemplate.from_template(
    """
You are a global public holiday database.

For {country_name} ({country_code})
and date range {date_start} to {date_end},

Return ONLY a list of official public holidays in this exact format:
YYYY-MM-DD|\n Holiday Name 

If no holidays in the period → return exactly one line:
NO_PUBLIC_HOLIDAYS

Do NOT add explanations, do NOT guess dates.

Period: {date_start} to {date_end}
"""
)

holiday_chain = holiday_prompt | HOLIDAY_LLM | StrOutputParser()

disaster_prompt = PromptTemplate.from_template(
    """
You are an early-warning disaster & event monitor.

Read the following news/social/web items from {country_name}
in period {date_display}.

Return ONLY events that are:
- natural disasters (flood, storm, earthquake, wildfire, etc.)
- major transport disruptions (port closure, strike, border issue, etc.)
- other high-impact events (protests, accidents, supply chain crisis)

Format each as :
EVENT_TYPE |\n short description |\n current impact level (HIGH/MEDIUM/LOW) | source snippet

If no relevant events → return exactly:
NO_DISASTER_OR_MAJOR_EVENTS

Items:
{events}
"""
)

disaster_chain = disaster_prompt | DISASTER_LLM | StrOutputParser()

summary_prompt = PromptTemplate.from_template(
    """
You are a concise logistics alert writer.

Input contains filtered  events, disasters, and/or holiday.


Turn them into a very short alert (2 sentences maximum).
Be direct, urgent, and factual.


Input:
{holiday_output}
{disaster_output}

Country: {country_name}
Time period: {date_display}
"""
)

summary_chain = summary_prompt | SUMMARY_LLM | StrOutputParser()

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
            query=query,
            search_depth="advanced",
            max_results=10
        )
        return [r.get("content", "") for r in result.get("results", [])]
    except Exception as e:
        st.error(f"Tavily fetch failed: {e}")
        return []




# --- MAIN UI --#  
if st.button("Run Logistics Check", type="primary",):
    with st.spinner(f"Scanning {country_name} for {date_display}..."):

        today = datetime.today().date()

        # ----- DETERMINE PERIOD TYPE -----
        if date_mode == "Single date":
            period_type = "future" if selected_date > today else "past_or_present"
        else:
            period_type = "future" if start_date > today else "past_or_present"

        

        # --- ALWAYS RUN HOLIDAY LLM ---
        holiday_output = holiday_chain.invoke({
            "country_name": country_name,
            "country_code": country_code.upper(),
            "date_start": from_date_str,
            "date_end": date_display.split(" – ")[-1].strip()
            if " – " in date_display else from_date_str
        })

        # 2️⃣ FUTURE → Only holidays
        if period_type == "future":
            disaster_output = "NO_DISASTER_OR_MAJOR_EVENTS"
        else:

        # Fetch data
            news_items = fetch_newsdata()
            tavily_items = fetch_tavily()

            # --- COMBINE AND REMOVE DUPLICATES —--
            all_items = news_items + tavily_items

            if not all_items:
                disaster_output = "NO_DISASTER_OR_MAJOR_EVENTS"
            else:
                disaster_output = disaster_chain.invoke({
                    "events": "\n\n".join(all_items),
                    "country_name": country_name,
                    "date_display": date_display
                })
        print(holiday_output,disaster_output)

        # --- SUMMARY_OUTPUT ---
        summary_output = summary_chain.invoke({
            "holiday_output": holiday_output,
            "disaster_output": disaster_output,
            "country_name": country_name,
            "date_display": date_display
        })

        st.subheader("ALERT")
        st.markdown(summary_output.strip())
   
           

        


               

                   

               
       