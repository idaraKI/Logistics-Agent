import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, date, timedelta
from typing import Optional
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pycountry
from dotenv import load_dotenv
from controller import run_logistics_check, fetch_holidays, fetch_gdacs_rss, fetch_latest_news

load_dotenv()

logger = logging.getLogger(__name__)

ALERT_COUNTRIES  = os.getenv("ALERT_COUNTRIES", "ir").split(",")


# --- Request / Response Models ---
class LogisticsRequest(BaseModel):
    country_name: str
    country_code: str
    from_date_str: str
    date_display: str
    date_mode: str  # "Single date" or "Date range"
    selected_date: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class HolidayItem(BaseModel):
    Name: str
    Date: str

class ActiveAlert(BaseModel):
    Title: str
    Severity: str
    Summary: str
    Source: str

class LogisticsResponse(BaseModel):
    Country: str
    Date: str
    Time: str
    Holidays: list[HolidayItem]
    Next_Holiday: Optional[str] = None
    Active_Alerts: list[ActiveAlert]
    status: str = "success"


class HolidayRequest(BaseModel):
    country: str
    country_code: str
    date: date

class Holiday(BaseModel):
    Type: str
    Date: str 

class HolidayResponse(BaseModel):
    Country: str
    Holidays: list[Holiday]
    CurrentTime: str
    status: str = "success"


class DisasterRequest(BaseModel):
    country: str
    country_code: str
    from_date: date
    to_date: date

class DisasterEvent(BaseModel):
    Disaster_Type: str
    Event_Summary: str
    Logistics_Impact: str
    Date: str
    Severity: str
    Source: str

class DisasterResponse(BaseModel):
    Country: str
    From_Date: str
    To_Date: str
    Total_Events: int
    Events: list[DisasterEvent]
    Current_Timestamp: str
    status: str = "success"

# --- Build message ---
def build_message(country_code, check_date, llm_output):
    lines = [
        f" *Logistics Daily Alert*",
        f"Country: {country_code.upper()}",
        f"Date: {check_date.strftime('%d/%m/%Y')}",
        f"Time: {datetime.now().strftime('%H:%M:%S')}",
        f"",
    ]
    if "NO_DISRUPTION_EVENTS" in llm_output:
        lines.append(" No logistics disruption events found for today.")
    else:
        lines.append("Active Alerts:")
        lines.append(llm_output)
    return "\n".join(lines)


# --- Daily check ---
def run_daily_check():
    logger.info("SCHEDULER | Running daily logistics check")
    today = date.today()

    for country_code in ALERT_COUNTRIES:
        country_code = country_code.strip()
        logger.info(f"SCHEDULER | Checking {country_code}")

        try:
            import pycountry
            c = pycountry.countries.get(alpha_2=country_code.upper())
            country_name = getattr(c, "common_name", None) or getattr(c, "name", None) or country_code

            result = run_logistics_check(
                country_name=country_name,
                country_code=country_code,
                from_date_str=str(today),
                date_display=today.strftime("%d/%m/%Y"),
                date_mode="Single date",
                selected_date=today,
                start_date=today,
                end_date=today
            )

            message = build_message(country_code, today, result)
            logger.info(f"SCHEDULER | Alert for {country_code.upper()}:\n{message}")


        except Exception as e:
            logger.error(f"SCHEDULER | Failed for {country_code}: {e}")

# --- Scheduler ---
def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_daily_check,
        trigger=CronTrigger(hour=7, minute=0),
        id="daily_logistics_check",
        name="Daily Logistics Check",
        replace_existing=True
    )
    scheduler.start()
    logger.info("SCHEDULER | Started — daily check at 07:00 AM")
    return scheduler


# --- Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


# --- App ---
app = FastAPI(
    title="Logistics Disruption Monitor API",
    description="API for monitoring logistics risks, holidays, and disasters",
    version="1.0.0",
    lifespan=lifespan
)

