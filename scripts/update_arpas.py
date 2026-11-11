"""Aggiorna il bollettino marino ARPAS; non sovrascrive dati validi se il parsing fallisce."""
import datetime as dt
import json
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URL = 'https://www.sar.sardegna.it/servizi/meteo/prevmare_new.asp'
OUT = Path(__file__).resolve().parents[1] / 'data' / 'arpas_mare.json'
MONTHS = dict(zip('gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre'.split(), range(1, 13)))
SLOTS = ['00:00-06:00', '06:00-12:00', '12:00-18:00', '18:00-24:00']
ZONE = r'(?:60\s+NW|60\s+N|61\s+NE|62\s+W|63\s+SE|64\s+SW|64\s+S)'
STATE = r'(?:Molto\s+mosso|Poco\s+mosso|Calmo|Quasi\s+calmo|Mosso|Agitato|Molto\s+agitato|Grosso|Molto\s+grosso|Tempestoso|N\.D\.)'
NUM = r'(?:\d+(?:[.,]\d+)?|N\.D\.)'
DIRECTION = r'(?:N|NE|E|SE|S|SO|O|NO|N\.D\.)'
ROW = re.compile(rf'(?<!\w)(?P<zone>{ZONE})\s+(?P<h1>{NUM})\s+(?P<d1>{NUM})\s+(?P<t1>{NUM})\s+(?P<dir1>{DIRECTION})\s+(?P<state1>{STATE})\s+(?P<h2>{NUM})\s+(?P<d2>{NUM})\s+(?P<t2>{NUM})\s+(?P<dir2>{DIRECTION})\s+(?P<state2>{STATE})(?!\w)', re.I)
DAY = re.compile(r'Previsione\s+per\s+\w+\s+(\d{1,2})\s+(\w+)\s+(\d{4})', re.I)
HALF = re.compile(r'Zona\s+(00:00\s*[-–]\s*06:00|12:00\s*[-–]\s*18:00)', re.I)

def extract(html):
    soup = BeautifulSoup(html, 'html.parser')
    # Unisci il testo con spazi: funziona anche se la pagina usa celle HTML diverse.
    raw = re.sub(r'\s+', ' ', soup.get_text(' ', strip=True))
    emitted = re.search(r'Emissione\s+del\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})', raw)
    if not emitted:
        raise ValueError('Data emissione ARPAS non trovata')
    issued = dt.datetime.strptime(' '.join(emitted.groups()), '%d/%m/%Y %H:%M:%S').isoformat()
    day_matches = list(DAY.finditer(raw))
    forecasts = []
    for j, day_match in enumerate(day_matches):
        d, month, y = day_match.groups()
        if month.lower() not in MONTHS:
            continue
        date = dt.date(int(y), MONTHS[month.lower()], int(d)).isoformat()
        section = raw[day_match.end():day_matches[j+1].start() if j+1 < len(day_matches) else len(raw)]
        half_matches = list(HALF.finditer(section))
        for k, half_match in enumerate(half_matches):
            half = 0 if half_match.group(1).startswith('00') else 2
            table = section[half_match.end():half_matches[k+1].start() if k+1 < len(half_matches) else len(section)]
            for match in ROW.finditer(table):
                zone = ' '.join(match.group('zone').split()).upper()
                for n in (1, 2):
                    h, douglas, period = (match.group(f'{v}{n}') for v in ('h','d','t'))
                    if 'N.D.' in (h.upper(), douglas.upper(), period.upper()):
                        continue
                    hx, state, t = float(h.replace(',','.')), int(float(douglas.replace(',','.'))), float(period.replace(',','.'))
                    if not (0 <= hx <= 30 and 0 <= state <= 9 and 0 <= t <= 30):
                        continue
                    forecasts.append(dict(date=date,zone=zone,slot=SLOTS[half+n-1],hx_m=hx,douglas=state,period_s=t,
                        direction=match.group(f'dir{n}'),sea_state=' '.join(match.group(f'state{n}').split())))
    unique = {(v['date'],v['zone'],v['slot']):v for v in forecasts}
    if len(unique) < 28:
        raise ValueError(f'ARPAS: trovate {len(unique)} previsioni, attese almeno 28; file precedente conservato')
    return dict(source='ARPAS Sardegna',source_url=URL,issued_at=issued,
        fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),
        note='Hx = altezza massima dell’onda, NON altezza significativa; zone marine ampie.',
        forecasts=sorted(unique.values(),key=lambda x:(x['date'],x['slot'],x['zone'])))

def main():
    response = requests.get(URL,timeout=30,headers={'User-Agent':'Mozilla/5.0 (compatible; LadyLola/3.1)'})
    response.raise_for_status()
    response.encoding = response.apparent_encoding or 'utf-8'
    result = extract(response.text)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Salvate',len(result['forecasts']),'previsioni ARPAS')

if __name__ == '__main__':
    main()
