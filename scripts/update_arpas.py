"""Fetch ARPAS marine bulletin; fail closed if layout changes.
Requires: requests, beautifulsoup4. Output only on successful validated parsing.
"""
import datetime as dt
import json
import re
from pathlib import Path
import requests
from bs4 import BeautifulSoup

URL = 'https://www.sar.sardegna.it/servizi/meteo/prevmare_new.asp'
OUT = Path(__file__).resolve().parents[1] / 'data' / 'arpas_mare.json'
ZONE = re.compile(r'^(60\s+(?:N|NW)|61\s+NE|62\s+W|63\s+SE|64\s+(?:S|SW))$', re.I)
DATE = re.compile(r'Previsione per\s+(\w+)\s+(\d{1,2})\s+(\w+)\s+(\d{4})', re.I)
MONTHS = dict(zip('gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre'.split(), range(1, 13)))
SLOTS = ['00:00-06:00', '06:00-12:00', '12:00-18:00', '18:00-24:00']

def parse_row(cells):
    """A zone row has zone, then [Hx,D,T,Dir,Stato] x 2."""
    cells = [re.sub(r'\s+', ' ', c).strip() for c in cells if c.strip()]
    if not cells: return None
    zone = cells[0]
    if len(cells) > 1 and ZONE.fullmatch(zone + ' ' + cells[1]):
        zone += ' ' + cells.pop(1)
    if not ZONE.fullmatch(zone): return None
    rest = cells[1:]
    if len(rest) != 10:
        # Some HTML layouts group two fields in a cell; normalize by splitting only numerical tokens.
        rest = ' '.join(rest).split()
        # State labels may have two words (Poco mosso / Molto mosso).
        for term in ('Poco mosso', 'Molto mosso'):
            rest = ' '.join(rest).replace(term, term.replace(' ', '_')).split()
        rest = [v.replace('_',' ') for v in rest]
    if len(rest) != 10: return None
    result=[]
    for i in (0,5):
        hx, douglas, period, direction, state = rest[i:i+5]
        try:
            h=float(hx.replace(',','.')); t=float(period.replace(',','.')); d=int(douglas)
        except ValueError: return None
        if not (0 <= h <= 30 and 0 <= t <= 30 and 0 <= d <= 9): return None
        result.append(dict(hx_m=h, douglas=d, period_s=t, direction=direction, sea_state=state))
    return zone, result

def extract(html):
    soup=BeautifulSoup(html,'html.parser')
    raw=soup.get_text(' ',strip=True)
    emitted=re.search(r'Emissione del\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})',raw)
    if not emitted: raise ValueError('Emission timestamp not found')
    issued=dt.datetime.strptime(' '.join(emitted.groups()),'%d/%m/%Y %H:%M:%S').replace(tzinfo=dt.timezone(dt.timedelta(hours=1))).isoformat()
    # Walk the document in source order, associating each zone table row with the nearest heading and 2-slot half-day.
    day=None; half=0; observations=[]
    for element in soup.find_all(['h1','h2','h3','h4','strong','b','tr','p','div']):
        # Ignore parent containers; their text includes child headings/rows.
        if element.name in ('p','div') and element.find(['h1','h2','h3','h4','strong','b','tr']): continue
        if element.name=='tr':
            cells=[c.get_text(' ',strip=True) for c in element.find_all(['td','th'],recursive=False)]
            parsed=parse_row(cells)
            if parsed and day:
                zone, pair=parsed
                # Each day contains two seven-zone tables; detect second occurrence.
                if zone=='60 N' and any(o['date']==day and o['zone']=='60 N' for o in observations): half=2
                for idx,record in enumerate(pair):
                    observations.append(dict(date=day,zone=zone,slot=SLOTS[half+idx],**record))
            continue
        t=element.get_text(' ',strip=True)
        m=DATE.search(t)
        if m and len(t)<150:
            _,day_num,month,year=m.groups()
            if month.lower() in MONTHS:
                day=dt.date(int(year),MONTHS[month.lower()],int(day_num)).isoformat();half=0
    # Deduplicate duplicate nested heading matches and validate coverage.
    unique={(o['date'],o['zone'],o['slot']):o for o in observations}
    if len(unique)<28: raise ValueError(f'Only {len(unique)} zone/slot records parsed; page structure may have changed')
    dates={o['date'] for o in unique.values()}
    if len(dates)<1: raise ValueError('No dates')
    return dict(source='ARPAS Sardegna',source_url=URL,issued_at=issued,
                fetched_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                note='Hx = altezza massima dell’onda, NON altezza significativa; zone marine ampie.',
                forecasts=sorted(unique.values(),key=lambda o:(o['date'],o['slot'],o['zone'])))

def main():
    response=requests.get(URL,timeout=30,headers={'User-Agent':'LadyLolaMarineForecast/1.0 (GitHub Actions; public bulletin)'})
    response.raise_for_status();response.encoding=response.apparent_encoding or 'utf-8'
    result=extract(response.text)
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Saved',len(result['forecasts']),'records to',OUT)

if __name__=='__main__':main()