# --- Endpoint 1 (Full Logistics Check)---
@app.post("/check", response_model=LogisticsResponse)
async def check_logistics_risk(request: LogisticsRequest):
    """
    Full logistics report — combines public holidays and disruption events
    into a single LLM-generated summary.
    """
    try:
        result = run_logistics_check(
            country_name=request.country_name,
            country_code=request.country_code,
            from_date_str=request.from_date_str,
            date_display=request.date_display,
            date_mode=request.date_mode,
            selected_date=request.selected_date,
            start_date=request.start_date,
            end_date=request.end_date
        )
        
        print("RAW LLM OUTPUT:")
        print(result)
        print("---END---")

         # Parse holidays
        holidays = []
        next_holiday = None
        alerts = []

        for line in result.splitlines():
            line = line.strip()

            # Skip lines that are just "None"
            if line in ("Holidays: None", "Active_Alerts: None", "Next_Holiday: None"):
                continue

            # Parse holiday lines: - Name: Easter | Date: 18/04/2026
            if line.startswith("- Name:") and "Date:" in line:
                parts = line.lstrip("- ").split("|")
                name  = parts[0].replace("Name:", "").strip()
                hdate = parts[1].replace("Date:", "").strip() if len(parts) > 1 else "N/A"
                holidays.append(HolidayItem(Name=name, Date=hdate))

            # Parse next holiday: Next_Holiday: Easter | 18/04/2026
            elif line.startswith("Next_Holiday:"):
                next_holiday = line.replace("Next_Holiday:", "").strip()

            # Parse alert lines: - Title: ... | Severity: ... | Summary: ... | Source: ...
            elif line.startswith("- Title:") and "Severity:" in line:
                parts    = line.lstrip("- ").split("|")
                title    = parts[0].replace("Title:", "").strip()    if len(parts) > 0 else "N/A"
                severity = parts[1].replace("Severity:", "").strip() if len(parts) > 1 else "N/A"
                summary  = parts[2].replace("Summary:", "").strip()  if len(parts) > 2 else "N/A"
                source   = parts[3].replace("Source:", "").strip()   if len(parts) > 3 else "N/A"
                alerts.append(ActiveAlert(Title=title, Severity=severity, Summary=summary, Source=source))

        return LogisticsResponse(
            Country=request.country_name,
            Date=datetime.strptime(request.from_date_str, "%Y-%m-%d").strftime("%d/%m/%Y"),
            Time=datetime.now().strftime("%H:%M:%S"),
            Holidays=holidays,
            Next_Holiday=next_holiday,
            Active_Alerts=alerts,
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Second endpoint(holiday only) ---
@app.post("/holidays", response_model=HolidayResponse)
async def check_holidays(request: HolidayRequest):
    try:
        target_year = request.date.year 
        holiday_list = fetch_holidays(request.country_code, target_year)


        from_date = request.date
        to_date = request.date + timedelta(days=7)

        formatted = []
        for h in holiday_list:
            parts = h.split(" | ")
            holiday_date = datetime.strptime(parts[0].strip(), "%Y-%m-%d").date()
            if from_date <= holiday_date <= to_date:
                formatted.append(Holiday(
                    Type=parts[1].strip() if len(parts) > 1 else "Unknown",
                    Date=holiday_date.strftime("%d/%m/%Y"),
                ))

        return HolidayResponse(
            Country=request.country,
            Holidays=formatted,
            CurrentTime=datetime.now().strftime("%H:%M:%S"),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Endpoint 3 — Disasters only (GDACS RSS + NewsData) ---
@app.post("/disasters", response_model=DisasterResponse)
async def check_disasters(request: DisasterRequest):
    try:
        gdacs_events = fetch_gdacs_rss(request.country_code, request.from_date, request.to_date)
        news_events  = fetch_latest_news(request.country_code, request.from_date, request.to_date)
        all_events   = gdacs_events + news_events 

            # Map short codes to full names
        type_map = {
            "WF":   "Wildfire",
            "FL":   "Flood",
            "EQ":   "Earthquake",
            "TC":   "Tropical Cyclone",
            "VO":   "Volcano",
            "DR":   "Drought",
            "NEWS": "News Event",
        }
        if not all_events:
            return DisasterResponse(
                Country=request.country_code.upper(),
                From_Date=str(request.from_date),
                To_Date=str(request.to_date),
                Total_Events=0,
                Events=[],
                Current_Timestamp=datetime.now().strftime("%H:%M:%S"),
            )

        # Pass all events through disaster LLM to filter logistics-relevant ones
        from controller import disaster_chain
        filtered_output = disaster_chain.invoke({
            "events":       "\n\n".join(all_events),
            "country_name": request.country,
            "date_display": f"{request.from_date} to {request.to_date}",
            "current_time": datetime.now().strftime("%H:%M:%S")
        })

        print("RAW DISASTER LLM OUTPUT:")
        print(filtered_output)
        print("---END---")

        parsed_events = []
        current_event = {}

        for line in filtered_output.splitlines():
            line = line.strip()
            if line.startswith("Country:"):
               if current_event.get("type"):
                  parsed_events.append(current_event)
                  current_event = {}
            elif line.startswith("Date:"):
                 current_event["date"] = line.replace("Date:", "").strip()
            elif line.startswith("Incident_Type:"):
                 current_event["type"] = line.replace("Incident_Type:", "").strip()
            elif line.lower().startswith  ("event_summary:"):
                 current_event["event_summary"] = line.split(":", 1)[1].strip()
            elif line.startswith("Logistics_Impact:"):
                 current_event["logistics_impact"] = line.replace("Logistics_Impact:", "").strip()
            elif line.startswith("Severity:"):
                 current_event["severity"] = line.replace("Severity:", "").strip()
            elif line == "---":
                 if current_event.get("type"):
                    parsed_events.append(current_event)
                 current_event = {}

        if current_event.get("type"):
           parsed_events.append(current_event)

        # Catch last event
        if current_event.get("type"):
            parsed_events.append(current_event)

        # Filter out NO_DISRUPTION_EVENTS
        parsed_events = [e for e in parsed_events if e.get("type") != "NO_DISRUPTION_EVENTS"]

        # ADD THIS — deduplicate by event_summary
        seen = set()
        unique_events = []
        for e in parsed_events:
            key = e.get("event_summary", "")
            if key not in seen:
               seen.add(key)
               unique_events.append(e)
        parsed_events = unique_events

        events = [
            DisasterEvent(
                Disaster_Type=type_map.get(e.get("type", ""), e.get("type", "Unknown")),
                Event_Summary=e.get("event_summary", "N/A"),
                Logistics_Impact=e.get("logistics_impact", "N/A"),
                Date=e.get("date", "N/A"),
                Severity=e.get("severity", "N/A"),
                Source="GDACS/GUARDIAN",
    )
    for e in parsed_events

]

        return DisasterResponse(
            Country=request.country_code.upper(),
            From_Date=str(request.from_date),
            To_Date=str(request.to_date),
            Total_Events=len(events),
            Events=events,
            Current_Timestamp=datetime.now().strftime("%H:%M:%S"),
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Trigger alert manually ---
@app.post("/trigger-alert")
async def trigger_alert():
    try:
        run_daily_check()
        return {"status": "success", "message": "Daily check triggered manually"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# --- Health check ---
@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now()}


# --- Entry point ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
