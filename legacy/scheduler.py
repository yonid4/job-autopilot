import time
from datetime import datetime
from zoneinfo import ZoneInfo

from legacy.config import Config as config
from legacy import main as job_main

PST = ZoneInfo("America/Los_Angeles")
START_HOUR = 5   # 5am PST
END_HOUR   = 18  # 6pm PST

def in_window() -> bool:
    now = datetime.now(PST)
    return START_HOUR <= now.hour < END_HOUR

def run():
    interval = config.HOURS_OLD * 3600
    print(f"Scheduler started. Running every {config.HOURS_OLD}h between {START_HOUR}am–{END_HOUR - 12}pm PST.")
    while True:
        if in_window():
            print(f"[{datetime.now(PST).strftime('%H:%M PST')}] Running job scrape...")
            job_main.main()
        else:
            print(f"[{datetime.now(PST).strftime('%H:%M PST')}] Outside window, skipping.")
        time.sleep(interval)

if __name__ == "__main__":
    run()
