import yfinance as yf
import pandas as pd
import numpy as np
import json
import datetime
import os
import sys
import requests

CSV_PATH = 'portfolio.csv'
JSON_PATH = 'docs/data.json'

BENCHMARKS = {
    'Large': 'NIFTYBEES.NS',
    'Mid': 'MID150BEES.NS',
    'Small': 'SMA250BEES.NS'
}

def calc_max_drawdown(series):
    if series.empty: return 0.0
    roll_max = series.cummax()
    drawdown = series / roll_max - 1.0
    return drawdown.min()

def main():
    if not os.path.exists('docs'):
        os.makedirs('docs')

    df = pd.read_csv(CSV_PATH)
    df['Buy_Date'] = pd.to_datetime(df['Buy_Date'])
    earliest_date = df['Buy_Date'].min()

    tickers = df['Ticker'].unique().tolist()
    etfs = list(BENCHMARKS.values())
    all_tickers = tickers + etfs

    # Bypass Yahoo Finance blocking GitHub Actions IPs
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'})

    # threads=False prevents SQLite database locks
    hist_data = yf.download(all_tickers, start=earliest_date, group_by='ticker', threads=False, session=session)
    
    if hist_data.empty:
        print("Error: yfinance failed to download any data. Exiting.")
        sys.exit(1)

    prices = pd.DataFrame(index=hist_data.index)
    for t in all_tickers:
        if len(all_tickers) == 1:
             prices[t] = hist_data['Close']
        else:
             if t in hist_data.columns.levels[0]:
                 prices[t] = hist_data[t]['Close']
             else:
                 prices[t] = np.nan
                 
    prices.ffill(inplace=True)

    port_val = pd.Series(0.0, index=prices.index)
    bench_val = pd.Series(0.0, index=prices.index)

    live_info = []
    
    for _, row in df.iterrows():
        t = row['Ticker']
        qty = row['Quantity']
        buy_price = row['Buy_Price']
        buy_date = row['Buy_Date']
        cap = row['Cap_Category']
        bench_ticker = BENCHMARKS.get(cap, 'NIFTYBEES.NS')

        port_val[prices.index >= buy_date] += prices[t][prices.index >= buy_date] * qty
        
        initial_investment = qty * buy_price
        try:
            bench_buy_price = prices[bench_ticker].loc[prices.index >= buy_date].iloc[0]
        except IndexError:
            bench_buy_price = prices[bench_ticker].iloc[-1] if not prices[bench_ticker].dropna().empty else buy_price
            
        bench_qty = initial_investment / bench_buy_price
        bench_val[prices.index >= buy_date] += prices[bench_ticker][prices.index >= buy_date] * bench_qty

        ticker_obj = yf.Ticker(t, session=session)
        fast_info = ticker_obj.fast_info
        
        try:
            curr_price = fast_info['last_price']
            prev_close = fast_info['previous_close']
            day_change_pct = ((curr_price - prev_close) / prev_close) * 100
            mcap = fast_info['market_cap']
        except:
            curr_price = prices[t].iloc[-1] if not prices[t].dropna().empty else buy_price
            day_change_pct = 0
            mcap = 0

        info = ticker_obj.info
        sector = info.get('sector', 'N/A')
        pe = info.get('trailingPE', 'N/A')

        live_info.append({
            'ticker': t,
            'category': cap,
            'sector': sector,
            'qty': qty,
            'buy_price': buy_price,
            'curr_price': round(curr_price, 2),
            'day_change': round(day_change_pct, 2),
            'total_change': round(((curr_price - buy_price) / buy_price) * 100, 2),
            'mcap_cr': round(mcap / 10000000, 2) if mcap else 'N/A',
            'pe': round(pe, 2) if isinstance(pe, (int, float)) else pe,
            'value': round(curr_price * qty, 2)
        })

    days_held = (prices.index[-1] - earliest_date).days if not prices.empty else 1
    years_held = max(days_held / 365.25, 0.01)
    
    total_invested = (df['Quantity'] * df['Buy_Price']).sum()
    curr_port_val = port_val.iloc[-1] if not port_val.empty else total_invested
    curr_bench_val = bench_val.iloc[-1] if not bench_val.empty else total_invested
    
    port_ret = (curr_port_val / total_invested) - 1
    bench_ret = (curr_bench_val / total_invested) - 1
    
    port_cagr = ((curr_port_val / total_invested) ** (1 / years_held)) - 1
    bench_cagr = ((curr_bench_val / total_invested) ** (1 / years_held)) - 1

    dates_str = [d.strftime('%Y-%m-%d') for d in port_val.index]
    
    output = {
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'summary': {
            'invested': round(total_invested, 2),
            'port_value': round(curr_port_val, 2),
            'bench_value': round(curr_bench_val, 2),
            'port_return_pct': round(port_ret * 100, 2),
            'bench_return_pct': round(bench_ret * 100, 2),
            'port_cagr': round(port_cagr * 100, 2),
            'bench_cagr': round(bench_cagr * 100, 2),
            'port_max_dd': round(calc_max_drawdown(port_val) * 100, 2),
            'bench_max_dd': round(calc_max_drawdown(bench_val) * 100, 2)
        },
        'holdings': live_info,
        'chart': {
            'labels': dates_str,
            'portfolio': [round(v, 2) for v in port_val.tolist()],
            'benchmark': [round(v, 2) for v in bench_val.tolist()]
        }
    }

    with open(JSON_PATH, 'w') as f:
        json.dump(output, f)

if __name__ == "__main__":
    main()
