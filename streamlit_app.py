import streamlit as st
from datetime import datetime, timedelta
from controller import run_logistics_check

# --- STREAMLIT CONFIGURATON ---
st.set_page_config( 
    page_title="Logistics Disruption Monitor",
    layout="wide"
)

# --- SIDEBAR(SELECTION OF COUNTRIES) ---
with st.sidebar:
    st.header("Monitoring Settings")

    countries = [
        ("Mozambique", "moz"),
        ("Philippines", "phl"),
        ("South Africa", "zaf"),
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

# --- MAIN UI --#  
if st.button("Run Logistics Check", type="primary",):
    with st.spinner(f"Scanning {country_name} for {date_display}..."):
        result = run_logistics_check(
            country_name=country_name,
            country_code=country_code,
            from_date_str=from_date_str,
            date_display=date_display,
            date_mode=date_mode,
            selected_date=selected_date if date_mode == "Single date" else None,
            start_date=start_date if date_mode == "Date range" else None,
            end_date=end_date if date_mode == "Date range" else None
        )

        st.subheader("Alert")
        st.markdown(result)
   