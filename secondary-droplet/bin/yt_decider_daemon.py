#!/usr/bin/env python3
# yt_decider_daemon.py — production decider (simplified, tuned for current deployment)
import os, time, csv, datetime, sys
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from subprocess import run, CalledProcessError

SCOPES=["https://www.googleapis.com/auth/youtube.readonly","https://www.googleapis.com/auth/youtube"]
TOKEN="/root/token.json"
CSV="/root/yt_decider_log.csv"
CYCLE=20  # seconds
COOLDOWN=10  # seconds

DAY_START=8
DAY_END=19
TZ_OFFSET=1  # Luanda

def local_hour():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=TZ_OFFSET)).hour

def build_api():
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    return build("youtube","v3",credentials=creds, cache_discovery=False)

def get_state(yt):
    b = yt.liveBroadcasts().list(part="id,contentDetails,status", mine=True, maxResults=5).execute()
    items = b.get("items", [])
    live = next((it for it in items if it.get("status",{}).get("lifeCycleStatus") in ("live","testing")), None)
    if not live:
        return {"streamStatus":"?", "health":"?", "note":"sem broadcast"}
    sid = live["contentDetails"]["boundStreamId"]
    s = yt.liveStreams().list(part="id,status,cdn", id=sid).execute()
    st = s["items"][0]
    hs = st["status"].get("healthStatus",{})
    return {
        "streamStatus": st["status"].get("streamStatus"),
        "health": hs.get("status","?"),
        "note": ""
    }

def csv_log(row):
    exists = os.path.exists(CSV)
    with open(CSV,"a",newline="",encoding="utf-8") as f:
        w=csv.writer(f); 
        if not exists: w.writerow(["cycle","hora","streamStatus","health","acao","detalhe"])
        w.writerow(row)

def is_active(unit):
    return run(["systemctl","is-active",unit], capture_output=True, text=True).returncode==0

def start_fallback():
    run(["systemctl","enable","--now","youtube-fallback.service"], check=False)

def stop_fallback():
    run(["systemctl","stop","youtube-fallback.service"], check=False)

def main():
    print("== yt_decider_daemon — PRODUÇÃO (STOP diurno quando primário OK) ==")
    cycle=0
    while True:
        cycle+=1
        try:
            yt = build_api()
            st = get_state(yt)
        except Exception as e:
            csv_log([cycle, datetime.datetime.now().strftime("%H:%M"),"?","?","KEEP", f"exc: {e.__class__.__name__}"])
            time.sleep(CYCLE); continue

        hr = local_hour()
        ss, hh = st["streamStatus"], st["health"]
        fb_on = is_active("youtube-fallback.service")

        action = "KEEP"; detail = st["note"] or ""
        # Night: 19:00–08:00 keep fallback if no primary
        if not (DAY_START <= hr < DAY_END):
            if ss in ("inactive","?") or hh in ("noData","?","bad"):
                if not fb_on: start_fallback(); action="START secondary"; detail="night + no primary"
            else:
                action="KEEP"
        else:
            # Day: stop fallback if primary OK, else keep/start
            if ss=="active" and hh in ("good","ok"):
                if fb_on: stop_fallback(); action="STOP secondary"; detail="day primary OK"
            else:
                if not fb_on: start_fallback(); action="START secondary"; detail="day but no primary"

        csv_log([cycle, datetime.datetime.now().strftime("%H:%M"), ss, hh, action, detail])
        time.sleep(CYCLE)

if __name__=="__main__":
    main()
