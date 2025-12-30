import yfinance as yf
import pandas as pd
import pandas_ta as ta
import datetime
import time
import pytz
from finvizfinance.screener.overview import Overview

# ==========================================
# 1. GLOBAL CONFIGURATION
# ==========================================
MODES = ["SCALP", "DAY", "SWING"]
INCLUDE_EXTENDED_HOURS = True 

# ==========================================
# 2. FINVIZ FILTER ENGINE
# ==========================================
def fetch_tickers_from_finviz(mode):
    print(f"\n🌍 Connecting to Finviz for [{mode}] candidates...")
    
    try:
        foverview = Overview()
        filters_dict = {}
        signal = ""
        
        # --- STRATEGY 1: SCALPER (In-Play) ---
        if mode == "SCALP":
            filters_dict = {
                'Price': 'Over $1',  # <--- UPDATED to $1
                'Relative Volume': 'Over 3',
                'Volatility': 'Month - Over 5%',
                'Average Volume': 'Over 500K'
            }
            signal = 'Top Gainers'

        # --- STRATEGY 2: DAY TRADER (Trend) ---
        elif mode == "DAY":
            filters_dict = {
                'Price': 'Over $5',  # <--- UPDATED to $5
                'Average Volume': 'Over 1M',
                'Relative Volume': 'Over 1.5',
                '20-Day Simple Moving Average': 'Price above SMA20',
                '50-Day Simple Moving Average': 'Price above SMA50'
            }
            signal = '' 

        # --- STRATEGY 3: POSITIONAL SWING (Base) ---
        elif mode == "SWING":
            filters_dict = {
                'Price': 'Price above SMA200',
                'Country': 'USA'
            }
            signals_to_check = ['Channel Up', 'Horizontal S/R', 'Wedge Up', 'Double Bottom']
            all_tickers = []
            
            for sig in signals_to_check:
                try:
                    time.sleep(0.5) 
                    print(f"   🔎 Scanning for pattern: {sig}...")
                    foverview.set_filter(signal=sig, filters_dict=filters_dict)
                    df = foverview.screener_view()
                    if df is not None and not df.empty:
                        print(f"      -> Found {len(df)} matches.")
                        all_tickers.extend(df['Ticker'].tolist())
                except:
                    pass
            
            unique = list(set(all_tickers))
            print(f"✅ Found {len(unique)} Swing candidates.")
            return unique

        foverview.set_filter(signal=signal, filters_dict=filters_dict)
        df = foverview.screener_view()
        
        if df is None or df.empty:
            print(f"❌ No {mode} stocks found.")
            return []
            
        tickers = df['Ticker'].tolist()
        if len(tickers) > 20: tickers = tickers[:20]
        
        print(f"✅ Found {len(tickers)} {mode} candidates.")
        return tickers

    except Exception as e:
        print(f"❌ Error fetching {mode} from Finviz: {e}")
        return []

