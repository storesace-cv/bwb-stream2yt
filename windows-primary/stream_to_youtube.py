#!/usr/bin/env python3
import os, time, datetime, subprocess, shlex, sys

def is_daytime(now=None, tz_offset_hours=0, start=8, end=19):
    now = now or datetime.datetime.utcnow()
    local = now + datetime.timedelta(hours=tz_offset_hours)
    return start <= local.hour < end

def main():
    yt_url = os.getenv("YT_URL", "").strip()
    if not yt_url:
        print("[stream_to_youtube] ERRO: defina YT_URL (rtmps://a.rtmps.youtube.com/live2/<KEY>)")
        sys.exit(2)

    tz = int(os.getenv("YT_TZ_OFFSET_HOURS", "1"))
    start = int(os.getenv("YT_DAY_START_HOUR", "8"))
    end = int(os.getenv("YT_DAY_END_HOUR", "19"))

    input_args = os.getenv("YT_INPUT_ARGS", "-re -f lavfi -i testsrc2=size=1280x720:rate=30")
    output_args = os.getenv("YT_OUTPUT_ARGS", "-c:v libx264 -preset veryfast -pix_fmt yuv420p -b:v 2500k -g 60 -c:a aac -b:a 128k -ar 48000 -ac 2")

    print(f"[stream_to_youtube] Enviando para: {yt_url}")
    while True:
        if is_daytime(tz_offset_hours=tz, start=start, end=end):
            cmd = f'ffmpeg -hide_banner -loglevel warning {input_args} -f flv "{yt_url}"'
            print(f"[stream_to_youtube] START ffmpeg: {cmd}")
            try:
                subprocess.run(shlex.split(cmd), check=False)
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"[stream_to_youtube] Exceção: {e}")
                time.sleep(5)
        else:
            print("[stream_to_youtube] Fora do horário: a app mantém-se ativa, sem enviar.")
            time.sleep(30)

if __name__ == "__main__":
    main()
