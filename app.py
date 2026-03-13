import streamlit as st
import datetime
import requests
from bs4 import BeautifulSoup
from zoneinfo import ZoneInfo
import re

st.set_page_config(page_title="TH Taktinen Tutka", page_icon="🚕", layout="wide")

# ==========================================
# 1. TIETOTURVA JA KIRJAUTUMINEN
# ==========================================

APP_PASSWORD = st.secrets.get("APP_PASSWORD", "2026")

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    st.markdown("<h1 style='text-align: center; color: #5bc0de;'> TH Taktinen Tutka </h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: #aaa;'>Kirjaudu sisään nähdäksesi datan.</p>", unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        pwd = st.text_input("Salasana", type="password")
        if st.button("Kirjaudu", use_container_width=True):
            if pwd == APP_PASSWORD:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Väärä salasana.")
    st.stop()

# ==========================================
# 2. ARKKITEHTUURIN PERUSTA: API-AVAIMET JA TILA
# ==========================================

FINAVIA_API_KEY = st.secrets.get("FINAVIA_API_KEY", "c24ac18c01e44b6e9497a2a30341")

if "valittu_asema" not in st.session_state:
    st.session_state.valittu_asema = "Helsinki"

if "paiva_offset" not in st.session_state:
    st.session_state.paiva_offset = 0

st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    header {visibility: hidden;}
    main { background-color: #121212; }
    .header-container {
        display: flex; justify-content: space-between; align-items: flex-start;
        border-bottom: 1px solid #333; padding-bottom: 15px; margin-bottom: 20px;
    }
    .app-title { font-size: 32px; font-weight: bold; color: #ffffff; margin-bottom: 5px; }
    .time-display { font-size: 42px; font-weight: bold; color: #e0e0e0; line-height: 1.1; }
    .taksi-card {
        background-color: #1e1e2a; color: #e0e0e0; padding: 22px;
        border-radius: 12px; margin-bottom: 20px; font-size: 20px;
        border: 1px solid #3a3a50; box-shadow: 0 4px 8px rgba(0,0,0,0.3); line-height: 1.4;
    }
    .card-title {
        font-size: 24px; font-weight: bold; margin-bottom: 12px;
        color: #ffffff; border-bottom: 2px solid #444; padding-bottom: 8px;
    }
    .taksi-link {
        color: #5bc0de; text-decoration: none; font-size: 18px;
        display: inline-block; margin-top: 12px; font-weight: bold;
    }
    .badge-red { background: #7a1a1a; color: #ff9999; padding: 2px 8px; border-radius: 4px; }
    .badge-yellow { background: #5a4a00; color: #ffeb3b; padding: 2px 8px; border-radius: 4px; }
    .badge-green { background: #1a4a1a; color: #88d888; padding: 2px 8px; border-radius: 4px; }
    .badge-blue { background: #1a2a5a; color: #8ab4f8; padding: 2px 8px; border-radius: 4px; }
    .badge-orange { background: #5a2a00; color: #ffb347; padding: 2px 8px; border-radius: 4px; }
    .sold-out { color: #ff4b4b; font-weight: bold; }
    .pax-good { color: #ffeb3b; font-weight: bold; }
    .pax-ok { color: #a3c2a3; }
    .delay-bad { color: #ff9999; font-weight: bold; }
    .on-time { color: #88d888; }
    .section-header {
        color: #e0e0e0; font-size: 24px; font-weight: bold;
        margin-top: 28px; margin-bottom: 10px;
        border-left: 4px solid #5bc0de; padding-left: 12px;
    }
    .venue-name { color: #ffffff; font-weight: bold; }
    .venue-address { color: #aaaaaa; font-size: 16px; }
    .endtime { color: #ffeb3b; font-size: 15px; font-weight: bold; }
    .eventline { border-left: 3px solid #333; padding-left: 12px; margin-bottom: 16px; }
    .live-event { color: #88d888; font-weight: bold; }
    .no-event { color: #888888; font-style: italic; }
    .tomorrow-banner {
        background: #2a2a0a; border: 1px solid #666600; border-radius: 8px;
        padding: 8px 16px; margin-bottom: 16px; color: #ffeb3b;
        font-size: 16px; font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 3. HEURISTIIKKAMOOTTORI
# ==========================================

def laske_kysyntakerroin(wb_status, klo_str):
    indeksi = 2.0
    if wb_status: 
        indeksi += 5.0
    try:
        tunnit = int(klo_str.split(":")[0])
        if tunnit >= 22 or tunnit <= 4: 
            indeksi += 2.5
        elif 15 <= tunnit <= 18: 
            indeksi += 1.5
    except: 
        pass
    
    indeksi = min(indeksi, 10.0)
    
    if indeksi >= 7: 
        return f"<span style='color:#ff4b4b; font-weight:bold;'>Kysyntä: {indeksi}/10</span>"
    elif indeksi >= 4: 
        return f"<span style='color:#ffeb3b;'>Kysyntä: {indeksi}/10</span>"
    else: 
        return f"<span style='color:#a3c2a3;'>Kysyntä: {indeksi}/10</span>"

# HAKUFUNKTIOT (CACHE)
@st.cache_data(ttl=86400)
def hae_juna_asemat():
    asemat = {
        "HKI": "Helsinki", "PSL": "Pasila", "TKL": "Tikkurila", "KRS": "Kerava",
        "RHI": "Riihimäki", "HML": "Hämeenlinna", "TPE": "Tampere", "TKU": "Turku",
        "POR": "Pori", "VAA": "Vaasa", "SEI": "Seinäjoki", "YV": "Ylivieska", "KOK": "Kokkola",
        "OUL": "Oulu", "KEM": "Kemi", "ROV": "Rovaniemi", "KLI": "Kolari", "KJA": "Kajaani",
        "KUO": "Kuopio", "JNS": "Joensuu", "ILO": "Iisalmi", "MIK": "Mikkeli", "KOU": "Kouvola",
        "LPR": "Lappeenranta", "IMR": "Imatra", "PMI": "Parikkala", "LH": "Lahti",
        "VNA": "Vainikkala", "VKO": "Vainikkala", "MÄ": "Mäntsälä", "LAE": "Lappila",
        "KAU": "Kauhava", "LAP": "Lapua", "VTI": "Vihanti", "YST": "Ylistaro"
    }
    try:
        resp = requests.get("https://rata.digitraffic.fi/api/v1/metadata/stations")
        resp.raise_for_status()
        for s in resp.json(): 
            asemat[s["stationShortCode"]] = s["stationName"].replace(" asema", "")
    except: 
        pass
    return asemat

def tunnista_terminaali(teksti):
    teksti = teksti.lower()
    if "t2" in teksti or "lansisatama" in teksti or "länsisatama" in teksti: return "Länsiterminaali T2"
    if "t1" in teksti or "olympia" in teksti: return "Olympia T1"
    if "katajanokka" in teksti: return "Katajanokka"
    if "vuosaari" in teksti: return "Vuosaari (rahti)"
    return "Tarkista"

def _etsi_aika(osat):
    for osa in osat:
        m = re.search(r"\b([0-2]?\d:[0-5]\d)\b", str(osa))
        if m: return m.group(1)
    return ""

def pax_arvio(pax):
    if pax is None: return "Ei tietoa", "pax-ok"
    autoa = round(pax * 0.025)
    if pax >= 1500: return f"({pax} matkustajaa, ~{autoa} autoa, HYVÄ)", "pax-good"
    if pax >= 800: return f"({pax} matkustajaa, ~{autoa} autoa, NORMAALI)", "pax-ok"
    return f"({pax} matkustajaa, ~{autoa} autoa, HILJAINEN)", "pax-ok"

@st.cache_data(ttl=600)
def get_averio_ships():
    laivat = []
    try:
        resp = requests.get("https://averio.fi/laivat", headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        
        for taulu in soup.find_all("table"):
            for rivi in taulu.find_all("tr"):
                solut = [td.get_text(strip=True) for td in rivi.find_all(["td", "th"])]
                if len(solut) < 3: continue
                rivi_teksti = " ".join(solut).lower()
                
                if any(h in rivi_teksti for h in ["alus", "laiva", "ship", "vessel"]): continue
                
                pax = None
                for solu in solut:
                    puhdas = re.sub(r"[^\d]", "", solu)
                    if puhdas and 50 < int(puhdas) <= 9999:
                        pax = int(puhdas)
                        break
                
                nimi_kandidaatit = [s for s in solut if re.search(r"[A-Za-zÄÖÅäöå]{3,}", s)]
                if not nimi_kandidaatit: continue
                nimi = max(nimi_kandidaatit, key=len)
                
                laivat.append({
                    "ship": nimi, 
                    "terminal": tunnista_terminaali(rivi_teksti),
                    "time": _etsi_aika(solut), 
                    "pax": pax
                })
        return laivat[:5] if laivat else [{"ship": "Averio: HTML-rakenne muuttunut", "terminal": "", "time": "", "pax": None}]
    except Exception as e: 
        return [{"ship": f"Averio-virhe: {str(e)}", "terminal": "", "time": "", "pax": None}]

@st.cache_data(ttl=600)
def get_port_schedule():
    try:
        resp = requests.get("https://www.portofhelsinki.fi/matkustajille/matkustajatietoa/saapuvat-ja-lahtevat-laivat/")
        resp.raise_for_status()
        lista = []
        for rivi in BeautifulSoup(resp.text, "html.parser").find_all("tr"):
            solut = rivi.find_all("td")
            if len(solut) >= 4:
                aika = solut[0].get_text(strip=True)
                laiva = solut[1].get_text(strip=True)
                terminaali = solut[3].get_text(strip=True) if len(solut) > 3 else ""
                if aika and laiva and re.match(r"\d{1,2}:\d{2}", aika):
                    lista.append({"time": aika, "ship": laiva, "terminal": terminaali})
        return lista[:6] if lista else []
    except: 
        return []

@st.cache_data(ttl=50)
def get_trains(asema_nimi):
    nykyhetki = datetime.datetime.now(ZoneInfo("Europe/Helsinki"))
    koodi = {"Helsinki": "HKI", "Pasila": "PSL", "Tikkurila": "TKL"}.get(asema_nimi, "HKI")
    asemat_dict = hae_juna_asemat()
    tulos = []
    
    try:
        resp = requests.get(f"https://rata.digitraffic.fi/api/v1/live-trains/station/{koodi}?arriving_trains=20&include_nonstopping=false")
        resp.raise_for_status()
        
        for juna in resp.json():
            if juna.get("cancelled"): continue
            nimi = f"{juna.get('trainType', '')} {juna.get('trainNumber', '')}"
            lahto_koodi = next((r["stationShortCode"] for r in juna["timeTableRows"] if r["type"] == "DEPARTURE"), "Tuntematon")
            
            if lahto_koodi in ("HKI", "PSL", "TKL", "ILA", "KRS"): continue
            
            aika_obj = None
            aika_str = None
            viive = 0
            
            for rivi in juna["timeTableRows"]:
                if rivi["stationShortCode"] == koodi and rivi["type"] == "ARRIVAL":
                    raaka = rivi.get("liveEstimateTime") or rivi.get("scheduledTime")
                    try:
                        aika_obj = datetime.datetime.strptime(raaka[:16], "%Y-%m-%dT%H:%M")
                        if aika_obj < nykyhetki - datetime.timedelta(minutes=3):
                            continue
                        aika_str = aika_obj.strftime("%H:%M")
                    except: 
                        pass
                    viive = rivi.get("differenceInMinutes", 0)
                    break
            
            if aika_str and aika_obj:
                tulos.append({
                    "train": nimi, 
                    "origin": asemat_dict.get(lahto_koodi, lahto_koodi), 
                    "time": aika_str, 
                    "delay": viive,
                    "dt": aika_obj
                })
                
        tulos.sort(key=lambda k: k["dt"])
        return tulos[:6]
    except Exception as e: 
        return [{"train": "API-virhe", "origin": str(e)[:40], "time": "", "delay": 0}]

@st.cache_data(ttl=60)
def get_flights():
    laajarunko = ("359", "350", "333", "330", "340", "788", "789", "777", "77W")
    endpoints = [
        (f"https://apigw.finavia.fi/flights/public/v0/flights/arr/HEL?subscription-key={FINAVIA_API_KEY}", {}),
        ("https://apigw.finavia.fi/flights/public/v0/flights/arr/HEL", {"Ocp-Apim-Subscription-Key": FINAVIA_API_KEY})
    ]
    
    for url, extra_headers in endpoints:
        hdrs = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Cache-Control": "no-cache"}
        hdrs.update(extra_headers)
        
        try:
            resp = requests.get(url, headers=hdrs, timeout=10)
            if resp.status_code in (401, 403): continue
            resp.raise_for_status()
            data = resp.json()
            
            saapuvat = []
            if isinstance(data, list): 
                saapuvat = data
            elif isinstance(data, dict):
                for avain in ("arr", "flights", "body"):
                    if isinstance(data.get(avain), list): 
                        saapuvat = data[avain]
                        break
                if not saapuvat and isinstance(data.get("body"), dict):
                    for ala in ("arr", "flight"):
                        if isinstance(data["body"].get(ala), list): 
                            saapuvat = data["body"][ala]
                            break
            
            if not saapuvat: continue
            
            tulos = []
            for lento in saapuvat:
                actype = str(lento.get("actype") or lento.get("aircraftType", "")).upper()
                status = str(lento.get("prt_f") or lento.get("statusInfo", "Odottaa")).upper()
                aika_r = str(lento.get("sdt") or lento.get("scheduledTime", ""))
                wb = any(c in actype for c in laajarunko)
                
                if wb and "LASKEUTUNUT" not in status and "LANDED" not in status:
                    pass
                elif "DELAY" in status or "MYOHASSA" in status: 
                    pass
                else:
                    if not wb: continue
                
                tulos.append({
                    "flight": lento.get("fltnr") or lento.get("flightNumber", "??"),
                    "origin": lento.get("route_n_1") or lento.get("airport", "Tuntematon"),
                    "time": aika_r[11:16] if "T" in aika_r else aika_r[:5],
                    "type": f"Laajarunko (+ {actype})" if wb else f"Kapearunko ({actype})",
                    "wb": wb, 
                    "status": status
                })
                
            tulos.sort(key=lambda x: (not x["wb"], x["time"]))
            return tulos[:8], None
            
        except: 
            continue
            
    return [], "Finavia API ei vastannut. Tarkista avain."

def _pvm_muodot(pvm_iso: str):
    dt = datetime.datetime.strptime(pvm_iso, "%Y-%m-%d")
    return [
        f"{dt.day}.{dt.month}.{dt.year}",
        f"{dt.day:02d}.{dt.month:02d}.{dt.year}",
        pvm_iso,
    ]

def _etsi_esitykset_soupista(soup, pvm_iso: str):
    tapahtumat = []
    seen = set()
    pvm_muodot = _pvm_muodot(pvm_iso)
    
    for pvm in pvm_muodot:
        for el in soup.find_all(string=re.compile(re.escape(pvm))):
            node = el.parent
            for _ in range(10):
                if node is None: break
                heading = node.find(["h1", "h2", "h3", "h4", "strong"])
                if heading:
                    title = heading.get_text(strip=True)
                    if len(title) > 4 and not re.match(r"^\d", title) and title not in seen:
                        container_text = node.get_text(" ", strip=True)
                        time_match = re.search(r"\b([0-2]?\d:[0-5]\d)\b", container_text)
                        entry = title
                        if time_match:
                            entry += f" klo {time_match.group(1)}"
                        tapahtumat.append(entry)
                        seen.add(title)
                        break
                node = node.parent
    return tapahtumat

@st.cache_data(ttl=600)
def hae_liiga_pvm(pvm_iso: str):
    try:
        dt = datetime.datetime.strptime(pvm_iso, "%Y-%m-%d")
        kausi_alku = dt.year if dt.month > 6 else dt.year - 1
        kausi_str = f"{kausi_alku}-{kausi_alku + 1}"
        
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        endpoints = [
            f"https://liiga.fi/api/v2/games?tournament=runkosarja&season={kausi_str}",
            f"https://liiga.fi/api/v2/games?tournament=SM-liiga&season={kausi_str}",
            f"https://liiga.fi/api/v1/games?tournament=runkosarja&season={kausi_str}",
            f"https://liiga.fi/api/v2/games?season={kausi_str}",
        ]
        
        for url in endpoints:
            try:
                resp = requests.get(url, headers=headers, timeout=10)
                if resp.status_code != 200: continue
                data = resp.json()
                
                pelit_lista = data if isinstance(data, list) else data.get("games", data.get("data", []))
                if not isinstance(pelit_lista, list): continue
                
                pelit = []
                for peli in pelit_lista:
                    start = peli.get("start", peli.get("startTime", peli.get("date", "")))
                    if not start.startswith(pvm_iso): continue
                    
                    koti = ((peli.get("homeTeam") or {}).get("teamName") or 
                            (peli.get("homeTeam") or {}).get("name") or 
                            peli.get("homeTeamName", ""))
                            
                    vieras = ((peli.get("awayTeam") or {}).get("teamName") or 
                              (peli.get("awayTeam") or {}).get("name") or 
                              peli.get("awayTeamName", ""))
                              
                    aika = start[11:16] if len(start) > 10 else ""
                    pelit.append({"koti": koti, "vieras": vieras, "aika": aika})
                    
                if pelit or len(pelit_lista) > 0:
                    return pelit
            except Exception:
                continue
        return []
    except Exception:
        return []

@st.cache_data(ttl=600)
def hae_ooppera_pvm(pvm_iso: str):
    try:
        pvm_muodot = _pvm_muodot(pvm_iso)
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get("https://oopperabaletti.fi/ohjelmisto/", headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        tapahtumat = _etsi_esitykset_soupista(soup, pvm_iso)
        
        if not tapahtumat:
            full_html = resp.text
            pvm_fi = pvm_muodot[0]
            for pvm in pvm_muodot:
                if pvm in full_html:
                    pattern = re.compile(re.escape(pvm) + r".{0,300}", re.DOTALL)
                    match = pattern.search(full_html)
                    if match:
                        context = BeautifulSoup(match.group(), "html.parser").get_text(" ", strip=True)
                        time_match = re.search(r"\b([0-2]?\d:[0-5]\d)\b", context)
                        aika_str = f" klo {time_match.group(1)}" if time_match else ""
                        tapahtumat = [f"Näytös {pvm_fi}{aika_str} (tarkista ooppera.fi)"]
                    else:
                        tapahtumat = [f"Näytös löytyi ({pvm_fi})"]
                    break
        return tapahtumat
    except Exception:
        return []

@st.cache_data(ttl=600)
def hae_hkt_pvm(pvm_iso: str):
    try:
        pvm_muodot = _pvm_muodot(pvm_iso)
        headers = {"User-Agent": "Mozilla/5.0"}
        tapahtumat = []
        for url in ["https://hkt.fi/kalenteri/", "https://hkt.fi/"]:
            try:
                resp = requests.get(url, headers=headers, timeout=12)
                if resp.status_code != 200: continue
                soup = BeautifulSoup(resp.text, "html.parser")
                tapahtumat = _etsi_esitykset_soupista(soup, pvm_iso)
                if tapahtumat: return tapahtumat
                
                for pvm in pvm_muodot:
                    if pvm in resp.text:
                        pvm_fi = pvm_muodot[0]
                        raw = resp.text
                        pattern = re.compile(re.escape(pvm) + r".{0,400}", re.DOTALL)
                        matches = pattern.findall(raw)
                        for m in matches[:3]:
                            ctx = BeautifulSoup(m, "html.parser").get_text(" ", strip=True)
                            time_match = re.search(r"\b([0-2]?\d:[0-5]\d)\b", ctx)
                            title_match = re.search(r"([A-ZÄÖÅ][A-ZÄÖÅ\s\-]{5,})", ctx)
                            if title_match:
                                title = title_match.group(1).strip()
                                aika_str = f" klo {time_match.group(1)}" if time_match else ""
                                tapahtumat.append(f"{title.title()}{aika_str}")
                if not tapahtumat:
                    tapahtumat = [f"Esityksiä {pvm_fi} (tarkista hkt.fi)"]
                return tapahtumat
            except Exception:
                continue
        return tapahtumat
    except Exception:
        return []

@st.cache_data(ttl=3600)
def get_culture_live_events(pvm_iso: str):
    live_tapahtumat = {}
    try:
        dt = datetime.datetime.strptime(pvm_iso, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Europe/Helsinki"))
        alku = dt.replace(hour=0, minute=0, second=0).isoformat()
        loppu = dt.replace(hour=23, minute=59, second=59).isoformat()
        
        url = f"https://linkedevents.api.hel.fi/v1/event/?start={alku}&end={loppu}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        
        for e in resp.json().get("data", []):
            paikka_nimi = (e.get("location", {}).get("name", {}).get("fi") or "")
            end_time_str = e.get("end_time")
            if not end_time_str or not paikka_nimi: continue
            
            try:
                end_dt = datetime.datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                if end_dt.date() == dt.date():
                    if paikka_nimi not in live_tapahtumat:
                        live_tapahtumat[paikka_nimi] = []
                    nimi = e.get('name', {}).get('fi', 'Tuntematon esitys')
                    klo = end_dt.strftime('%H:%M')
                    live_tapahtumat[paikka_nimi].append(f"{nimi} (päättyy: {klo})")
            except: pass
    except: pass
    return live_tapahtumat

def yhdista_kulttuuridata(paikat, pvm_iso: str):
    live_data = get_culture_live_events(pvm_iso)
    ooppera_tapahtumat = hae_ooppera_pvm(pvm_iso)
    hkt_tapahtumat = hae_hkt_pvm(pvm_iso)
    
    for p in paikat:
        hakusanat = p.get("hakusanat", [])
        tapahtumat = []
        
        for api_paikka, api_tapahtumat in live_data.items():
            if any(sana in api_paikka for sana in hakusanat):
                tapahtumat.extend(api_tapahtumat)
                
        nimi = p.get("nimi", "").lower()
        if not tapahtumat:
            if "ooppera" in nimi and ooppera_tapahtumat:
                tapahtumat = ooppera_tapahtumat
            elif "kaupunginteatteri" in nimi and hkt_tapahtumat:
                tapahtumat = hkt_tapahtumat
                
        if tapahtumat:
            p["lopetus_html"] = f"<span class='live-event'>ESITYKSIÄ: {' | '.join(tapahtumat)}</span>"
        else:
            if hakusanat:
                p["lopetus_html"] = (f"<span class='no-event'>Ei tunnettua esitystä.</span>"
                                     f"<br><span style='color:#777;'>Tyypillisesti: {p.get('huomio','')}</span>")
            else:
                p["lopetus_html"] = f"<span class='endtime'>Tyypillinen lopetus: {p.get('huomio','')}</span>"
    return paikat

def yhdista_urheiludata(paikat, pvm_iso: str):
    liiga_pelit = hae_liiga_pvm(pvm_iso)
    
    def etsi_kotipeli(hakusana):
        tulokset = []
        for peli in liiga_pelit:
            koti_lower = peli["koti"].lower()
            if hakusana.lower() in koti_lower:
                tulokset.append(f"{peli['koti']} - {peli['vieras']} (klo {peli['aika']})")
        return tulokset
        
    for p in paikat:
        nimi = p.get("nimi", "").lower()
        tapahtumat = []
        if "hifk" in nimi:
            tapahtumat = etsi_kotipeli("hifk") or etsi_kotipeli("ifk")
        elif "kiekko-espoo" in nimi or "k-espoo" in nimi:
            tapahtumat = etsi_kotipeli("k-espoo") or etsi_kotipeli("kiekko")
            
        if tapahtumat:
            p["lopetus_html"] = (f"<span class='live-event'>PELI TÄNÄÄN: {' | '.join(tapahtumat)}</span>"
                                 f"<br><span style='color:#ccc;font-size:15px;'>Kesto n. 2,5h aloitusajasta</span>")
        else:
            p["lopetus_html"] = "<span class='no-event'>Ei Liiga-kotiottelua.</span>"
    return paikat

@st.cache_data(ttl=3600)
def get_general_live_events(pvm_iso: str):
    tulos = []
    try:
        dt = datetime.datetime.strptime(pvm_iso, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Europe/Helsinki"))
        url = f"https://linkedevents.api.hel.fi/v1/event/?start={pvm_iso}&sort=end_time"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        
        for e in resp.json().get("data", []):
            end_time_str = e.get("end_time")
            if not end_time_str: continue
            try:
                end_dt = datetime.datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
                if end_dt.date() == dt.date() and end_dt.hour >= 16:
                    loc = e.get("location", {})
                    osoite = loc.get("name", {}).get("fi") or loc.get("street_address", {}).get("fi") or "Helsinki"
                    tulos.append({
                        "nimi": e.get("name", {}).get("fi", "Tuntematon tapahtuma"),
                        "loppu": end_dt.strftime("%H:%M"),
                        "paikka": osoite,
                        "dt": end_dt,
                    })
            except: pass
        tulos.sort(key=lambda x: x["dt"])
        return tulos[:10]
    except:
        return []

def viive_badge(minuutit):
    if minuutit <= 0: return "<span class='badge-green'>Aikataulussa</span>"
    if minuutit < 15: return f"<span class='badge-yellow'>+{minuutit} min</span>"
    if minuutit < 60: return f"<span class='badge-red'>+{minuutit} min</span>"
    return f"<span class='badge-red'>+{minuutit} min VR-korvaus!</span>"

def venue_card(p):
    lopetus_naytto = p.get("lopetus_html", f"<span class='endtime'>Tyypillinen lopetus: {p.get('huomio','')}</span>")
    badge_color = p.get('badge', 'badge-blue')
    card_html = (
        f"<div class='eventline'>"
        f"<span class='{badge_color}'></span> "
        f"<span class='venue-name'>{p.get('nimi','')}</span><br>"
        f"<span class='venue-address'>Max pax: <b>{p.get('kap','')}</b></span><br>"
        f"{lopetus_naytto}<br>"
    )
    if 'linkki' in p:
        card_html += f"<a href='{p['linkki']}' class='taksi-link' target='_blank' style='font-size:14px;'>Sivut</a>"
    if 'linkki2' in p:
        card_html += f" &nbsp; &nbsp; <a href='{p['linkki2']}' class='taksi-link' target='_blank' style='font-size:14px;'>Liput</a>"
    return card_html + "</div>"

def venue_html(paikat):
    return "".join(venue_card(p) for p in paikat)

# ==========================================
# 4. DASHBOARD (NATIIVI AUTOREFRESH)
# ==========================================

@st.fragment(run_every=300)
def render_dashboard():
    suomen_aika = datetime.datetime.now(ZoneInfo("Europe/Helsinki"))
    klo = suomen_aika.strftime("%H:%M")
    paiva = suomen_aika.strftime("%A %d.%m.%Y").capitalize()
    HSL_LINKKI = "https://www.hsl.fi/matkustaminen/liikenne?language=fi"

    st.markdown(f"""
    <div class='header-container'>
        <div>
            <div class='app-title'>TH Taktinen Tutka</div>
            <div class='time-display'>{klo} <span style='font-size:16px;color:#888;'>{paiva}</span></div>
        </div>
        <div style='text-align:right;'>
            <a href='https://www.ilmatieteenlaitos.fi/sade-ja-pilvialueet?area=etela-suomi' class='taksi-link' target='_blank'>Sää</a> | 
            <a href='https://liikennetilanne.fintraffic.fi/' class='taksi-link' target='_blank'>Liikenne</a> | 
            <a href='{HSL_LINKKI}' class='taksi-link' target='_blank'>HSL</a>
        </div>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Pakota päivitys (Tyhjennä muisti)", type="secondary", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    # LOHKO 1: JUNAT
    st.markdown("<div class='section-header'> SAAPUVAT KAUKOJUNAT</div>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns(3)
    if c1.button("Helsinki (HKI)", use_container_width=True): st.session_state.valittu_asema = "Helsinki"
    if c2.button("Pasila (PSL)", use_container_width=True): st.session_state.valittu_asema = "Pasila"
    if c3.button("Tikkurila (TKL)", use_container_width=True): st.session_state.valittu_asema = "Tikkurila"

    valittu = st.session_state.valittu_asema
    junat = get_trains(valittu)
    vr_linkit = {
        "Helsinki": "https://www.vr.fi/radalla?station=HKI",
        "Pasila": "https://www.vr.fi/radalla?station=PSL",
        "Tikkurila": "https://www.vr.fi/radalla?station=TKL"
    }

    juna_html = f"<span style='color:#aaa; font-size:17px;'>Asema: <b>{valittu}</b></span><br><br>"
    if junat and junat[0].get("train") != "API-virhe":
        for j in junat:
            h_merkki = '❄️' if j['origin'] in ['Rovaniemi', 'Kolari', 'Kemi', 'Oulu'] else ''
            juna_html += f"<b>{j['time']}</b> {j['train']} <span style='color:#aaa;'>(lähtö: {j['origin']} {h_merkki})</span> └ {viive_badge(j['delay'])}<br><br>"
    else:
        juna_html += "Ei saapuvia kaukojunia lähiaikoina."

    st.markdown(
        f"<div class='taksi-card'>{juna_html}"
        f"<a href='{vr_linkit.get(valittu, '')}' class='taksi-link' target='_blank'>VR Live</a>"
        f" &nbsp; &nbsp; <a href='https://www.vr.fi/radalla/poikkeustilanteet' class='taksi-link' target='_blank'>Poikkeukset</a></div>",
        unsafe_allow_html=True,
    )

    # LOHKO 2: LAIVAT
    st.markdown("<div class='section-header'> MATKUSTAJALAIVAT</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns(2)
    
    with col_a:
        averio_html = "<div class='card-title'>Averio Matkustajamäärät</div><span style='color:#aaa; font-size:15px;'> klo 00:30 MS Finlandia →</span><br><br>"
        for laiva in get_averio_ships():
            arvio_teksti, arvio_css = pax_arvio(laiva["pax"])
            averio_html += (f"<b>{laiva['time']}</b> {laiva['ship']}<br>"
                            f"└ Terminaali: {laiva['terminal']}<br>"
                            f"└ <span class='{arvio_css}'>{arvio_teksti}</span><br><br>")
        st.markdown(f"<div class='taksi-card'>{averio_html}<a href='https://averio.fi/laivat' class='taksi-link' target='_blank'>Lähde: Averio.fi</a></div>", unsafe_allow_html=True)

    with col_b:
        port_html = "<div class='card-title'>Helsingin Satama Aikataulu</div><br>"
        port_laivat = get_port_schedule()
        if port_laivat:
            for laiva in port_laivat:
                port_html += f"<b>{laiva['time']}</b> {laiva['ship']} ({laiva['terminal']})<br><br>"
        else:
            port_html += "Ei dataa - sivu vaatii JavaScript-renderöinnin.<br><br>"
        st.markdown(f"<div class='taksi-card'>{port_html}<a href='https://www.portofhelsinki.fi/matkustajille/matkustajatietoa/saapuvat-ja-lahtevat-laivat/' class='taksi-link' target='_blank'>Lähde: Port of Helsinki</a></div>", unsafe_allow_html=True)

    # LOHKO 3: LENNOT
    st.markdown("<div class='section-header'> LENTOKENTTÄ (Helsinki-Vantaa) </div>", unsafe_allow_html=True)
    lennot, lento_virhe = get_flights()
    if lento_virhe:
        st.markdown(f"<div class='taksi-card'><div class='card-title'>Finavia API</div><span style='color:#ff9999;'>{lento_virhe}</span><br><br></div>", unsafe_allow_html=True)
    else:
        lento_html = "<div class='card-title'>Taktiset poiminnat saapuvat</div><span style='color:#aaa; font-size:15px;'>Frankfurt arki-iltaisin = paljon liike-elämän matkustajia</span><br><br>"
        for lento in lennot:
            pax_class = 'pax-good' if lento['wb'] else 'pax-ok'
            lento_html += (f"<b>{lento['time']}</b> {lento['origin']} <span style='color:#ccc;'>({lento['flight']})</span> - {lento['status']}<br>"
                           f"└ <span class='{pax_class}'>{lento['type']}</span><br>"
                           f"└ {laske_kysyntakerroin(lento['wb'], lento['time'])}<br><br>")
        st.markdown(f"<div class='taksi-card'>{lento_html}<a href='https://www.finavia.fi/fi/lentoasemat/helsinki-vantaa/lennot' class='taksi-link' target='_blank'>Finavia Live</a></div>", unsafe_allow_html=True)

    # LOHKO 4: TAPAHTUMAT
    st.markdown("<div class='section-header'> TAPAHTUMAT & KAPASITEETTI</div>", unsafe_allow_html=True)
    col_p1, col_p2, col_p3 = st.columns([1, 1, 4])
    
    if col_p1.button("Tänään", use_container_width=True, type="primary" if st.session_state.paiva_offset == 0 else "secondary"):
        st.session_state.paiva_offset = 0
    if col_p2.button("Huomenna", use_container_width=True, type="primary" if st.session_state.paiva_offset == 1 else "secondary"):
        st.session_state.paiva_offset = 1

    kohde_dt = suomen_aika + datetime.timedelta(days=st.session_state.paiva_offset)
    pvm_iso = kohde_dt.strftime("%Y-%m-%d")
    pvm_fi_naytto = kohde_dt.strftime("%A %d.%m.%Y").capitalize()

    if st.session_state.paiva_offset == 1:
        st.markdown(f"<div class='tomorrow-banner'> Näytetään HUOMISEN tapahtumat ({pvm_fi_naytto})</div>", unsafe_allow_html=True)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Kulttuuri & VIP", "Urheilu", "Messut", "Musiikki", "Muut"])

    with tab1:
        kulttuuri_paikat = [
            {"nimi": "Helsingin Kaupunginteatteri (HKT)", "kap": "947 hlö", "hakusanat": ["hkt", "kaupunginteatteri"]},
            {"nimi": "Kansallisooppera ja baletti", "kap": "1 700 hlö", "hakusanat": ["ooppera", "baletti"]},
            {"nimi": "Kansallisteatteri", "kap": "1 000 hlö", "hakusanat": ["kansallisteatteri"]},
            {"nimi": "Musiikkitalo", "kap": "1 704 hlö", "hakusanat": ["musiikkitalo"]},
            {"nimi": "Tanssin talo (Kaapelitehdas)", "kap": "1 000 hlö", "hakusanat": ["tanssin talo", "kaapelitehdas"]},
            {"nimi": "Helsingin Suomalainen Klubi", "kap": "300 hlö", "hakusanat": []},
            {"nimi": "Svenska Klubben", "kap": "200 hlö", "hakusanat": []},
            {"nimi": "Finlandia-talo", "kap": "1 700 hlö", "hakusanat": ["finlandia"]}
        ]
        st.markdown(f"<div class='taksi-card'>{venue_html(yhdista_kulttuuridata(kulttuuri_paikat, pvm_iso))}</div>", unsafe_allow_html=True)

    with tab2:
        urheilu_paikat = [
            {"nimi": "HIFK Nordis (jääkiekko)", "kap": "8 200 hlö", "huomio": "Yleisö poistuu 2,5h aloituksesta"},
            {"nimi": "Kiekko-Espoo Metro Areena", "kap": "8 500 hlö", "huomio": "Yleisö poistuu 2,5h aloituksesta"},
            {"nimi": "Veikkaus Arena (Jokerit & Tapahtumat)", "kap": "15 000 hlö"},
            {"nimi": "Bolt Arena (HJK)", "kap": "10 770 hlö", "huomio": "Veikkausliiga"},
            {"nimi": "Olympiastadion", "kap": "50 000 hlö"}
        ]
        st.markdown(f"<div class='taksi-card'>{venue_html(yhdista_urheiludata(urheilu_paikat, pvm_iso))}</div>", unsafe_allow_html=True)

    with tab3:
        messut_paikat = [
            {"nimi": "Messukeskus", "kap": "50 000 hlö", "huomio": "Poistumapiikki usein klo 16-18"},
            {"nimi": "Aalto-yliopisto / Dipoli (Espoo)", "kap": "1 000 hlö", "huomio": "Seminaareja"},
            {"nimi": "Kalastajatorppa / Pyöreä Sali", "kap": "500 hlö", "huomio": "Yritystilaisuuksia"}
        ]
        st.markdown(f"<div class='taksi-card'>{venue_html(messut_paikat)}</div>", unsafe_allow_html=True)

    with tab4:
        musiikki_paikat = [
            {"nimi": "Tavastia", "kap": "900 hlö", "huomio": "Paras keikkapaikka"},
            {"nimi": "Malmitalo", "kap": "400 hlö", "huomio": "Iskelmä, kansanmusiikki"},
            {"nimi": "On the Rocks", "kap": "600 hlö", "huomio": "Rock, metal"},
            {"nimi": "Kulttuuritalo", "kap": "1 500 hlö", "huomio": "Isommat rock-keikat"},
            {"nimi": "Sellosali (Espoo)", "kap": "400 hlö", "huomio": "Klassinen, pop"},
            {"nimi": "Flow Festival / Suvilahdentie", "kap": "30 000 hlö / päivä"}
        ]
        st.markdown(f"<div class='taksi-card'>{venue_html(musiikki_paikat)}</div>", unsafe_allow_html=True)

    with tab5:
        general_tapahtumat = get_general_live_events(pvm_iso)
        st.markdown("<div class='card-title'>Muita yleisötapahtumia (Helsinki API)</div>", unsafe_allow_html=True)
        if general_tapahtumat:
            live_html = ""
            for t in general_tapahtumat:
                live_html += (f"<div class='eventline'><span class='badge-blue'>LIVE</span> "
                              f"<span class='venue-name'>{t['nimi']}</span><br>"
                              f"<span class='venue-address'>{t['paikka']}</span><br>"
                              f"<span class='endtime'>Päättyy: klo {t['loppu']}</span></div>")
            st.markdown(f"<div class='taksi-card'>{live_html}</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='taksi-card'>Ei muita tiedossa olevia yleisötapahtumia tälle illalle.</div>", unsafe_allow_html=True)

    # PIKALINKIT
    st.markdown("<div class='section-header'> OPERATIIVISET PIKALINKIT</div>", unsafe_allow_html=True)
    st.markdown(f"""
    <div class='taksi-card'>
        <div style='display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;font-size:16px;'>
            <div>
                <b style='color:#5bc0de;'>Liikenne</b><br>
                <a href='https://www.vr.fi/radalla/poikkeustilanteet' class='taksi-link' target='_blank'>VR Poikkeukset</a><br>
                <a href='{HSL_LINKKI}' class='taksi-link' target='_blank'>HSL Reittiopas</a><br>
                <a href='https://liikennetilanne.fintraffic.fi/' class='taksi-link' target='_blank'>Fintraffic Kartta</a>
            </div>
            <div>
                <b style='color:#5bc0de;'>Sää</b><br>
                <a href='https://www.ilmatieteenlaitos.fi/sade-ja-pilvialueet?area=etela-suomi' class='taksi-link' target='_blank'>Säätutka</a><br>
                <a href='https://www.ilmatieteenlaitos.fi/paikallissaa/helsinki' class='taksi-link' target='_blank'>Paikallissää</a>
            </div>
            <div>
                <b style='color:#5bc0de;'>Meriliikenne</b><br>
                <a href='https://averio.fi/laivat' class='taksi-link' target='_blank'>Averio (Matkustajat)</a><br>
                <a href='https://www.portofhelsinki.fi/matkustajille/matkustajatietoa/saapuvat-ja-lahtevat-laivat/' class='taksi-link' target='_blank'>Helsingin Satama</a>
            </div>
        </div>
        <hr style='border-color:#333;margin:16px 0;'>
        <div style='display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px;font-size:16px;'>
            <div>
                <b style='color:#5bc0de;'>Lentoliikenne</b><br>
                <a href='https://www.finavia.fi/fi/lentoasemat/helsinki-vantaa/lennot/saapuvat' class='taksi-link' target='_blank'>Finavia Saapuvat</a>
            </div>
            <div>
                <b style='color:#5bc0de;'>Business & Tapahtumat</b><br>
                <a href='https://tapahtumat.klubi.fi/tapahtumat/' class='taksi-link' target='_blank'>Suomalainen Klubi</a><br>
                <a href='https://messukeskus.com/kavijalle/tapahtumat/tapahtumakalenteri/' class='taksi-link' target='_blank'>Messukeskus</a><br>
                <a href='https://stadissa.fi/' class='taksi-link' target='_blank'>Stadissa.fi</a>
            </div>
            <div>
                <b style='color:#5bc0de;'>VR Korvaukset</b><br>
                <a href='https://www.vr.fi/asiakaspalvelu/korvaukset-ja-hyvitykset' class='taksi-link' target='_blank'>Lomake</a><br>
                <span style='color:#aaa;font-size:14px;'>Oikeutus: &gt;60 min myöhässä</span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<div style='color:#555; font-size:14px;text-align:center; margin-top:20px;'>TH Taktinen Tutka v6.3 | Päivittyy 5 min välein</div>", unsafe_allow_html=True)

if st.session_state.authenticated:
    render_dashboard()