# ==========================================
# 3. ANALYSIS ENGINE
# ==========================================
def analyze_ticker(ticker, mode):
    try:
        # 1. Settings
        if mode == "SCALP":
            timeframe = "5m"; hist_period = "5d"; 
            st_factor = 2.0; box_mult = 1.5
        elif mode == "DAY":
            timeframe = "1h"; hist_period = "1mo"; 
            st_factor = 3.0; box_mult = 2.0
        else: # SWING
            timeframe = "1d"; hist_period = "6mo"; 
            st_factor = 3.0; box_mult = 2.2

        # 2. Fetch Data
        df = yf.download(ticker, period=hist_period, interval=timeframe, prepost=INCLUDE_EXTENDED_HOURS, progress=False, auto_adjust=True)
        
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        if df.empty or len(df) < 30: return None

        # 3. Determine Session State
        last_time = df.index[-1]
        est = pytz.timezone('US/Eastern')
        if last_time.tzinfo is None:
            last_time = last_time.replace(tzinfo=pytz.utc).astimezone(est)
        else:
            last_time = last_time.astimezone(est)
            
        current_hour = last_time.hour
        current_minute = last_time.minute
        
        is_pre  = (current_hour < 9) or (current_hour == 9 and current_minute < 30)
        is_post = (current_hour >= 16)
        is_extended = is_pre or is_post

        # 4. Indicators
        df['EMA_Slow'] = ta.ema(df['Close'], length=50)
        df['ATR'] = ta.atr(df['High'], df['Low'], df['Close'], length=14)
        df['VWAP'] = ta.vwap(df['High'], df['Low'], df['Close'], df['Volume'])
        
        st = ta.supertrend(df['High'], df['Low'], df['Close'], length=10, multiplier=st_factor)
        if st is not None:
            st_dir_col = f'SUPERTd_10_{st_factor}'
            df['ST_Direction'] = st[st_dir_col]
        else:
             df['ST_Direction'] = 0

        # Box Logic
        df['Box_High'] = df['High'].rolling(window=20).max()
        df['Box_Low']  = df['Low'].rolling(window=20).min()
        df['Box_Range'] = df['Box_High'] - df['Box_Low']
        df['Vol_Avg'] = ta.sma(df['Volume'], length=50)

        # 5. Signal Logic
        curr = df.iloc[-1]
        prev = df.iloc[-2]

        # Standard Logic
        bullish_trend = curr['ST_Direction'] == 1
        is_tight = curr['Box_Range'] < (curr['ATR'] * box_mult)
        vol_spike = curr['Volume'] > (curr['Vol_Avg'] * 2.0)
        breakout = (curr['Close'] > prev['Box_High'])

        # Extended Hours Logic
        pct_change = 0.0
        if len(df) > 2:
            pct_change = ((curr['Close'] - prev['Close']) / prev['Close']) * 100

        # VWAP Check
        above_vwap = False
        if 'VWAP' in df.columns and not pd.isna(curr['VWAP']):
            above_vwap = curr['Close'] > curr['VWAP']

        # Scoring
        score = 0
        status = "WAIT"
        color = "#444"

        if is_extended:
            if pct_change > 0.5:
                if above_vwap:
                    status = "🔥 HIGH CONVICTION"
                    color = "#00ff00"
                    score = 95
                else:
                    status = "☀️ GAP UP (Weak)"
                    color = "#FFFF00"
                    score = 75
            elif pct_change < -0.5:
                status = "🔻 DUMPING"
                color = "#ff0000"
                score = 80
            elif vol_spike and above_vwap:
                status = "⚠️ LOADING UP"
                color = "#FFD700"
                score = 70
            else:
                status = "💤 QUIET"
                score = 10
        else:
            if bullish_trend: score += 20
            if is_tight: score += 20
            if vol_spike: score += 30
            if breakout: score += 30

            if breakout and vol_spike: status = "🚀 BREAKOUT"; color = "#00ff00"
            elif vol_spike and is_tight: status = "⚠️ PREP"; color = "#FFD700"
            elif is_tight and bullish_trend: status = "👀 WATCH"; color = "#00FFFF"

        last_time_str = last_time.strftime("%H:%M")

        return {
            "Ticker": ticker,
            "Price": round(curr['Close'], 2),
            "Vol": f"{round(curr['Volume']/1000, 1)}K" if curr['Volume'] < 1000000 else f"{round(curr['Volume']/1000000, 1)}M",
            "Time": last_time_str,
            "Session": "POST" if is_post else ("PRE" if is_pre else "MKT"),
            "Status": status,
            "Color": color,
            "Score": f"{score}%"
        }

    except Exception as e:
        return None

