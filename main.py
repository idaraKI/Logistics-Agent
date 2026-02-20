from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional
from dotenv import load_dotenv
from controller import run_logistics_check

load_dotenv()

app = FastAPI(
    title="Logistics Disruption Monitor API",
    description="API for monitoring logistics risks, holidays, and disasters",
    version="1.0.0"
)

class CheckRequest(BaseModel):
    country_name: str
    country_code: str
    from_date_str: str
    date_display: str
    date_mode: str  # "Single date" or "Date range"
    selected_date: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None

class CheckResponse(BaseModel):
    alert: str
    status: str = "success"
    timestamp: datetime

@app.post("/check", response_model=CheckResponse)
async def check_logistics_risk(request: CheckRequest):
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
        
        return CheckResponse(
            alert=result,
            timestamp=datetime.now()
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.now()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
