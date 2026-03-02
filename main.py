from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, date, timedelta
from typing import Optional
from dotenv import load_dotenv
from controller import run_logistics_check, fetch_holidays, fetch_gdacs_rss, fetch_newsdata

load_dotenv()

app = FastAPI(
    title="Logistics Disruption Monitor API",
    description="API for monitoring logistics risks, holidays, and disasters",
    version="1.0.0"
)

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

class DisasterResponse(BaseModel):
    Country: str
    Date: str
    Disaster_Type: str
    Disaster_Summary: str
    Current_Timestamp: str
    status: str = "success"

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
            Date=datetime.now().strftime("%d/%m/%Y"),
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
        news_events  = fetch_newsdata(request.country_code, request.from_date, request.to_date)
        all_events   = gdacs_events + news_events

        # Take the first event as the primary disaster report
        if all_events:
            event = all_events[0]
            lines = event.split("\n")

            # Line 0: SOURCE:GDACS | ALERT:RED | TYPE:WF | Event Title
            title_line = lines[0]
            disaster_type    = title_line.split("TYPE:")[-1].split("|")[0].strip()
            disaster_summary = title_line.split("|")[-1].strip()

            # Line 1: Date: ... | Country: ...
            date_line  = lines[1].strip() if len(lines) > 1 else ""
            event_date = date_line.split("Date:")[-1].split("|")[0].strip() if "Date:" in date_line else "N/A"

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
            disaster_type = type_map.get(disaster_type, disaster_type)

        else:
            disaster_type    = "NO_DISRUPTION_EVENTS"
            disaster_summary = "No disruption events found for this period."
            event_date       = "N/A"

        return DisasterResponse(
            Country=request.country_code.upper(),
            Date=event_date,
            Disaster_Type=disaster_type,
            Disaster_Summary=disaster_summary,
            Current_Timestamp=datetime.now().strftime("%H:%M:%S"),
        )
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
