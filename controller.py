import os
import requests
import pycountry
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import logging

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d\n--> %(message)s\n",
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('data_log.log', mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY")
if not OPENROUTER_API_KEY:
    raise ValueError("Missing OPENROUTER_API_KEY in .env file.")
if not NEWSDATA_API_KEY:
    raise ValueError("Missing NEWSDATA_API_KEY in .env file.")


# --- MODELS ---
HOLIDAY_LLM  = ChatOpenAI(model="anthropic/claude-3.5-sonnet",   temperature=0,   base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
DISASTER_LLM = ChatOpenAI(model="google/gemini-2.0-flash-001",   temperature=0,   base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
SUMMARY_LLM  = ChatOpenAI(model="openai/gpt-4o-mini",            temperature=0.2, base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)


# --- PROMPTS ---
holiday_chain = PromptTemplate.from_template("""
You are a public holiday database.
Known holidays: {known_holidays}
For {country_name} ({country_code}), period {date_start} to {date_end}:
Return ONLY holidays in this format: YYYY-MM-DD | Holiday Name
If none, return: NO_PUBLIC_HOLIDAYS
Do not guess or add explanations.
""") | HOLIDAY_LLM | StrOutputParser()

disaster_chain = PromptTemplate.from_template("""
You are a logistics disruption analyst.
Country: {country_name} | Period: {date_display}
Events below are real and recorded — report ALL of them.
Format each as: SEVERITY | TYPE | Event name | Logistics impact | Date | Source
If none, return: NO_DISRUPTION_EVENTS
Events:
{events}
""") | DISASTER_LLM | StrOutputParser()

summary_chain = PromptTemplate.from_template("""
You are a logistics alert writer.
Write 2-3 sentences. Be specific — include event names, dates, what is affected.
Country: {country_name} | Period: {date_display}
Data: {processed_input}
""") | SUMMARY_LLM | StrOutputParser()


# --- COUNTRY HELPERS ---
def _resolve(code):
    code = code.strip().upper()
    return pycountry.countries.get(alpha_3=code) if len(code) == 3 else pycountry.countries.get(alpha_2=code)

def to_iso2(code):
    c = _resolve(code)
    return c.alpha_2 if c and hasattr(c, "alpha_2") else code[:2].upper()

def _terms(code):
    """Lowercase name variants for matching against API text fields."""
    c = _resolve(code)
    if c:
        t = {c.name.lower(), c.alpha_3.lower()}
        if hasattr(c, "common_name"): t.add(c.common_name.lower())
        return t
    return {code.lower()}

def expand(from_date, to_date):
    """Expand single-day queries ±7 days so multi-day events are captured."""
    if isinstance(from_date, datetime): from_date = from_date.date()
    if isinstance(to_date, datetime):   to_date   = to_date.date()
    if from_date == to_date:
        from_date -= timedelta(days=7)
        to_date   += timedelta(days=7)
    return from_date, to_date


# --- GDACS RSS — real-time, all disaster types ---
GDACS_NS = {"gdacs": "http://www.gdacs.org"}

def fetch_gdacs_rss(country_code, from_date, to_date):
    from_date, to_date = expand(from_date, to_date)
    logger.info(f"GDACS-RSS | {country_code} | {from_date} to {to_date}")

    try:
        r = requests.get("https://www.gdacs.org/xml/rss.xml",
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        r.raise_for_status()
    except Exception as e:
        logger.error(f"GDACS-RSS | Failed: {e}")
        return []

    root  = ET.fromstring(r.content)
    terms = _terms(country_code)
    events = []

    for item in root.findall(".//item"):
        def g(tag, ns=None):
            el = item.find(f"{{{GDACS_NS[ns]}}}{tag}" if ns else tag)
            return el.text.strip() if el is not None and el.text else ""

        # Country match — check title and gdacs:country field
        title    = g("title")
        country  = g("country", "gdacs")
        if not any(t in (title + " " + country).lower() for t in terms):
            continue

        # Date filter
        fromdate_str = g("fromdate", "gdacs")
        try:
            event_date = datetime.strptime(fromdate_str[:16], "%a, %d %b %Y %H:%M").date()
            if not (from_date <= event_date <= to_date):
                continue
        except Exception:
            pass  # include if date unparseable

        events.append(
            f"SOURCE:GDACS | ALERT:{g('alertlevel','gdacs').upper()} | TYPE:{g('eventtype','gdacs').upper()} | {title}\n"
            f"  Date: {fromdate_str} | Country: {country}\n"
            f"  Details: {g('description')[:200]}\n"
            f"  Link: {g('link')}"
        )

    logger.info(f"GDACS-RSS | {len(events)} events matched")
    return events


# --- NEWSDATA API — news-based disaster & disruption coverage ---
def fetch_newsdata(country_code, from_date, to_date):
    from_date, to_date = expand(from_date, to_date)
    iso2 = to_iso2(country_code).lower()
    logger.info(f"NEWSDATA | {iso2} | {from_date} to {to_date}")

    # Search for logistics-relevant disaster/disruption news
    query = "flood OR cyclone OR earthquake OR volcano OR wildfire OR drought OR strike OR protest OR disaster"

    try:
        r = requests.get(
            "https://newsdata.io/api/1/news",
            params={
                "apikey":   NEWSDATA_API_KEY,
                "country":  iso2,
                "q":        query,
                "language": "en",
                "from_date": str(from_date),
                "to_date":   str(to_date),
            },
            timeout=20
        )
        r.raise_for_status()
    except Exception as e:
        logger.error(f"NEWSDATA | Failed: {e}")
        return []

    data    = r.json()
    results = data.get("results", [])
    logger.info(f"NEWSDATA | {len(results)} articles received")

    events = []
    for article in results:
        title       = article.get("title") or "No title"
        description = (article.get("description") or "")[:200]
        pub_date    = (article.get("pubDate") or "")[:10]
        source      = article.get("source_id") or "unknown"
        link        = article.get("link") or ""

        events.append(
            f"SOURCE:NEWSDATA | ALERT:NEWS | TYPE:NEWS | {title}\n"
            f"  Date: {pub_date} | Source: {source}\n"
            f"  Details: {description}\n"
            f"  Link: {link}"
        )

    logger.info(f"NEWSDATA | {len(events)} articles formatted")
    return events


# --- HOLIDAYS ---
def fetch_holidays(country_code, year):
    iso2 = to_iso2(country_code)
    logger.info(f"NAGER | {iso2} | {year}")
    try:
        r = requests.get(f"https://date.nager.at/api/v3/PublicHolidays/{year}/{iso2}", timeout=10)
        r.raise_for_status()
        hits = [f"{h['date']} | {h['name']}" for h in r.json() if h.get("date") and h.get("name")]
        logger.info(f"NAGER | {len(hits)} holidays found")
        return hits
    except Exception as e:
        logger.error(f"NAGER | Failed: {e}")
        return []


# --- MAIN ---
def run_logistics_check(country_name, country_code, from_date_str, date_display,
                        date_mode, selected_date=None, start_date=None, end_date=None):

    logger.info(f"RUN | {country_name} ({country_code}) | {date_display}")
    today = datetime.today().date()

    period_type = "future" if (
        (selected_date if date_mode == "Single date" else start_date) > today
    ) else "past_or_present"
    logger.info(f"RUN | period_type={period_type}")

    # Holidays
    year = from_date_str.split("-")[0]
    holiday_list = fetch_holidays(country_code, year)
    holiday_text = "\n".join(holiday_list) or "NO_PUBLIC_HOLIDAYS"
    base_date = datetime.strptime(from_date_str, "%Y-%m-%d").date()
    lookahead = str(base_date + timedelta(days=7))

    holiday_output = holiday_chain.invoke({
        "country_name": country_name, "country_code": country_code.upper(),
        "date_start": from_date_str,
        "date_end": lookahead,
        "known_holidays": holiday_text
    })
    logger.info("HOLIDAYS | Done")

    if period_type == "future":
        return holiday_output.strip()

    # Disasters — GDACS RSS + NewsData merged
    fd = selected_date if date_mode == "Single date" else start_date
    td = selected_date if date_mode == "Single date" else end_date

    all_events = fetch_gdacs_rss(country_code, fd, td) + fetch_newsdata(country_code, fd, td)
    logger.info(f"RUN | {len(all_events)} total events from all sources")

    if not all_events:
        disaster_output = "NO_DISRUPTION_EVENTS"
    else:
        disaster_output = disaster_chain.invoke({
            "events": "\n\n".join(all_events),
            "country_name": country_name, "date_display": date_display
        })
    logger.info("DISASTERS | Done")

    summary = summary_chain.invoke({
        "processed_input": f"=== HOLIDAYS ===\n{holiday_output}\n\n=== DISRUPTIONS ===\n{disaster_output}",
        "country_name": country_name, "date_display": date_display
    })
    logger.info(f"SUMMARY | Done — {len(summary)} chars")

    return summary.strip()