# ==========================================
# 4. DASHBOARD GENERATOR
# ==========================================
def generate_dashboard():
    
    full_report = {}
    print("🚀 STARTING 24/7 TRIDENT SCAN (V11)...")
    
    for mode in MODES:
        watchlist = fetch_tickers_from_finviz(mode)
        mode_results = []
        
        if watchlist:
            print(f"📊 Analyzing {len(watchlist)} {mode} tickers...")
            for ticker in watchlist:
                data = analyze_ticker(ticker, mode)
                if data: 
                    mode_results.append(data)
        
        if mode_results:
            mode_results = sorted(mode_results, key=lambda x: int(x['Score'].replace('%','')), reverse=True)
            
        full_report[mode] = mode_results

    # HTML Output
    html = f"""
    <html>
    <head>
        <title>Trident Market Radar (24/7)</title>
        <meta http-equiv="refresh" content="600"> 
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0d1117; color: #c9d1d9; padding: 20px; }}
            h1 {{ text-align: center; color: #238636; letter-spacing: 1px; }}
            .timestamp {{ text-align: center; color: #8b949e; margin-bottom: 30px; font-size: 0.9em; }}
            .section-title {{ 
                background: linear-gradient(90deg, #161b22, #30363d); 
                padding: 12px; border-left: 6px solid; margin-top: 40px; margin-bottom: 10px; 
                display: flex; justify-content: space-between; align-items: center;
                border-radius: 6px;
            }}
            .scalp-header {{ border-color: #f778ba; color: #f778ba; }}
            .day-header {{ border-color: #58a6ff; color: #58a6ff; }}
            .swing-header {{ border-color: #d29922; color: #d29922; }}
            table {{ width: 100%; border-collapse: collapse; background-color: #161b22; border-radius: 6px; overflow: hidden; }}
            th {{ background-color: #21262d; color: #8b949e; text-align: left; padding: 15px; font-size: 0.85em; text-transform: uppercase; letter-spacing: 0.5px; }}
            td {{ padding: 15px; border-bottom: 1px solid #30363d; font-size: 0.95em; }}
            tr:last-child td {{ border-bottom: none; }}
            tr:hover {{ background-color: #21262d; }}
            .tag {{ padding: 5px 10px; border-radius: 20px; font-weight: 600; color: #000; font-size: 0.75em; min-width: 90px; display: inline-block; text-align: center; }}
            .ticker {{ font-weight: 700; color: #fff; font-size: 1.1em; }}
            .session-tag {{ font-size: 0.7em; padding: 2px 6px; border-radius: 4px; margin-left: 8px; vertical-align: middle; }}
            .post {{ background-color: #3fb950; color: #000; }}
            .pre {{ background-color: #d29922; color: #000; }}
            .mkt {{ background-color: #58a6ff; color: #000; }}
        </style>
    </head>
    <body>
        <h1>🔱 TRIDENT MARKET RADAR (24/7)</h1>
        <div class="timestamp">Last Scan: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</div>
        <div style="text-align: center; margin-bottom: 20px; font-size: 0.8em; color: #666;">
            <i>Page auto-refreshes every 10 minutes.</i>
        </div>
    """

    mode_colors = {"SCALP": "scalp-header", "DAY": "day-header", "SWING": "swing-header"}
    
    for mode in MODES:
        results = full_report.get(mode, [])
        count = len(results)
        
        html += f"""
        <div class="section-title {mode_colors[mode]}">
            <span><h2>{mode} RADAR</h2></span>
            <span style="font-size: 0.9em; opacity: 0.8;">{count} Tickers Found</span>
        </div>
        <table>
            <thead>
                <tr>
                    <th width="15%">Ticker</th>
                    <th width="15%">Price</th>
                    <th width="15%">Last Candle</th>
                    <th width="10%">Session</th>
                    <th width="15%">Volume</th>
                    <th width="30%">Status</th>
                </tr>
            </thead>
            <tbody>
        """
        
        if not results:
            html += "<tr><td colspan='6' style='padding:20px; text-align:center; color:#666;'>No active signals found.</td></tr>"
        else:
            for row in results:
                text_col = "#000" if "HIGH CONVICTION" in row['Status'] or "BREAKOUT" in row['Status'] else "#fff"
                sess_class = row['Session'].lower()
                
                html += f"""
                <tr>
                    <td class="ticker">{row['Ticker']}</td>
                    <td>${row['Price']}</td>
                    <td>{row['Time']}</td>
                    <td><span class="session-tag {sess_class}">{row['Session']}</span></td>
                    <td>{row['Vol']}</td>
                    <td><span class="tag" style="background-color: {row['Color']}; color: {text_col}">{row['Status']}</span></td>
                </tr>
                """
        
        html += "</tbody></table>"

    html += "</body></html>"
    
    with open("dashboard_247.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    print("\n✅ DONE! Open 'dashboard_247.html' (Auto-refreshes every 10m).")

if __name__ == "__main__":
    generate_dashboard()