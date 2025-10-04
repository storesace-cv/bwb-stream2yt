#!/usr/bin/env python3
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import json, sys

SCOPES=["https://www.googleapis.com/auth/youtube.readonly","https://www.googleapis.com/auth/youtube"]
TOKEN="/root/token.json"

def main():
    creds = Credentials.from_authorized_user_file(TOKEN, SCOPES)
    yt=build("youtube","v3",credentials=creds, cache_discovery=False)
    b = yt.liveBroadcasts().list(part="id,contentDetails,status", mine=True, maxResults=5).execute()
    items = b.get("items", [])
    live = next((it for it in items if it.get("status",{}).get("lifeCycleStatus") in ("live","testing")), None)
    if not live:
        print("Sem broadcast live/testing visível pela API."); return 0
    sid = live["contentDetails"]["boundStreamId"]
    s = yt.liveStreams().list(part="id,status,cdn", id=sid).execute()
    st = s["items"][0]; hs = st["status"].get("healthStatus", {})
    print(json.dumps({
      "streamStatus": st["status"].get("streamStatus"),
      "healthStatus.status": hs.get("status"),
      "issues": hs.get("configurationIssues", []),
      "cdn": st.get("cdn",{}),
    }, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    sys.exit(main() or 0)
