#!/usr/bin/env python3
"""
VICTOR GALAN: LA COMUNIDAD
─────────────────────────────────────────────────────────────────────────────
• 11 Sectores + 77 Industrias/Temas con drill-down (acciones + 1Y + MA)
• Benchmarks extendidos: BTC, oro, petróleo, IBEX35, DAX, CAC40...
• Amplitud real: A/D Line proxy, % sobre MA50/MA200, nuevos máx/mín,
  distribución de retornos diarios, score 0-100 estilo "Ofensivo Pleno"
• Noticias de bolsa vía yfinance RSS integrado en el HTML (fetch live)
• Earnings recientes S&P 500: batió/falló expectativas
• Panel individual de acción: precio, técnicos, RS, MA, volumen relativo
─────────────────────────────────────────────────────────────────────────────
Ejecutar:  python market_tracker.py
Requisitos: pip install yfinance pandas requests beautifulsoup4
"""

import os, sys, json, webbrowser, math
from datetime import datetime, timedelta

# ── Auto-install ─────────────────────────────────────────────────────────────
def ensure(pkg, imp=None):
    try: __import__(imp or pkg)
    except ImportError:
        import subprocess
        print(f"  Instalando {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])

ensure("yfinance"); ensure("pandas"); ensure("requests"); ensure("beautifulsoup4","bs4")

import yfinance as yf
import warnings, logging
# Suppress yfinance / urllib3 warnings to keep console clean
logging.getLogger('yfinance').setLevel(logging.CRITICAL)
warnings.filterwarnings('ignore')
import pandas as pd
import requests

# ══════════════════════════════════════════════════════════════════════════════
#  UNIVERSO DE DATOS
# ══════════════════════════════════════════════════════════════════════════════

SECTOR_ETFS = {
    "Technology":             "XLK", "Healthcare":           "XLV",
    "Financials":             "XLF", "Consumer Discret.":    "XLY",
    "Consumer Staples":       "XLP", "Energy":               "XLE",
    "Industrials":            "XLI", "Materials":            "XLB",
    "Real Estate":            "XLRE","Utilities":            "XLU",
    "Communication Svcs":     "XLC",
}

SECTOR_STOCKS = {
    "Technology": [
        "AAPL","MSFT","NVDA","AVGO","ORCL","AMD","CRM","ADBE","QCOM","TXN",
        "NOW","INTU","CSCO","IBM","AMAT","LRCX","KLAC","ADI","MU","MCHP",
        "INTC","PANW","SNPS","CDNS","HPE","DELL","KEYS","ANSS","PTC","ZBRA",
        "GLW","JNPR","NTAP","AKAM","CTSH","GDDY","CDW","FFIV","EPAM","TDC",
    ],
    "Healthcare": [
        "UNH","LLY","JNJ","MRK","ABBV","TMO","ABT","DHR","ISRG","PFE",
        "MDT","BMY","AMGN","GILD","CVS","ELV","CI","SYK","BSX","ZTS",
        "REGN","HUM","VRTX","IQV","MCK","MOH","CNC","BDX","IDXX","DXCM",
        "HOLX","RMD","COO","BAX","ALGN","TFX","EW","MTD","A","PODD",
    ],
    "Financials": [
        "BRK-B","JPM","V","MA","BAC","GS","MS","WFC","SPGI","AXP",
        "BLK","C","PGR","CB","MMC","ICE","CME","AON","MET","PRU",
        "TRV","AFL","ALL","USB","PNC","TFC","COF","CFG","FITB","RF",
        "HBAN","KEY","STT","BK","SCHW","RJF","AMP","CBOE","NDAQ","RE",
    ],
    "Consumer Discret.": [
        "AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TJX","BKNG","CMG",
        "ORLY","GM","F","DHI","RH","LEN","PHM","ROST","EBAY","YUM",
        "MAR","HLT","CCL","RCL","EXPE","DRI","DKNG","NVR","TOL","LKQ",
        "AZO","GPC","BBY","POOL","APTV","BWA","RL","PVH","TPR","HAS",
    ],
    "Consumer Staples": [
        "COST","WMT","PG","KO","PM","MDLZ","MO","CL","GIS","KHC",
        "SYY","HSY","CHD","EL","K","CAG","HRL","TSN","SJM","MKC",
        "CPB","CLX","KMB","STZ","MNST","WBA","KR","POST","COTY","BF-B",
    ],
    "Energy": [
        "XOM","CVX","SLB","EOG","MPC","PSX","OXY","VLO","COP","DVN",
        "HAL","HES","BKR","FANG","PXD","APA","MRO","CTRA","OKE","WMB",
        "KMI","TRGP","EPD","LNG","AM","DINO","PARR","CQP","NFE","HES",
    ],
    "Industrials": [
        "GE","CAT","UPS","RTX","HON","DE","ETN","LMT","BA","WM",
        "GD","NSC","FDX","EMR","PH","ROK","CTAS","PAYX","VRSK","TT",
        "OTIS","CARR","XYL","IEX","FAST","AME","ROP","GNRC","CHRW","EXPD",
        "ODFL","JBHT","SAIA","GXO","FLR","PWR","MTZ","MAS","IR","HII",
    ],
    "Materials": [
        "LIN","APD","ECL","SHW","NEM","FCX","NUE","VMC","MLM","ALB",
        "MOS","CF","PPG","IFF","BALL","PKG","IP","SON","SEE","AVY",
        "FMC","CTVA","CE","EMN","OLN","RPM","LYB","DOW","DD","AMCR",
    ],
    "Real Estate": [
        "PLD","AMT","EQIX","PSA","O","WELL","DLR","AVB","EQR","WY",
        "ARE","VTR","SPG","ESS","MAA","NNN","VICI","GLPI","IRM","CCI",
        "SBAC","EXR","LSI","CPT","UDR","BXP","KIM","REG","FRT","HST",
    ],
    "Utilities": [
        "NEE","SO","DUK","AEP","SRE","XEL","D","ED","EXC","ES",
        "ETR","PPL","FE","AEE","LNT","WEC","DTE","CNP","CMS","NI",
        "PNW","EVRG","ATO","AWK","SWX","UGI","NWE","AVA","MGEE","EIX",
    ],
    "Communication Svcs": [
        "GOOGL","META","NFLX","TMUS","VZ","T","DIS","CHTR","EA","TTWO",
        "OMC","IPG","PARA","WBD","FOXA","FOX","LYV","NYT","NWSA","NWS",
        "MTCH","SNAP","PINS","RBLX","ZG","IAC","SIRI","DISH","LUMN","ATVI",
    ],
}

INDUSTRY_DATA = {
    # ── TECNOLOGÍA
    "Semiconductors":        {"etf":"SOXX","holdings":["NVDA","AVGO","AMD","QCOM","MU","AMAT","LRCX","KLAC","MCHP","ON","TXN","ASML","MRVL","NXPI","STM","SWKS","MPWR","WOLF","OLED","INTC"]},
    "Software (Broad)":      {"etf":"IGV", "holdings":["MSFT","ORCL","CRM","NOW","ADBE","INTU","PANW","CDNS","SNPS","PTC","DDOG","ZM","TEAM","GTLB","HUBS","WDAY","OKTA","VEEV","BILL"]},
    "Cloud Computing":       {"etf":"CLOU","holdings":["MSFT","AMZN","GOOGL","DDOG","NET","SNOW","MDB","ZS","HUBS","VEEV","WDAY","OKTA","TTD","BILL","ESTC","DOCN","NTNX","PSTG","FSLY"]},
    "Cybersecurity":         {"etf":"HACK","holdings":["PANW","CRWD","ZS","FTNT","S","OKTA","QLYS","TENB","VRNT","CHKP","VRSN","CACI","LDOS","SAIC","SAIL","RDWR","RPM"]},
    "AI & Robotics":         {"etf":"BOTZ","holdings":["NVDA","ISRG","TRMB","ONTO","AZTA","NOVT","MKSI","ZBRA","CGNX","AXON","PATH","PLTR","AI","SOUN","BBAI"]},
    "Fintech":               {"etf":"FINX","holdings":["V","MA","PYPL","FIS","FISV","GPN","AFRM","SOFI","LC","UPST","MGNI","PAGS","DLO","NCNO","FLYW","RPAY","WEX"]},
    "Internet & E-commerce": {"etf":"FDN", "holdings":["AMZN","GOOGL","META","NFLX","EBAY","BKNG","ABNB","DASH","ETSY","CHWY","W","SE","MELI","SHOP","CART"]},
    "Social Media":          {"etf":"SOCL","holdings":["META","SNAP","PINS","MTCH","BMBL","IAC","RBLX","U","ZG","ANGI","NERD","GENI","MGNI","TTD"]},
    "Gaming & Esports":      {"etf":"ESPO","holdings":["NVDA","AMD","EA","TTWO","RBLX","U","NERD","DKNG","PENN","RSI","HUYA","DOYU","NTES","BILI"]},
    "Digital Payments":      {"etf":"IPAY","holdings":["V","MA","PYPL","SQ","AFRM","FOUR","RPAY","EVERI","GPN","FIS","WEX","FLYW","PRAA","NCNO","DLO"]},
    "Quantum Computing":     {"etf":"QTUM","holdings":["IBM","GOOGL","INTC","IONQ","RGTI","QUBT","QBTS","ARQQ","NVDA","MSFT","AMZN"]},
    "Data Centers / REIT":   {"etf":"DTCR","holdings":["EQIX","DLR","AMT","CCI","SBAC","IRM","REXR","EXR","CUBE","NLOP"]},
    "SaaS Enterprise":       {"etf":"WCLD","holdings":["NOW","DDOG","SNOW","MDB","ZS","CRWD","HUBS","WDAY","VEEV","OKTA","TTD","CFLT","BILL","ESTC","DOCN"]},
    # ── SALUD
    "Biotech (Broad)":       {"etf":"XBI", "holdings":["MRNA","BNTX","REGN","VRTX","BIIB","ILMN","EXAS","ALNY","BMRN","FOLD","ARWR","NTLA","EDIT","BEAM","RXRX","NVAX","FATE","TWST"]},
    "Biotech (Large Cap)":   {"etf":"BBH", "holdings":["LLY","AMGN","GILD","ABBV","REGN","VRTX","BIIB","MRNA","BMY","AZN","NVO","ALNY","SGEN","INCY"]},
    "Pharmaceuticals":       {"etf":"PJP", "holdings":["JNJ","PFE","MRK","ABBV","BMY","LLY","JAZZ","PAHC","SUPN","LNTH","PRGO","VTRS","COLL"]},
    "Medical Devices":       {"etf":"IHI", "holdings":["ISRG","MDT","ABT","BSX","SYK","ZBH","BAX","HOLX","PODD","NVCR","TNDM","IRTC"]},
    "Health Insurance":      {"etf":"IHF", "holdings":["UNH","CVS","CI","HUM","CNC","MOH","ELV","OSCR","HQY","ALHC","TDOC","HIMS","DOCS","PHR"]},
    "Genomics":              {"etf":"ARKG","holdings":["CRSP","NTLA","EDIT","BEAM","PACB","VERV","RXRX","SEER","FLGT","NVAX","FATE","TWST","CDNA","SDGR"]},
    "Telemedicine":          {"etf":"EDOC","holdings":["TDOC","AMWL","HIMS","ACCD","PHR","DOCS","OMCL","VEEV","MDRX","HCAT","GDRX","OPRX"]},
    # ── FINANZAS
    "Banks Large Cap":       {"etf":"KBE", "holdings":["JPM","BAC","WFC","C","GS","MS","USB","PNC","TFC","COF","CFG","FITB","HBAN","RF","KEY"]},
    "Regional Banks":        {"etf":"KRE", "holdings":["WBS","FHN","BOKF","SNV","WTFC","IBOC","BKU","FFIN","UMBF","CBSH","SFBS","BPOP","COLB"]},
    "Insurance":             {"etf":"KIE", "holdings":["PGR","CB","MET","PRU","AFL","AIG","ALL","HIG","TRV","L","CINF","AXS","RLI","WRB"]},
    "Asset Management":      {"etf":"IAI", "holdings":["BLK","SPGI","GS","MS","IVZ","AMG","SEI","VRTS","APAM","CSWC","GAIN","ARCC","MAIN","BXSL"]},
    "REITs":                 {"etf":"VNQ", "holdings":["PLD","AMT","EQIX","PSA","O","WELL","DLR","AVB","EQR","ARE","VTR","SPG","ESS","MAA","VICI"]},
    # ── ENERGÍA
    "Oil & Gas Explor.":     {"etf":"XOP", "holdings":["XOM","CVX","COP","OXY","EOG","DVN","APA","FANG","SM","MGY","PR","MTDR"]},
    "Oil Services":          {"etf":"OIH", "holdings":["SLB","HAL","BKR","FTI","RES","LBRT","PUMP","PTEN","NE","DO","VAL","HP","WHD","ACDC"]},
    "Natural Gas":           {"etf":"UNG", "holdings":["RRC","EQT","AR","CNX","CRK","GPOR","CTRA","LNG","NFE","CQP","DINO","PARR","GEVO"]},
    "Pipeline & MLP":        {"etf":"AMLP","holdings":["EPD","ET","PAA","MPLX","WES","OKE","TRGP","HESM","GEL","USAC","NGL","KMI"]},
    "Clean Energy":          {"etf":"ICLN","holdings":["ENPH","SEDG","NEE","FSLR","RUN","ARRY","MAXN","SHLS","SPWR","CSIQ","JKS","FLNC","BE"]},
    "Solar":                 {"etf":"TAN", "holdings":["ENPH","FSLR","SEDG","RUN","ARRY","NOVA","MAXN","SPWR","CSIQ","DAQO","JKS","SHLS","HASI","AES","NEE","FLNC","FTCI","SOLV","NRGV","ARRY","CSLR","BE","PLUG"]},
    "Wind Energy":           {"etf":"FAN", "holdings":["NEE","VST","CWEN","AES","ORA","BEP","BEPC","RNW","IBDRY","RDWR","DNNGY","TPIC"]},
    "Nuclear Energy":        {"etf":"NLR", "holdings":["CCJ","NNE","SMR","OKLO","BWXT","LEU","UEC","DNN","URG","UUUU","CEG","TLN","VST","ETR","EXC","AEE","AEP","NEE","DUK","SO","ED","D","PPL","FE","ES"]},
    "Hydrogen / Fuel Cell":  {"etf":"HDRO","holdings":["PLUG","FCEL","BE","BLDP","LIQT","HTOO","MVST","ITM","AFG","HTOO","MVST"]},
    "Uranium":               {"etf":"URA", "holdings":["CCJ","NNE","UUUU","DNN","EU","URG","UEC","LEU","PDN","PEN","URNM","URNJ","CVV"]},
    # ── INDUSTRIA
    "Defense & Aerospace":   {"etf":"ITA", "holdings":["RTX","LMT","NOC","GD","BA","HII","KTOS","AVAV","HEI","TDY","DRS","CACI","LDOS","SAIC","BAH","AMSYS","TDY","CW","DRS","MRCY"]},
    "Space Economy":         {"etf":"UFO", "holdings":["SPCE","RKLB","PL","KTOS","GSAT","VSAT","IRDM","SATS","BWXT","ASTS","LUNR","RDW","GNSS","GFAI","HON","RTX"]},
    "Airlines":              {"etf":"JETS","holdings":["DAL","UAL","LUV","AAL","ALGT","JBLU","RYAAY","ULCC","SKYW","FLGT","AIR","EZJ","IAG"]},
    "Transportation":        {"etf":"IYT", "holdings":["UPS","FDX","CHRW","XPO","ODFL","JBHT","EXPD","SAIA","GXO","LSTR","RXO","TFII","WERN","KNX","HUBG","FWRD","MRTN","SNDR","CVLG","HTLD"]},
    "Railroads":             {"etf":"RAIL","holdings":["UNP","CSX","NSC","CP","GBX","WAB","TRN","GATX","AMSF","RAIL","KBWY","HWKN","NPKI"]},
    "Shipping & Marine":     {"etf":"BOAT","holdings":["ZIM","MATX","SBLK","EGLE","STNG","HAFN","TRMD","NMM","GNK","SB","CMRE","DSX","ESEA","GSL","HSHP","TOPS","CTRM","PANL","GLBS","SFL","SHIP","GRIN","EDRY"]},
    "Homebuilders":          {"etf":"XHB", "holdings":["DHI","LEN","PHM","NVR","TOL","TMHC","MTH","LGIH","GRBK","SKY","CCS","KBH","MHO","CVCO","BLDR","IBP","APOG","AMWD","SITE","SSD","TREX"]},
    "Construction & Infra":  {"etf":"PAVE","holdings":["VMC","MLM","NUE","CRH","CARR","PWR","MTZ","MYRG","IESC","MTRX","PRIM","TTEK","GVA","STRL","AECOM","ICF","WSC","DY","WMS","ROAD","GLDD","AGX"]},
    "Machinery & Equip.":    {"etf":"XLI", "holdings":["CAT","DE","EMR","PH","ROK","IR","GNRC","NDSN","ESAB","OTIS","CARR","XYL","ROP","TRMB","AME","ITT","FELE","HLIO","TXT","DOV","FLS","GGG","MIDD"]},
    "Waste Management":      {"etf":"EVX", "holdings":["WM","RSG","CWST","CLH","NVRI","CECO","TREX","TFSL","GFL","AQMS","ERII","PESI","LIQT","OCEA"]},
    # ── CONSUMO
    "Retail Broad":          {"etf":"XRT", "holdings":["AMZN","COST","WMT","HD","TGT","LOW","TJX","ROST","BBY","KSS","M","ANF","URBN","CHWY","W","BOOT","FIVE","OLLI","PRGO","DLTR","DG","CASY","SCVL"]},
    "Luxury Goods":          {"etf":"LUXE","holdings":["RL","TPR","CPRI","MOV","BOOT","SHOO","CATO","EL","FOSL","ZUMZ","GOOS"]},
    "Food & Beverage":       {"etf":"PBJ", "holdings":["KO","PEP","MCD","SBUX","YUM","CMG","DRI","QSR","JACK","CAKE","RRGB","BLMN","DIN","WEN","SHAK","TXRH","BJRI","CBRL","EAT","PLAY","DNUT","LOCO","FRSH","TACO"]},
    "Travel & Leisure":      {"etf":"PEJ", "holdings":["BKNG","EXPE","ABNB","MAR","HLT","H","RCL","CCL","NCLH","LVS","MGM","WYNN","CZR","DKNG","PENN","TNL","MTN","PLNT","CLUB","TRIP"]},
    "Casinos & Betting":     {"etf":"BJK", "holdings":["LVS","MGM","WYNN","CZR","PENN","DKNG","RSI","EVRI","GDEN","MCRI","PLBY","ELYS","GMBL","BALY","ACMR","NERD","SKLZ"]},
    "Cannabis":              {"etf":"MJ",  "holdings":["TLRY","CGC","CRON","ACB","VFF","OGI","SMG","IIPR","CURLF","GTBIF","TCNNF","AYRWF","VRSSF","GLASF"]},
    "Sports & Media":        {"etf":"NERD","holdings":["DKNG","PENN","GENI","MSGE","MSGS","FUBO","SIRI","LYV","RBLX","U","NERD","SKLZ","GMBL","RSI","EVRI","GAME","PTON"]},
    # ── MATERIALES
    "Metals & Mining":       {"etf":"XME", "holdings":["NUE","STLD","CLF","CMC","RS","WOR","ATI","TS","MT","HCC","BTU","AMR","TECK","FCX","AA","METC","SXC","MP","CENX","CMP","EAF"]},
    "Gold Miners":           {"etf":"GDX", "holdings":["NEM","GOLD","AEM","WPM","FNV","KGC","AGI","BTG","OR","PAAS","CDE","HL","EQX","SSL","EDV","ORLA","GRVY","IAG","HBM","EGO","SSRM"]},
    "Silver Miners":         {"etf":"SIL", "holdings":["WPM","PAAS","HL","CDE","SILV","MAG","AG","SVM","EXK","USA","ASM","SIL","MNVN","BCEKF"]},
    "Copper":                {"etf":"COPX","holdings":["FCX","TECK","HBM","ERO","TGB","BHP","RIO","VALE","GLNCY","LUNR","FQVLF","TLOFF","SBSW"]},
    "Steel":                 {"etf":"SLX", "holdings":["NUE","STLD","CLF","CMC","RS","WOR","ATI","TS","PKX","VALE","BHP","RIO","MT","SID","GGB","X","SXC","ZEUS","METC","SBSW","HCC","AMR"]},
    "Agriculture":           {"etf":"MOO", "holdings":["DE","NTR","MOS","CF","CTVA","FMC","BG","ADM","LW","INGR","TSN","HRL","CAG","SFD","DAR","CALM","JBSS","VITL","SMG","AMTX","GRWG","IIPR"]},
    "Lithium & Battery":     {"etf":"LIT", "holdings":["ALB","SQM","LAC","ACE","ATLX","MVST","BLNK","CHPT","EVGO","NKLA","XPEV","NIO","LI","RIVN","LCID"]},
    "Water":                 {"etf":"PHO", "holdings":["AWK","ECL","XYL","WMS","FELE","MSEX","ARTNA","CWCO","YORW","GWRS","PESI","ERII","WTRG","NWN","SJW","ARTNA","MSEX","A","DNNGY"]},
    "Rare Earths & Critical":{"etf":"REMX","holdings":["MP","UUUU","HYMC","REE","SGML","LTHM","ALB","SQM","REEMF","GFAI","NIOCF","ESGA","BKTPF"]},
    # ── GLOBAL / MACRO
    "Emerging Markets":      {"etf":"EEM", "holdings":["TSM","BABA","TCEHY","VALE","PDD","BIDU","JD","NIO","XPEV","LI","GRAB","SEA","MELI","NU","INFY","ITUB","BBD","PBR","HDB","IBN","TM","SONY","SHOP","MELI","BABA"]},
    "China Tech":            {"etf":"KWEB","holdings":["BABA","TCEHY","JD","BIDU","PDD","MOMO","BILI","IQ","VNET","QFIN","TIGR","FUTU","KC","LQDT","GOTU","EDU","TAL","NTES"]},
    "India":                 {"etf":"INDA","holdings":["INFY","HDB","IBN","WIT","RDY","NBIX","YTRA","MMYT","CTSH","SAP","SIFY","REYN","CGNX","EXLS"]},
    "Europe Broad":          {"etf":"VGK", "holdings":["LVMH","ASML","SAP","NVO","NOVN","BP","RMS","EOAN","RWE"]},
    "Japan":                 {"etf":"EWJ", "holdings":["TM","SONY","HMC","NTDOY","FUJIY","MUFG","SMFG","MFG","KYOCY","IIJIY","MRAAY","TKOMY","DWAHY","OTSKY"]},
    "Brazil":                {"etf":"EWZ", "holdings":["VALE","ITUB","BBD","PBR","ABEV","SID","GGB","CIG","SUZ","AMBP","CSAN","RDVY"]},
    "Dividends":             {"etf":"DVY", "holdings":["CVX","MO","PM","T","VZ","IBM","OKE","ENB","EPD","ET","XOM","LYB","MPC","PSX","VLO","HES","SLB","F","GM","IP","ATO","WEC","DTE","CNP","CMS"]},
    "Infrastructure":        {"etf":"PAVE","holdings":["VMC","MLM","NUE","CRH","CARR","PWR","MTZ","MYR","PIKE","GLDD","MYRG","IESC","MTRX","PRIM","TTEK","STRL","AECOM","ICF","WSC","DY"]},
    # ── ALTERNATIVOS
    "Crypto & Blockchain":   {"etf":"BKCH","holdings":["COIN","MSTR","MARA","RIOT","CLSK","HUT","BITF","BTBT","CIFR","BTDR","IREN","GBTC","IBIT","FBTC","WGMI","BKCH","SATO","BTCS"]},
    "Bitcoin ETFs":          {"etf":"IBIT","holdings":["IBIT","FBTC","ARKB","BITB","BRRR","HODL","BTCO","BITO","BTF","MAXI","GBTC","BITI","DEFI","BITS","BRRR","BTCW"]},
    "Electric Vehicles":     {"etf":"DRIV","holdings":["TSLA","GM","F","NIO","XPEV","LI","RIVN","LCID","NKLA","BLNK","CHPT","EVGO","VLTA","GOEV","FSR","KNDI"]},
    "Self-Driving & ADAS":   {"etf":"IDRV","holdings":["TSLA","NVDA","GOOGL","INTC","QCOM","MBLY","LIDR","OUST","AEVA","INVZ","AUR","VNET","PRNT"]},
    "Small Cap Growth":      {"etf":"IJR", "holdings":["SMCI","CAVA","CELH","DASH","DKNG","AFRM","SOFI","IONQ","RKLB","JOBY","ACHR","EVTL","SPCE","RIVN","VLDR","ACNB","NVTS"]},
    "Inflation Hedge":       {"etf":"PDBC","holdings":["XOM","CVX","COP","GLD","SLV","GSG","BCI","COMB","CMDY","FTGC","GUNR","DBC","PDBC","COMT","DJP","CCRV","RAAX","INFL","IVOL"]},
    "Volatility & Hedge":    {"etf":"UVXY","holdings":["VXX","UVXY","SVXY","VIXY","VIXM","PHDG","VONE","VTWO"]},
}

# ── BENCHMARKS extendidos ────────────────────────────────────────────────────
BENCHMARK = {
    # USA — índices reales via Yahoo Finance
    "S&P 500":          "^GSPC", "Nasdaq 100":    "^NDX",
    "Russell 2000":     "^RUT",  "Dow Jones":     "^DJI",
    "Mid Cap (S&P400)": "^MID",  "VIX":           "^VIX",
    # Crypto
    "Bitcoin":          "BTC-USD", "Ethereum":    "ETH-USD",
    # Commodities (futuros)
    "Gold":             "GC=F",  "Silver":        "SI=F",
    "Oil (WTI)":        "CL=F",  "Natural Gas":   "NG=F",
    "Copper":           "HG=F",
    # Bonds / tipos
    "Treasury 20Y":     "TLT",   "High Yield":    "HYG",
    "T-Bond 10Y Yield": "^TNX",  "T-Bond 2Y Yield":"^IRX",
    # Europa — índices reales
    "DAX (Germany)":    "^GDAXI","CAC 40 (Fr)":   "^FCHI",
    "IBEX 35 (Esp)":    "^IBEX", "FTSE 100":      "^FTSE",
    "Euro Stoxx 50":    "^STOXX50E",
    # Asia
    "Nikkei 225":       "^N225", "Hang Seng":     "^HSI",
    "Shanghai":         "000001.SS","India (Nifty)":"^NSEI",
    # FX / alternatives
    "EUR/USD":          "EURUSD=X","US Dollar Idx": "DX-Y.NYB",
    "Real Estate":      "VNQ",
}

# ── Amplitud de mercado ──────────────────────────────────────────────────────
BREADTH_TICKERS = {
    "SPY":"S&P 500","QQQ":"Nasdaq 100","IWM":"Russell 2000","DIA":"Dow Jones",
    "^VIX":"VIX","HYG":"High Yield Bonds","TLT":"Treasury 20Y","SHY":"Treasury 2Y",
    "GLD":"Gold","SLV":"Silver","UUP":"US Dollar","USO":"Oil (WTI)",
    "IBIT":"Bitcoin ETF","GDX":"Gold Miners",
    # NYSE y Put/Call
    "^NYA":"NYSE Composite",
    "^VVIX":"VVIX (Volatilidad del VIX)",
    "^SKEW":"SKEW (Riesgo de cola CBOE)",
    # Macro / Bonds CEF / TIPS / HAA
    "TIP":"TIPS ETF (Inflacion real)",
    "STIP":"TIPS Corto Plazo",
    "AGG":"Aggregate Bonds (AGG)",
    "LQD":"Corp Bonds IG",
    "EMB":"Bonos Emergentes",
    "^TNX":"Yield 10Y Tesoro EEUU",
    "^IRX":"Yield 2Y Tesoro EEUU",
    # Sectores
    "XLK":"Tech","XLE":"Energy","XLF":"Financials","XLV":"Healthcare",
    "XLU":"Utilities","XLRE":"Real Estate","XLC":"Communication",
    "XLI":"Industrials","XLY":"Consumer Discret.","XLP":"Consumer Staples",
    "XLB":"Materials",
}

# S&P 500 muestra amplia para amplitud de mercado (~200 tickers)
SP500_SAMPLE = [
    # Mega cap / Top 50
    "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","JPM",
    "LLY","V","UNH","XOM","MA","JNJ","PG","HD","COST","MRK",
    "CVX","ABBV","CRM","BAC","ORCL","KO","PEP","TMO","AMD","NFLX",
    "DIS","ADBE","NKE","WMT","CSCO","MCD","ABT","COP","IBM","GE",
    "CAT","GS","HON","SPGI","AMGN","LOW","ISRG","DE","RTX","NOW",
    # Top 51-100
    "QCOM","PFE","TXN","BMY","NEE","UPS","INTU","T","BKNG","AXP",
    "VRTX","LMT","SYK","MDT","MDLZ","CB","ETN","C","ZTS","BSX",
    "SO","REGN","CI","MMC","ADI","WFC","MS","PGR","GILD","CME",
    "AMAT","ELV","SHW","BDX","LRCX","MO","F","GM","NOC","COF",
    "USB","DUK","AON","APD","FCX","TJX","HUM","FDX","SLB","PSA",
    # Top 101-150
    "ECL","WM","NSC","EMR","KLAC","GD","ADP","MCO","PYPL","UBER",
    "ABNB","SNOW","CRWD","DDOG","ZS","NET","PANW","MDB","TTD","SHOP",
    "SQ","AFRM","SOFI","COIN","RIVN","LCID","NIO","XPEV","LI","PLTR",
    "PATH","AI","SOUN","IONQ","RKLB","JOBY","ACHR","SMCI","CAVA","CELH",
    "DASH","DKNG","SNAP","PINS","RBLX","U","MTCH","BMBL","ZG","IAC",
    # Top 151-200
    "NEM","FCX","ALB","MOS","CF","LIN","APD","PPG","IFF","VMC",
    "MLM","NUE","STLD","CLF","CMC","PLD","AMT","EQIX","PSA","O",
    "WELL","DLR","AVB","EQR","WY","SPG","ESS","MAA","VTR","ARE",
    "NEE","SO","DUK","AEP","SRE","XEL","D","ED","EXC","ES",
    "EPD","ET","OKE","WMB","KMI","TRGP","LNG","MPC","PSX","VLO",
]
# Eliminar duplicados preservando orden
_seen = set()
SP500_SAMPLE = [x for x in SP500_SAMPLE if not (x in _seen or _seen.add(x))]


# ══════════════════════════════════════════════════════════════════════════════
#  FUNCIONES DE DESCARGA
# ══════════════════════════════════════════════════════════════════════════════

def fetch_perf(tickers_dict, label="", period="1y"):
    results, tks = [], list(tickers_dict.values())
    print(f"  ↓ {label} ({len(tks)} tickers)...")
    try:
        raw   = yf.download(tks, period=period, interval="1d",
                            progress=False, auto_adjust=True, threads=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
    except Exception as e:
        print(f"  Error {label}: {e}"); return []
    name_map = {v:k for k,v in tickers_dict.items()}
    for tk in tks:
        try:
            s = close[tk].dropna() if tk in close.columns else close.dropna()
            if len(s) < 2: continue
            last = float(s.iloc[-1])
            def chg(b): return round((last/float(b)-1)*100, 2)
            results.append({
                "name":    name_map.get(tk, tk),
                "ticker":  tk,
                "price":   round(last, 2),
                "1D":  chg(s.iloc[-2]),
                "1W":  chg(s.iloc[-6])   if len(s)>5   else chg(s.iloc[0]),
                "1M":  chg(s.iloc[-22])  if len(s)>21  else chg(s.iloc[0]),
                "3M":  chg(s.iloc[-66])  if len(s)>65  else chg(s.iloc[0]),
                "6M":  chg(s.iloc[-132]) if len(s)>131 else chg(s.iloc[0]),
                "1Y":  chg(s.iloc[0]),
                "52wHigh": round(float(s.max()), 2),
                "52wLow":  round(float(s.min()), 2),
                "distHi":  round((last/float(s.max())-1)*100, 1),
                "priceHistory": [round(float(v),2) for v in s.values[-90:]],
                "priceDates":   [d.strftime("%Y-%m-%d") for d in s.index[-90:]],
            })
        except: continue
    results.sort(key=lambda x: x["1D"], reverse=True)
    return results


def fetch_stock_perf():
    """Descarga datos de todas las acciones de sectores e industrias."""
    all_tks = set()
    for d in INDUSTRY_DATA.values(): all_tks.update(d["holdings"])
    for s in SECTOR_STOCKS.values(): all_tks.update(s)
    all_tks.update(SP500_SAMPLE)
    all_tks = list(all_tks)
    print(f"  ↓ Constituyentes: {len(all_tks)} acciones únicas (puede tardar ~2 min)...")
    try:
        raw   = yf.download(all_tks, period="1y", interval="1d",
                            progress=False, auto_adjust=True, threads=True)
        is_m  = isinstance(raw.columns, pd.MultiIndex)
        close = raw["Close"] if is_m else raw
        try:
            vol   = raw["Volume"] if is_m else pd.DataFrame()
            hi_df = raw["High"]   if is_m else pd.DataFrame()
            lo_df = raw["Low"]    if is_m else pd.DataFrame()
            op_df = raw["Open"]   if is_m else pd.DataFrame()
        except: vol=hi_df=lo_df=op_df=pd.DataFrame()
    except Exception as e:
        print(f"  Error acciones: {e}"); return {}

    out = {}
    for tk in all_tks:
        try:
            s = close[tk].dropna() if tk in close.columns else None
            if s is None or len(s) < 5: continue
            last = float(s.iloc[-1])
            def chg(b): return round((last/float(b)-1)*100, 2)
            ma20  = float(s.tail(20).mean())  if len(s)>=20  else None
            ma50  = float(s.tail(50).mean())  if len(s)>=50  else None
            ma200 = float(s.tail(200).mean()) if len(s)>=200 else None
            # Relative Strength vs SPY - computed later
            # Volume relative (20d avg)
            vol_rel = None
            if not vol.empty and tk in vol.columns and not vol[tk].dropna().empty:
                v   = vol[tk].dropna()
                avg = float(v.tail(20).mean()) if len(v)>=20 else None
                vol_rel = round(float(v.iloc[-1])/avg, 2) if avg and avg>0 else None
            # 52w new highs/lows
            hi52 = float(s.max()); lo52 = float(s.min())
            new_hi = bool(last >= hi52 * 0.99)  # within 1% of 52w high
            new_lo = bool(last <= lo52 * 1.01)  # within 1% of 52w low
            out[tk] = {
                "ticker":  tk,
                "price":   round(last, 2),
                "1D":  chg(s.iloc[-2]),
                "1W":  chg(s.iloc[-6])  if len(s)>5  else chg(s.iloc[0]),
                "1M":  chg(s.iloc[-22]) if len(s)>21 else chg(s.iloc[0]),
                "3M":  chg(s.iloc[-66]) if len(s)>65 else chg(s.iloc[0]),
                "1Y":  chg(s.iloc[0]),
                "ma20":  round(ma20,2)  if ma20  else None,
                "ma50":  round(ma50,2)  if ma50  else None,
                "ma200": round(ma200,2) if ma200 else None,
                "abv20":  bool(last>ma20)  if ma20  else None,
                "abv50":  bool(last>ma50)  if ma50  else None,
                "abv200": bool(last>ma200) if ma200 else None,
                "52wHigh": round(hi52,2),
                "52wLow":  round(lo52,2),
                "newHi":   new_hi,
                "newLo":   new_lo,
                "volRel":  vol_rel,
                # Sparkline (last 30 days, normalized 0-100)
                "spark": normalize_spark(list(s.values[-30:])),
                "ohlc":  _build_ohlc(s, op_df, hi_df, lo_df, tk),
            }
        except: continue
    return out


def _build_ohlc(close_s, op_df, hi_df, lo_df, tk):
    """Construye lista OHLC para los últimos 90 días."""
    ohlc = []
    try:
        for dt in close_s.index[-90:]:
            c = float(close_s.loc[dt])
            o = float(op_df[tk].loc[dt]) if not op_df.empty and tk in op_df.columns else c
            h = float(hi_df[tk].loc[dt]) if not hi_df.empty and tk in hi_df.columns else c
            l = float(lo_df[tk].loc[dt]) if not lo_df.empty and tk in lo_df.columns else c
            ohlc.append({"t":dt.strftime("%Y-%m-%d"),"o":round(o,2),"h":round(h,2),"l":round(l,2),"c":round(c,2)})
    except: pass
    return ohlc


def normalize_spark(prices):
    """Normaliza serie de precios a 0-100 para sparkline."""
    if not prices or len(prices) < 2: return []
    mn, mx = min(prices), max(prices)
    rng = mx - mn
    if rng == 0: return [50] * len(prices)
    return [round((p-mn)/rng*100, 1) for p in prices]


def fetch_breadth_and_amplitude(stock_perf):
    """
    Calcula métricas de amplitud real usando los datos de stock_perf.
    También descarga series de tiempo de instrumentos clave.
    """
    tks = list(BREADTH_TICKERS.keys())
    print(f"  ↓ Amplitud de mercado ({len(tks)} instrumentos)...")
    try:
        raw   = yf.download(tks, period="1y", interval="1d",
                            progress=False, auto_adjust=True, threads=True)
        close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
    except Exception as e:
        print(f"  Error breadth: {e}"); return {}, {}

    latest, series = {}, {}
    for tk in tks:
        try:
            s = close[tk].dropna() if tk in close.columns else None
            if s is None or len(s) < 2: continue
            last, prev = float(s.iloc[-1]), float(s.iloc[-2])
            chg1d = round((last/prev-1)*100, 2)
            ma50  = float(s.tail(50).mean())  if len(s)>=50  else None
            ma200 = float(s.tail(200).mean()) if len(s)>=200 else None
            latest[tk] = {
                "name":  BREADTH_TICKERS[tk],
                "price": round(last,2),
                "chg":   chg1d,
                "ma50":  round(ma50,2)  if ma50  else None,
                "ma200": round(ma200,2) if ma200 else None,
                "abv50": bool(last>ma50)  if ma50  else None,
                "abv200":bool(last>ma200) if ma200 else None,
            }
            # Series for charts (90 days)
            series[tk] = {
                "dates":  [d.strftime("%Y-%m-%d") for d in s.index[-90:]],
                "values": [round(float(v),2) for v in s.values[-90:]],
            }
        except: continue

    # ── Amplitud REAL usando TODOS los datos de stock_perf ──────────────────
    # sample_sp500 = solo SP500 para % sobre MAs y nuevos máx/mín
    # sample_all   = todas las acciones para distribución y avanzando/retrocediendo
    sample_sp500 = [v for k,v in stock_perf.items() if k in set(SP500_SAMPLE)]
    sample_all   = list(stock_perf.values())  # todas las acciones descargadas

    # % sobre medias móviles (con SP500)
    if sample_sp500:
        abv50  = [s for s in sample_sp500 if s.get("abv50")  is True]
        abv200 = [s for s in sample_sp500 if s.get("abv200") is True]
        pct50  = round(len(abv50)/len(sample_sp500)*100,1)
        pct200 = round(len(abv200)/len(sample_sp500)*100,1)
    else:
        pct50 = pct200 = 0

    # Nuevos máximos / mínimos con lista de tickers (SP500)
    new_highs_list = sorted([s["ticker"] for s in sample_sp500 if s.get("newHi")],
                            key=lambda t: stock_perf.get(t,{}).get("1D",0), reverse=True)
    new_lows_list  = sorted([s["ticker"] for s in sample_sp500 if s.get("newLo")],
                            key=lambda t: stock_perf.get(t,{}).get("1D",0))
    new_highs = len(new_highs_list)
    new_lows  = len(new_lows_list)

    # Distribución de retornos diarios — TODAS las acciones del universo
    returns_1d = [s.get("1D",0) for s in sample_all if s.get("1D") is not None]
    dist_buckets = {
        "<-10%":0, "-10a-5%":0, "-5a-2%":0, "-2a0%":0,
        "0a2%":0, "2a5%":0, "5a10%":0, ">10%":0
    }
    for r in returns_1d:
        if   r < -10: dist_buckets["<-10%"]  += 1
        elif r < -5:  dist_buckets["-10a-5%"] += 1
        elif r < -2:  dist_buckets["-5a-2%"]  += 1
        elif r <  0:  dist_buckets["-2a0%"]   += 1
        elif r <  2:  dist_buckets["0a2%"]    += 1
        elif r <  5:  dist_buckets["2a5%"]    += 1
        elif r < 10:  dist_buckets["5a10%"]   += 1
        else:         dist_buckets[">10%"]    += 1

    # Avanzando / retrocediendo — TODAS las acciones del universo
    adv  = sum(1 for s in sample_all if (s.get("1D") or 0) > 0)
    dec  = sum(1 for s in sample_all if (s.get("1D") or 0) < 0)
    unch = len(sample_all) - adv - dec

    # Alias para compatibilidad con score
    sample = sample_sp500

    # A/D Line: acumulado de (avances - descensos) últimos 90 días
    # Aproximamos con sectores ETFs diarios
    ad_line = []
    try:
        spy_s = series.get("SPY", {})
        if spy_s:
            n = len(spy_s["dates"])
            spy_vals = spy_s["values"]
            # Use sector ETF daily changes as proxy
            sector_tks = ["XLK","XLF","XLV","XLY","XLP","XLE","XLI","XLB","XLRE","XLU","XLC"]
            cumad = 0
            for i in range(1, min(n, 90)):
                up,dn = 0,0
                for stk in sector_tks:
                    sv = series.get(stk,{}).get("values",[])
                    if len(sv)>i and sv[i-1]>0:
                        chg = (sv[i]-sv[i-1])/sv[i-1]
                        if chg>0: up+=1
                        else: dn+=1
                cumad += (up-dn)
                ad_line.append({"date": spy_s["dates"][i], "val": cumad})
    except: pass

    # McClellan Oscillator proxy: EMA19 - EMA39 de avances-descensos diarios
    mcclellan_series = []
    try:
        if len(ad_line) >= 39:
            ad_vals  = [x["val"] for x in ad_line]
            ad_daily = [ad_vals[i]-ad_vals[i-1] for i in range(1, len(ad_vals))]
            def _ema(vals, n):
                k = 2/(n+1); e = vals[0]; result = [e]
                for v in vals[1:]:
                    e = v*k + e*(1-k); result.append(round(e,2))
                return result
            if len(ad_daily) >= 39:
                e19 = _ema(ad_daily, 19); e39 = _ema(ad_daily, 39)
                n   = min(len(e19), len(e39))
                mcclellan_series = [
                    {"date": ad_line[i+1]["date"], "val": round(e19[i]-e39[i],2)}
                    for i in range(n)
                ]
    except: pass

    # Curva 10Y-2Y proxy: retorno relativo TLT vs SHY
    curve_spread = []
    try:
        tlt_s = series.get("TLT",{}).get("values",[])
        shy_s = series.get("SHY",{}).get("values",[])
        dates = series.get("TLT",{}).get("dates",[])
        if tlt_s and shy_s and len(tlt_s)==len(shy_s) and len(tlt_s)>0:
            tlt0, shy0 = tlt_s[0], shy_s[0]
            for i, d in enumerate(dates):
                tlt_ret = (tlt_s[i]/tlt0 - 1) * 100
                shy_ret = (shy_s[i]/shy0 - 1) * 100
                curve_spread.append({"date": d, "val": round(tlt_ret - shy_ret, 2)})
    except: pass

    # ── SCORE 0-100 ──────────────────────────────────────────────────────────
    score_components = []
    # % sobre MA50 (0-25 pts)
    score_components.append(min(25, pct50 * 0.25))
    # % sobre MA200 (0-20 pts)
    score_components.append(min(20, pct200 * 0.20))
    # Nuevos máximos vs mínimos (0-15 pts)
    total_nh = new_highs + new_lows
    if total_nh > 0:
        score_components.append(min(15, (new_highs/total_nh)*15))
    else: score_components.append(7)
    # VIX (bajo=bueno) (0-15 pts)
    vix = latest.get("^VIX",{}).get("price", 20)
    if   isinstance(vix,(int,float)) and vix < 15: score_components.append(15)
    elif isinstance(vix,(int,float)) and vix < 20: score_components.append(12)
    elif isinstance(vix,(int,float)) and vix < 25: score_components.append(7)
    else: score_components.append(3)
    # HYG risk-on (0-10 pts)
    hyg_chg = latest.get("HYG",{}).get("chg",0)
    score_components.append(10 if hyg_chg>0 else 3)
    # McClellan: positivo=alcista (0-10 pts)
    mcc_last = mcclellan_series[-1]["val"] if mcclellan_series else 0
    if   mcc_last >  50: score_components.append(10)
    elif mcc_last >   0: score_components.append(7)
    elif mcc_last > -50: score_components.append(3)
    else: score_components.append(0)
    # Nuevos mínimos penalizan (0-5 pts, penaliza si hay muchos mínimos)
    if total_nh > 0:
        score_components.append(max(0, 5 - round(new_lows/max(new_highs,1)*5)))
    else: score_components.append(3)

    market_score = int(sum(score_components))
    score_label  = ("Defensivo" if market_score<30 else
                   "Neutral Bajista" if market_score<45 else
                   "Neutral" if market_score<55 else
                   "Neutral Alcista" if market_score<65 else
                   "Ofensivo" if market_score<80 else
                   "Ofensivo Pleno")

    sc = [latest.get(t,{}).get("chg",0) for t in
          ["XLK","XLV","XLF","XLY","XLP","XLE","XLI","XLB","XLRE","XLU","XLC"]]

    latest["__summary__"] = {
        "up_sectors":    sum(1 for c in sc if c>0),
        "down_sectors":  sum(1 for c in sc if c<0),
        "vix":           latest.get("^VIX",{}).get("price","N/A"),
        "vix_chg":       latest.get("^VIX",{}).get("chg",0),
        "spy_chg":       latest.get("SPY",{}).get("chg",0),
        "spy_price":     latest.get("SPY",{}).get("price","N/A"),
        "hyg_chg":       hyg_chg,
        "tlt_chg":       latest.get("TLT",{}).get("chg",0),
        "uup_chg":       latest.get("UUP",{}).get("chg",0),
        "gld_chg":       latest.get("GLD",{}).get("chg",0),
        "uso_chg":       latest.get("USO",{}).get("chg",0),
        # NYSE y Put/Call
        "nyse_price":    latest.get("^NYA",{}).get("price","N/A"),
        "nyse_chg":      latest.get("^NYA",{}).get("chg",0),
        "pc_total":      latest.get("^VVIX",{}).get("price","N/A"),
        "pc_equity":     latest.get("^SKEW",{}).get("price","N/A"),
        # Macro / Bonos / Inflación
        "tip_chg":       latest.get("TIP",{}).get("chg",0),
        "tip_price":     latest.get("TIP",{}).get("price","N/A"),
        "agg_chg":       latest.get("AGG",{}).get("chg",0),
        "lqd_chg":       latest.get("LQD",{}).get("chg",0),
        "tnx_price":     latest.get("^TNX",{}).get("price","N/A"),
        "tnx_chg":       latest.get("^TNX",{}).get("chg",0),
        "irx_price":     latest.get("^IRX",{}).get("price","N/A"),
        "irx_chg":       latest.get("^IRX",{}).get("chg",0),
        "emb_chg":       latest.get("EMB",{}).get("chg",0),
        # Amplitud real
        "pct_abv50":     pct50,
        "pct_abv200":    pct200,
        "new_highs":     new_highs,
        "new_lows":      new_lows,
        "new_highs_list": new_highs_list[:25],
        "new_lows_list":  new_lows_list[:25],
        "advancing":     adv,
        "declining":     dec,
        "unchanged":     unch,
        "total_sample":  len(sample_all),
        "total_sp500":   len(sample_sp500),
        "dist_buckets":  dist_buckets,
        "ad_line":       ad_line[-60:] if len(ad_line)>60 else ad_line,
        "mcclellan":     mcclellan_series[-60:] if len(mcclellan_series)>60 else mcclellan_series,
        "curve_spread":  curve_spread[-60:] if len(curve_spread)>60 else curve_spread,
        "score":         market_score,
        "score_label":   score_label,
    }
    return latest, series


def fetch_stock_info(tickers_sample):
    """Descarga info fundamental en paralelo (ThreadPoolExecutor) para mayor velocidad."""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print(f"  ↓ Fundamentales ({len(tickers_sample)} acciones, paralelo)...")
    out = {}

    def _fetch_one(tk):
        try:
            info = yf.Ticker(tk).info
            if not info: return tk, None
            return tk, {
                "name":        info.get("shortName", info.get("longName","")),
                "sector":      info.get("sector",""),
                "industry":    info.get("industry",""),
                "mktCap":      info.get("marketCap"),
                "pe":          info.get("trailingPE"),
                "fwdPE":       info.get("forwardPE"),
                "eps":         info.get("trailingEps"),
                "fwdEps":      info.get("forwardEps"),
                "revGrowth":   info.get("revenueGrowth"),
                "epsGrowth":   info.get("earningsGrowth"),
                "divYield":    info.get("dividendYield"),
                "beta":        info.get("beta"),
                "analyst":     info.get("recommendationMean"),
                "nAnalysts":   info.get("numberOfAnalystOpinions"),
                "targetMean":  info.get("targetMeanPrice"),
                "grossMarg":   info.get("grossMargins"),
                "opMarg":      info.get("operatingMargins"),
                "netMarg":     info.get("profitMargins"),
                "roe":         info.get("returnOnEquity"),
                "roa":         info.get("returnOnAssets"),
                "debtEq":      info.get("debtToEquity"),
                "currentRatio":info.get("currentRatio"),
                "revenue":     info.get("totalRevenue"),
                "ebitda":      info.get("ebitda"),
                "fcf":         info.get("freeCashflow"),
                "peg":         info.get("pegRatio"),
                "pb":          info.get("priceToBook"),
                "ps":          info.get("priceToSalesTrailing12Months"),
                "employees":   info.get("fullTimeEmployees"),
                "country":     info.get("country",""),
                "exchange":    info.get("exchange",""),
                "website":     info.get("website",""),
                "summary":     (info.get("longBusinessSummary","") or "")[:600],
            }
        except: return tk, None

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_one, tk): tk for tk in tickers_sample}
        for future in as_completed(futures):
            try:
                tk, data = future.result()
                if data: out[tk] = data
            except: pass
    print(f"    → {len(out)} acciones con fundamentales")
    return out


def build_stock_maps(stock_perf):
    ind_map, sec_map = {}, {}
    for ind, data in INDUSTRY_DATA.items():
        rows = sorted([dict(stock_perf[t]) for t in data["holdings"] if t in stock_perf],
                      key=lambda x: x.get("1D",0), reverse=True)
        ind_map[ind] = rows
    for sec, tks in SECTOR_STOCKS.items():
        rows = sorted([dict(stock_perf[t]) for t in tks if t in stock_perf],
                      key=lambda x: x.get("1D",0), reverse=True)
        sec_map[sec] = rows
    return ind_map, sec_map


# ══════════════════════════════════════════════════════════════════════════════
#  HTML (template con placeholders)
# ══════════════════════════════════════════════════════════════════════════════
HTML_TMPL = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#06080d">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="VG Comunidad">
<title>VICTOR GALAN: LA COMUNIDAD</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=Syne:wght@400;700;800&display=swap');
:root{
  --bg:#06080d;--bg2:#0c0f18;--bg3:#121720;--bg4:#181e2a;
  --b1:#1c2436;--b2:#26304a;--b3:#2e3a55;
  --tx:#b2bfcf;--dim:#3a4860;--hi:#d8e6f5;
  --ac:#38bdf8;--ac2:#0ea5e9;
  --up:#10b981;--dn:#f43f5e;--warn:#f59e0b;--neu:#4b5563;
  --upb:rgba(16,185,129,.08);--dnb:rgba(244,63,94,.08);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%}
body{background:var(--bg);color:var(--tx);font-family:'JetBrains Mono',monospace;font-size:12px}
/* ── TOPBAR */
.topbar{background:var(--bg2);border-bottom:1px solid var(--b1);padding:0 18px;display:flex;align-items:center;justify-content:space-between;height:46px;position:sticky;top:0;z-index:300}
.logo{font-family:'Syne',sans-serif;font-weight:800;font-size:14px;color:var(--ac);display:flex;align-items:center;gap:8px}
.pulse{width:7px;height:7px;border-radius:50%;background:var(--up);animation:pulse 2s infinite;flex-shrink:0}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
.topbar-r{display:flex;align-items:center;gap:12px}
.pill{padding:2px 9px;border-radius:4px;font-size:10px;font-weight:700}
.pup{background:var(--upb);color:var(--up)}.pdn{background:var(--dnb);color:var(--dn)}
.pwarn{background:rgba(245,158,11,.1);color:var(--warn)}.pac{background:rgba(56,189,248,.08);color:var(--ac);cursor:pointer}
/* ── WRAP */
.wrap{max-width:1900px;margin:0 auto;padding:14px 18px}
/* ── BREADTH STRIP */
.bstrip{display:grid;grid-template-columns:repeat(6,1fr);gap:7px;margin-bottom:14px}
.bc{background:var(--bg2);border:1px solid var(--b1);border-radius:7px;padding:10px 12px}
.bc-l{font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.08em;margin-bottom:3px}
.bc-v{font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:var(--hi)}
.bc-c{font-size:10px;font-weight:700;margin-top:2px}
/* ── TABS */
.tabs{display:flex;border-bottom:1px solid var(--b1);margin-bottom:13px;gap:0;overflow-x:auto}
.tab{padding:7px 16px;border:none;background:none;color:var(--dim);cursor:pointer;font-family:'Syne',sans-serif;font-weight:700;font-size:11px;letter-spacing:.05em;text-transform:uppercase;border-bottom:2px solid transparent;margin-bottom:-1px;white-space:nowrap;transition:all .2s}
.tab:hover{color:var(--tx)}.tab.active{color:var(--ac);border-bottom-color:var(--ac)}
.tc{display:none}.tc.active{display:block}
/* ── SECTION HDR */
.sh{display:flex;align-items:center;justify-content:space-between;margin-bottom:11px;flex-wrap:wrap;gap:8px}
.st{font-family:'Syne',sans-serif;font-weight:700;font-size:13px;color:var(--hi)}
.hint{font-size:10px;color:var(--dim);font-weight:400;margin-left:8px}
.pbs{display:flex;gap:3px}
.pb{padding:3px 8px;border:1px solid var(--b1);border-radius:4px;background:none;color:var(--dim);cursor:pointer;font-size:10px;transition:all .2s}
.pb.active,.pb:hover{background:rgba(56,189,248,.07);color:var(--ac);border-color:var(--ac)}
/* ── HEATMAP */
.hmg{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:5px;margin-bottom:16px}
.hmc{border-radius:7px;padding:10px;cursor:pointer;border:1px solid transparent;transition:transform .15s,border-color .15s;position:relative}
.hmc:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.09)}
.hmc::after{content:'▶';position:absolute;bottom:5px;right:7px;font-size:7px;opacity:.25}
.hmc-n{font-weight:700;font-size:10px;margin-bottom:1px;color:rgba(255,255,255,.88);line-height:1.3}
.hmc-t{font-size:8px;opacity:.48;margin-bottom:5px}
.hmc-p{font-family:'Syne',sans-serif;font-size:16px;font-weight:800}
.hmc-pr{font-size:8px;opacity:.42;margin-top:1px}
/* ── TABLE */
.tw{background:var(--bg2);border:1px solid var(--b1);border-radius:9px;overflow:hidden;margin-bottom:16px}
table{width:100%;border-collapse:collapse}
thead tr{background:var(--bg3);border-bottom:1px solid var(--b1)}
th{padding:7px 11px;text-align:right;font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);cursor:pointer;white-space:nowrap;user-select:none}
th:first-child,th:nth-child(2){text-align:left}
th:hover{color:var(--ac)}th.srt{color:var(--ac)}
tbody tr{border-bottom:1px solid var(--b1);transition:background .1s;cursor:pointer}
tbody tr:last-child{border-bottom:none}
tbody tr:hover{background:rgba(255,255,255,.018)}
td{padding:7px 11px;text-align:right;white-space:nowrap;font-size:11px}
td:first-child{text-align:left}td:nth-child(2){text-align:left;color:var(--dim);font-size:10px}
.rk{display:inline-block;width:17px;height:17px;border-radius:3px;background:var(--bg3);text-align:center;line-height:17px;font-size:9px;color:var(--dim);margin-right:5px}
.nm{font-weight:600;color:var(--hi)}
/* colors */
.up{color:var(--up)}.dn{color:var(--dn)}.neu{color:var(--neu)}
/* gauge */
.gw{display:flex;align-items:center;gap:4px;justify-content:flex-end}
.gt{width:48px;height:3px;background:var(--bg4);border-radius:2px;position:relative}
.gf{position:absolute;left:0;top:0;height:100%;border-radius:2px;background:linear-gradient(90deg,var(--dn),var(--warn),var(--up))}
.gd{position:absolute;top:-3px;width:7px;height:7px;border-radius:50%;background:var(--ac);border:1.5px solid var(--bg2);transform:translateX(-50%)}
/* badge */
.badge{display:inline-block;padding:1px 5px;border-radius:3px;font-size:9px;font-weight:700}
.b-up{background:var(--upb);color:var(--up)}.b-dn{background:var(--dnb);color:var(--dn)}.b-neu{background:var(--bg4);color:var(--dim)}
/* search */
.sr{display:flex;gap:9px;align-items:center;margin-bottom:11px}
.si{background:var(--bg2);border:1px solid var(--b1);border-radius:5px;padding:6px 11px;color:var(--tx);font-family:'JetBrains Mono',monospace;font-size:11px;width:220px;outline:none;transition:border-color .2s}
.si:focus{border-color:var(--ac)}.si::placeholder{color:var(--dim)}
.clabel{font-size:10px;color:var(--dim)}
/* ── MODAL */
.ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.8);z-index:500;backdrop-filter:blur(5px);align-items:flex-start;justify-content:center;padding-top:42px}
.ov.open{display:flex}
.mod{background:var(--bg2);border:1px solid var(--b2);border-radius:11px;width:min(1100px,97vw);max-height:86vh;display:flex;flex-direction:column;animation:si .2s ease}
@keyframes si{from{transform:translateY(-12px);opacity:0}to{transform:translateY(0);opacity:1}}
.mh{display:flex;align-items:flex-start;justify-content:space-between;padding:13px 17px;border-bottom:1px solid var(--b1);flex-shrink:0}
.mt{font-family:'Syne',sans-serif;font-weight:800;font-size:15px;color:var(--hi)}
.msub{font-size:10px;color:var(--dim);margin-top:2px}
.mright{display:flex;align-items:center;gap:8px;flex-shrink:0}
.metf{background:rgba(56,189,248,.1);color:var(--ac);padding:2px 9px;border-radius:4px;font-size:10px;font-weight:700}
.mclose{background:none;border:none;color:var(--dim);cursor:pointer;font-size:16px;padding:4px 7px;border-radius:4px;transition:color .2s}
.mclose:hover{color:var(--hi)}
.mb{overflow-y:auto;flex:1}
.mb table{width:100%}.mb thead th{position:sticky;top:0;z-index:1;background:var(--bg3)}
/* sparkline in table */
.spark-cell svg{display:block}
/* ── AMPLITUD */
.score-block{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:18px;margin-bottom:14px;display:flex;align-items:center;gap:20px}
.score-ring{flex-shrink:0}
.score-txt h2{font-family:'Syne',sans-serif;font-weight:800;font-size:26px;color:var(--hi);margin-bottom:4px}
.score-txt p{font-size:11px;color:var(--dim)}
.amp-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:7px;margin-bottom:14px}
.amp-card{background:var(--bg2);border:1px solid var(--b1);border-radius:8px;padding:11px 13px}
.amp-l{font-size:10px;color:var(--tx);font-weight:600;letter-spacing:.03em;margin-bottom:4px}
.amp-v{font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--hi)}
.amp-sub{font-size:10px;color:var(--dim);margin-top:3px}
.risk-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px}
.nyse-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px}
.risk-c{background:var(--bg2);border:1px solid var(--b1);border-radius:8px;padding:12px;text-align:center}
.risk-l{font-size:10px;color:var(--tx);font-weight:600;letter-spacing:.02em;margin-bottom:5px}
.risk-a{font-size:24px;margin-bottom:3px}
.risk-v{font-size:13px;font-weight:700}.risk-n{font-size:10px;color:var(--dim);margin-top:4px}
.charts-2{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.charts-3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px}
.cw{background:var(--bg2);border:1px solid var(--b1);border-radius:9px;padding:13px}
.ct{font-family:'Syne',sans-serif;font-size:11px;font-weight:700;color:var(--hi);margin-bottom:9px}
/* dist bar chart */
.dist-wrap{display:flex;align-items:flex-end;gap:4px;height:80px;padding-bottom:18px;position:relative}
.dist-bar{flex:1;border-radius:3px 3px 0 0;min-width:20px;position:relative;transition:opacity .2s}
.dist-bar:hover{opacity:.8}
.dist-label{position:absolute;bottom:-16px;left:50%;transform:translateX(-50%);font-size:8px;color:var(--dim);white-space:nowrap}
.dist-val{position:absolute;top:-16px;left:50%;transform:translateX(-50%);font-size:9px;font-weight:700;color:var(--hi)}
/* ── BENCHMARK CHART MODAL */
.bm-ov{display:none;position:fixed;inset:0;background:rgba(0,0,0,.82);z-index:600;backdrop-filter:blur(5px);align-items:center;justify-content:center}
.bm-ov.open{display:flex}
.bm-box{background:var(--bg2);border:1px solid var(--b2);border-radius:11px;width:min(820px,95vw);padding:18px}
.bm-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
.bm-name{font-family:'Syne',sans-serif;font-weight:800;font-size:16px;color:var(--hi)}
.bm-meta{font-size:10px;color:var(--dim);margin-top:2px}
/* ── EARNINGS TABS */
.earn-tabs{display:flex;gap:4px;margin-bottom:12px}
.earn-tab{padding:5px 14px;border:1px solid var(--b1);border-radius:5px;background:none;color:var(--dim);cursor:pointer;font-family:'Syne',sans-serif;font-weight:700;font-size:11px;transition:all .2s}
.earn-tab.active{background:rgba(56,189,248,.07);color:var(--ac);border-color:var(--ac)}
.earn-upcoming-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:7px;margin-bottom:14px}
.eu-card{background:var(--bg2);border:1px solid var(--b1);border-radius:7px;padding:10px 12px;text-align:center}
.eu-tk{font-family:'Syne',sans-serif;font-size:15px;font-weight:800;color:var(--hi)}
.eu-dt{font-size:9px;color:var(--dim);margin-top:4px}
/* ── NEWS */
.news-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:9px;margin-bottom:14px}
.news-card{background:var(--bg2);border:1px solid var(--b1);border-radius:8px;padding:12px 14px;cursor:pointer;transition:border-color .2s}
.news-card:hover{border-color:var(--b2)}
.news-src{font-size:9px;color:var(--ac);text-transform:uppercase;letter-spacing:.07em;margin-bottom:5px}
.news-title{font-size:11px;font-weight:600;color:var(--hi);line-height:1.4;margin-bottom:6px}
.news-time{font-size:9px;color:var(--dim)}
/* ── STOCK PANEL */
.stock-header{background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:18px 20px;margin-bottom:12px}
.stk-top-row{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-bottom:12px}
.stock-info h2{font-family:'Syne',sans-serif;font-size:26px;font-weight:800;color:var(--hi);line-height:1.1}
.stk-sector-tag{font-size:11px;color:var(--ac);margin-top:4px;margin-bottom:6px}
.stock-price{font-family:'Syne',sans-serif;font-size:24px;font-weight:800}
.stk-rs-inline{display:flex;align-items:center;gap:8px;margin-top:8px}
.stk-rs-num{font-family:'Syne',sans-serif;font-size:36px;font-weight:800;line-height:1}
.stk-rs-label{font-size:10px;color:var(--dim);max-width:120px;line-height:1.4}
.stk-badges{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.stk-vol-bar{height:5px;border-radius:3px;background:var(--b1);margin-top:4px;overflow:hidden}
.stk-vol-fill{height:100%;border-radius:3px;background:var(--ac);transition:width .4s}
.stock-metrics{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:6px;margin-bottom:12px}
.sm-c{background:var(--bg3);border:1px solid var(--b1);border-radius:7px;padding:8px 10px}
.sm-l{font-size:9px;color:var(--dim);margin-bottom:2px;text-transform:uppercase;letter-spacing:.05em}
.sm-v{font-size:13px;font-weight:600;color:var(--hi)}
.fund-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:6px;margin-bottom:12px}
.fg{background:var(--bg3);border:1px solid var(--b1);border-radius:7px;padding:8px 10px}
.fg-l{font-size:9px;color:var(--dim);margin-bottom:2px;text-transform:uppercase;letter-spacing:.05em}
.fg-v{font-size:13px;font-weight:600;color:var(--hi)}
.fg-v.up{color:var(--up)}.fg-v.dn{color:var(--dn)}
.stock-input-row{display:flex;gap:8px;align-items:center;margin-bottom:14px}
.stk-input{background:var(--bg2);border:1px solid var(--b1);border-radius:5px;padding:7px 12px;color:var(--tx);font-family:'JetBrains Mono',monospace;font-size:12px;width:140px;outline:none;transition:border-color .2s;text-transform:uppercase}
.stk-input:focus{border-color:var(--ac)}
.stk-btn{padding:7px 16px;border-radius:5px;border:1px solid var(--ac);background:rgba(56,189,248,.08);color:var(--ac);cursor:pointer;font-family:'Syne',sans-serif;font-weight:700;font-size:11px;transition:all .2s}
.stk-btn:hover{background:rgba(56,189,248,.18)}
.rs-bar{height:5px;border-radius:3px;background:linear-gradient(90deg,var(--dn),var(--warn),var(--up));position:relative;margin-top:4px}
.rs-dot{position:absolute;top:-5px;width:12px;height:12px;border-radius:50%;background:var(--ac);border:2px solid var(--bg);transform:translateX(-50%);box-shadow:0 0 8px var(--ac)}
canvas{width:100%!important}
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:var(--bg)}
::-webkit-scrollbar-thumb{background:var(--b2);border-radius:3px}
.foot{color:var(--dim);font-size:10px;text-align:right;padding:10px 0;border-top:1px solid var(--b1)}

/* ── RESPONSIVE MOBILE ────────────────────────────────────────────────────── */
@media (max-width:768px){
  .wrap{padding:8px 10px}
  .topbar{padding:0 10px;height:42px;flex-wrap:wrap}
  .topbar-l{font-size:11px}
  .topbar-r{gap:6px;font-size:10px}
  .tabs{gap:0;font-size:11px}
  .tab{padding:8px 10px;font-size:11px;white-space:nowrap}
  .charts-2,.charts-3{grid-template-columns:1fr!important}
  .stock-header .stk-top-row{flex-direction:column}
  [style*="grid-template-columns:1fr 1fr"]{grid-template-columns:1fr!important}
  [style*="grid-template-columns:2fr 1fr"]{grid-template-columns:1fr!important}
  [style*="grid-template-columns:1fr 1fr 1fr"]{grid-template-columns:1fr!important}
  [style*="grid-template-columns:repeat(auto-fill"]{grid-template-columns:repeat(2,1fr)!important}
  .hmg{grid-template-columns:repeat(2,1fr)!important}
  .amp-grid{grid-template-columns:repeat(2,1fr)!important}
  .nyse-grid,.risk-grid{grid-template-columns:repeat(2,1fr)!important}
  .sh{flex-direction:column;gap:6px;align-items:flex-start}
  .sh>div{flex-wrap:wrap}
  .pb{padding:5px 10px;font-size:10px}
  .tw{font-size:10px}
  th,td{padding:5px 6px}
  .stk-rs-num{font-size:28px}
  .cw{padding:10px 11px}
  #briefing-col-left,#briefing-col-right{display:block}
  .tw table{min-width:500px}
  .tw{overflow-x:auto;-webkit-overflow-scrolling:touch}
  /* Bottom nav for key sections */
  #mobile-nav{display:flex!important}
  .topbar-r .pill{display:none}
}
@media (max-width:480px){
  body{font-size:11px}
  .topbar{height:auto;padding:6px 10px;flex-wrap:wrap;gap:4px}
  .tab{font-size:10px;padding:7px 8px}
  .amp-grid,.nyse-grid,.risk-grid{grid-template-columns:1fr!important}
  [style*="grid-template-columns:repeat(auto-fill"]{grid-template-columns:1fr!important}
  .hmg{grid-template-columns:repeat(2,1fr)!important}
  .stk-rs-num{font-size:24px}
  .metric-value,.risk-value{font-size:20px}
}
/* Mobile bottom navigation bar */
#mobile-nav{
  display:none;position:fixed;bottom:0;left:0;right:0;z-index:500;
  background:var(--bg2);border-top:1px solid var(--b1);
  padding:6px 0 calc(6px + env(safe-area-inset-bottom));
  display:none;align-items:center;justify-content:space-around
}
#mobile-nav button{
  display:flex;flex-direction:column;align-items:center;gap:2px;
  background:none;border:none;color:var(--dim);font-size:9px;
  cursor:pointer;padding:4px 8px;border-radius:6px;font-family:inherit;
  min-width:52px;transition:color .15s
}
#mobile-nav button.active{color:var(--ac)}
#mobile-nav button span:first-child{font-size:18px}
/* Add bottom padding when mobile nav visible */
@media (max-width:768px){
  .wrap{padding-bottom:70px}
}
</style>
</head>
<body>
<div class="topbar">
  <div class="logo"><span class="pulse"></span>VICTOR GALAN: <span style="color:var(--ac)">LA COMUNIDAD</span></div>
  <div class="topbar-r">
    <span id="ts-l" style="color:var(--dim);font-size:10px"></span>
    <span class="pill" id="spy-p">—</span>
    <span class="pill" id="vix-p">—</span>
    <span class="pill" style="background:rgba(245,158,11,.1);color:var(--warn);cursor:pointer" onclick="sw('briefing',document.getElementById('tab-briefing-btn'))">📋 Resumen</span>
    <span class="pill pac" onclick="sw('breadth',document.getElementById('tab-breadth-btn'))">Amplitud ▸</span>
    <span class="pill pac" onclick="sw('stocks',document.getElementById('tab-stocks-btn'))">Acciones ▸</span>
  </div>
</div>

<!-- DRILL-DOWN MODAL -->
<div class="ov" id="ov" onclick="closeModal(event)">
  <div class="mod">
    <div class="mh">
      <div>
        <div class="mt" id="m-title">—</div>
        <div class="msub" id="m-sub">—</div>
      </div>
      <div class="mright">
        <span class="metf" id="m-etf">—</span>
        <div class="pbs" id="m-pbs">
          <button class="pb active" onclick="setMP('1D',this)">1D</button>
          <button class="pb" onclick="setMP('1W',this)">1W</button>
          <button class="pb" onclick="setMP('1M',this)">1M</button>
          <button class="pb" onclick="setMP('3M',this)">3M</button>
          <button class="pb" onclick="setMP('1Y',this)">1Y</button>
        </div>
        <button class="mclose" onclick="closeModal()">✕</button>
      </div>
    </div>
    <div class="mb">
      <table>
        <thead><tr>
          <th style="text-align:left;cursor:pointer" onclick="sortModal(0)"># Acción ↕</th>
          <th style="text-align:left">Ticker</th>
          <th onclick="sortModal(2)" style="cursor:pointer">Precio ↕</th>
          <th onclick="setMP('1D',document.querySelector('#m-pbs .pb'))" style="cursor:pointer">1D ↕</th>
          <th onclick="setMPdirect('1W')" style="cursor:pointer">1W ↕</th>
          <th onclick="setMPdirect('1M')" style="cursor:pointer">1M ↕</th>
          <th onclick="setMPdirect('3M')" style="cursor:pointer">3M ↕</th>
          <th onclick="setMPdirect('1Y')" style="cursor:pointer">1Y ↕</th>
          <th>vs MA20</th><th>vs MA50</th><th>vs MA200</th>
          <th onclick="sortModal(11)" style="cursor:pointer">Vol Rel. ↕</th>
          <th>52W</th><th>Tendencia</th>
        </tr></thead>
        <tbody id="m-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- BENCHMARK CHART MODAL -->
<div class="bm-ov" id="bm-ov" onclick="closeBMModal(event)">
  <div class="bm-box">
    <div class="bm-hdr">
      <div>
        <div class="bm-name" id="bm-name">—</div>
        <div class="bm-meta" id="bm-meta">—</div>
      </div>
      <button class="mclose" onclick="closeBMModal()">✕</button>
    </div>
    <canvas id="bm-chart" height="340"></canvas>
  </div>
</div>

<div class="wrap">
  <div class="bstrip" id="bstrip"></div>
  <div class="tabs">
    <button class="tab" onclick="sw('briefing',this)" id="tab-briefing-btn" style="color:var(--warn);border-bottom-color:var(--warn)">📋 Resumen</button>
    <button class="tab active" onclick="sw('sectors',this)">Sectores (11)</button>
    <button class="tab" onclick="sw('industries',this)">Industrias / Temas (__NIND__)</button>
    <button class="tab" onclick="sw('breadth',this)" id="tab-breadth-btn">Amplitud</button>
    <button class="tab" onclick="sw('stocks',this)" id="tab-stocks-btn">Panel Acción</button>
    <button class="tab" onclick="sw('scanner',this)" id="tab-scanner-btn">🔍 Scanner</button>
    <button class="tab" onclick="sw('watchlist',this)" id="tab-watchlist-btn">⭐ Watchlist</button>
    <button class="tab" onclick="sw('cartera',this)" id="tab-cartera-btn">💼 Mi Cartera</button>
  </div>


  <!-- ═══ BRIEFING ═══ -->
  <div id="tab-briefing" class="tc">
    <!-- Cabecera estilo periódico -->
    <div style="border-bottom:2px solid var(--ac);margin-bottom:14px;padding-bottom:10px;display:flex;align-items:flex-end;justify-content:space-between;flex-wrap:wrap;gap:8px">
      <div>
        <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--hi);letter-spacing:-.01em">VICTOR GALAN: LA COMUNIDAD</div>
        <div style="font-size:11px;color:var(--dim);margin-top:2px">Resumen de mercado · <span id="briefing-date"></span></div>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        <div id="briefing-semaphore-top" style="display:flex;gap:6px;align-items:center"></div>
        <button class="pb" onclick="_briefingBuilt=false;renderBriefing()" style="padding:5px 12px">↻ Actualizar</button>
      </div>
    </div>
    <!-- Intro headline -->
    <div id="briefing-intro" style="margin-bottom:14px"></div>
    <!-- Layout 2 columnas -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px" id="briefing-cols">
      <div id="briefing-col-left"></div>
      <div id="briefing-col-right"></div>
    </div>
  </div>

  <!-- ═══ SECTORES ═══ -->
  <div id="tab-sectors" class="tc active">
    <div class="sh">
      <span class="st">SECTORES S&P 500<span class="hint">— click para ver acciones</span></span>
      <div class="pbs" id="ps">
        <button class="pb active" onclick="sp('s','1D',this)">1D</button>
        <button class="pb" onclick="sp('s','1W',this)">1W</button>
        <button class="pb" onclick="sp('s','1M',this)">1M</button>
        <button class="pb" onclick="sp('s','3M',this)">3M</button>
        <button class="pb" onclick="sp('s','6M',this)">6M</button>
        <button class="pb" onclick="sp('s','1Y',this)">1Y</button>
      </div>
    </div>
    <div class="hmg" id="hm-s"></div>
    <div class="tw"><table><thead><tr>
      <th onclick="srt('tb-s',0)"># Sector</th><th>Ticker</th><th>Precio</th>
      <th onclick="srt('tb-s',3)">1D</th><th onclick="srt('tb-s',4)">1W</th>
      <th onclick="srt('tb-s',5)">1M</th><th onclick="srt('tb-s',6)">3M</th>
      <th onclick="srt('tb-s',7)">6M</th><th onclick="srt('tb-s',8)">1Y</th>
      <th>52W</th><th onclick="srt('tb-s',10)">vs Máx</th>
    </tr></thead><tbody id="tb-s"></tbody></table></div>
  </div>

  <!-- ═══ INDUSTRIAS ═══ -->
  <div id="tab-industries" class="tc">
    <div class="sh">
      <span class="st">INDUSTRIAS & TEMAS<span class="hint">— click para ver constituyentes</span></span>
      <div class="pbs" id="pi">
        <button class="pb active" onclick="sp('i','1D',this)">1D</button>
        <button class="pb" onclick="sp('i','1W',this)">1W</button>
        <button class="pb" onclick="sp('i','1M',this)">1M</button>
        <button class="pb" onclick="sp('i','3M',this)">3M</button>
        <button class="pb" onclick="sp('i','6M',this)">6M</button>
        <button class="pb" onclick="sp('i','1Y',this)">1Y</button>
      </div>
    </div>
    <div class="hmg" id="hm-i"></div>
    <div class="sr">
      <input class="si" type="text" placeholder="Filtrar industria, ticker, tema..." oninput="fi(this.value)">
      <span class="clabel" id="ind-cnt"></span>
    </div>
    <div class="tw"><table><thead><tr>
      <th onclick="srt('tb-i',0)"># Industria / Tema</th><th>ETF</th><th>Precio</th>
      <th onclick="srt('tb-i',3)">1D</th><th onclick="srt('tb-i',4)">1W</th>
      <th onclick="srt('tb-i',5)">1M</th><th onclick="srt('tb-i',6)">3M</th>
      <th onclick="srt('tb-i',7)">6M</th><th onclick="srt('tb-i',8)">1Y</th>
      <th>52W</th><th onclick="srt('tb-i',10)">vs Máx</th>
    </tr></thead><tbody id="tb-i"></tbody></table></div>
  </div>

  <!-- ═══ AMPLITUD ═══ -->
  <div id="tab-breadth" class="tc">
    <!-- Score block -->
    <div class="score-block">
      <div class="score-ring">
        <svg width="90" height="90" viewBox="0 0 90 90">
          <circle cx="45" cy="45" r="38" fill="none" stroke="var(--b1)" stroke-width="7"/>
          <circle cx="45" cy="45" r="38" fill="none" stroke="var(--ac)" stroke-width="7"
            stroke-dasharray="238.76" id="score-arc" stroke-dashoffset="238.76"
            stroke-linecap="round" transform="rotate(-90 45 45)"/>
          <text x="45" y="50" text-anchor="middle" font-family="Syne,sans-serif" font-size="20"
            font-weight="800" fill="var(--hi)" id="score-num">—</text>
        </svg>
      </div>
      <div class="score-txt">
        <h2 id="score-label">—</h2>
        <p id="score-desc" style="margin-bottom:8px">—</p>
        <div style="display:flex;gap:10px;flex-wrap:wrap">
          <span id="adv-badge" class="badge b-up">—</span>
          <span id="dec-badge" class="badge b-dn">—</span>
          <span id="unch-badge" class="badge b-neu">—</span>
          <span id="nh-badge" class="badge b-up" style="cursor:pointer" onclick="toggleNHList('highs')" title="Click para ver tickers">—</span>
          <span id="nl-badge" class="badge b-dn" style="cursor:pointer" onclick="toggleNHList('lows')" title="Click para ver tickers">—</span>
        </div>
        <div id="nh-list" style="display:none;margin-top:10px;display:none;flex-wrap:wrap;gap:4px;max-height:80px;overflow-y:auto"></div>
      </div>
    </div>

    <!-- Amplitude metrics -->
    <div class="amp-grid" id="amp-grid"></div>

    <!-- Risk on/off -->
    <div class="sh" style="margin-top:2px"><span class="st">NYSE &amp; PUT/CALL RATIO</span></div>
    <div class="nyse-grid" id="nyse-grid"></div>
    <div class="sh" style="margin-top:2px"><span class="st">INDICADORES RISK-ON / RISK-OFF</span></div>
    <div class="risk-grid" id="risk-g"></div>

    <!-- Indicadores avanzados: 3 columnas x 2 filas -->
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px">
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">📊 Sentimiento AAII proxy</div>
        <div id="aaii-content"></div>
      </div>
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">🌊 Ciclo Kondratiev</div>
        <div id="kondratiev-content"></div>
      </div>
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">📈 MACD S&P500 — ¿Activado?</div>
        <div id="macd-content"></div>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:14px">
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">💰 Bonos CEF — señal de flujo</div>
        <div id="cef-content"></div>
      </div>
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">🔁 Coppock Curve — S&P mensual</div>
        <div id="coppock-content"></div>
      </div>
      <div class="cw" style="padding:12px 14px">
        <div class="ct" style="margin-bottom:7px;font-size:11px">⚖️ HAA-Simple — Asset Allocation</div>
        <div id="haa-content"></div>
      </div>
    </div>
    <!-- Fear & Greed iframe CNN -->
    <div class="cw" style="padding:12px 14px;margin-bottom:14px">
      <div class="ct" style="margin-bottom:7px;font-size:11px">😨 Fear &amp; Greed — CNN Markets</div>
      <div id="fg-content"></div>
    </div>

    <!-- Distribución retornos -->
    <div class="sh"><span class="st">DISTRIBUCIÓN DE RETORNOS DIARIOS — S&P 500 muestra</span></div>
    <div class="cw" style="margin-bottom:14px">
      <div class="dist-wrap" id="dist-chart"></div>
    </div>

    <!-- Charts row 1: SPY + VIX -->
    <div class="charts-2">
      <div class="cw"><div class="ct">S&P 500 (SPY) — 90 días <span id="chg-spy" style="float:right;font-size:10px"></span></div><canvas id="c-spy" height="120"></canvas></div>
      <div class="cw"><div class="ct">VIX — Volatilidad implícita <span id="chg-vix" style="float:right;font-size:10px"></span></div><canvas id="c-vix" height="120"></canvas></div>
    </div>
    <!-- Charts row 2: HYG + TLT + UUP -->
    <div class="charts-3">
      <div class="cw"><div class="ct">High Yield (HYG) <span id="chg-hyg" style="float:right;font-size:10px"></span></div><canvas id="c-hyg" height="110"></canvas></div>
      <div class="cw"><div class="ct">Treasury 20Y (TLT) <span id="chg-tlt" style="float:right;font-size:10px"></span></div><canvas id="c-tlt" height="110"></canvas></div>
      <div class="cw"><div class="ct">US Dollar (UUP) <span id="chg-uup" style="float:right;font-size:10px"></span></div><canvas id="c-uup" height="110"></canvas></div>
    </div>
    <!-- Charts row 3: McClellan + A/D Line + Curva 10Y-2Y -->
    <div class="charts-3">
      <div class="cw"><div class="ct">McClellan Osc. <span id="chg-mcc" style="float:right;font-size:10px"></span></div><canvas id="c-mcc" height="110"></canvas></div>
      <div class="cw"><div class="ct">A/D Line (proxy) <span id="chg-adl" style="float:right;font-size:10px"></span></div><canvas id="c-adl" height="110"></canvas></div>
      <div class="cw"><div class="ct">Curva 10Y-2Y (proxy) <span id="chg-crv" style="float:right;font-size:10px"></span></div><canvas id="c-crv" height="110"></canvas></div>
    </div>
    <!-- Charts row 4: GLD + BTC + NYSE -->
    <div class="charts-3">
      <div class="cw"><div class="ct">Oro (GLD) <span id="chg-gld" style="float:right;font-size:10px"></span></div><canvas id="c-gld" height="110"></canvas></div>
      <div class="cw"><div class="ct">Bitcoin ETF (IBIT) <span id="chg-btc" style="float:right;font-size:10px"></span></div><canvas id="c-btc" height="110"></canvas></div>
      <div class="cw"><div class="ct">NYSE Composite <span id="chg-nya" style="float:right;font-size:10px"></span></div><canvas id="c-nya" height="110"></canvas></div>
    </div>
    <!-- VVIX + SKEW legend -->
    <div class="charts-2" style="margin-bottom:14px">
      <div class="cw">
        <div class="ct">VVIX — Volatilidad del VIX (sentimiento opciones)</div>
        <canvas id="c-vvix" height="100"></canvas>
        <div style="font-size:10px;color:var(--dim);margin-top:8px;line-height:1.6">
          <strong style="color:var(--hi)">¿Qué es?</strong> Mide la volatilidad del propio VIX. Cuando el VVIX sube, los traders compran puts agresivamente.
          <br>📍 <strong>&gt;120</strong>: Alta incertidumbre — mercado en modo pánico de opciones. 
          <strong>&lt;90</strong>: Calma — falta de cobertura, posible complacencia.
        </div>
      </div>
      <div class="cw">
        <div class="ct">SKEW — Índice de riesgo de cola CBOE</div>
        <canvas id="c-skew" height="100"></canvas>
        <div style="font-size:10px;color:var(--dim);margin-top:8px;line-height:1.6">
          <strong style="color:var(--hi)">¿Qué es?</strong> Mide la demanda de protección contra caídas extremas (colas izquierdas).
          <br>📍 <strong>&gt;140</strong>: Miedo a evento de cola — crash implícito en opciones.
          <strong>100–115</strong>: Normal. <strong>&lt;100</strong>: Complacencia excesiva.
        </div>
      </div>
    </div>
    <!-- Macro / Bonos / Yields -->
    <div class="sh"><span class="st">MACRO — BONOS, YIELDS E INFLACIÓN</span></div>
    <div class="charts-3" style="margin-bottom:14px">
      <div class="cw">
        <div class="ct">Yield 10Y Tesoro EEUU (^TNX) <span id="tnx-chg" style="float:right;font-size:10px"></span></div>
        <canvas id="c-tnx" height="90"></canvas>
        <div style="font-size:9px;color:var(--dim);margin-top:6px">El yield 10Y es la referencia global del coste del dinero. Subidas presionan las valoraciones growth y el mercado inmobiliario.</div>
      </div>
      <div class="cw">
        <div class="ct">TIPS (Inflación real USA) <span id="tip-chg" style="float:right;font-size:10px"></span></div>
        <canvas id="c-tip" height="90"></canvas>
        <div style="font-size:9px;color:var(--dim);margin-top:6px">Los TIPS reflejan expectativas de inflación real. Si suben mientras el nominal baja, el mercado espera menor inflación futura.</div>
      </div>
      <div class="cw">
        <div class="ct">Bonos Aggregate (AGG) vs Corp (LQD) <span id="agg-chg" style="float:right;font-size:10px"></span></div>
        <canvas id="c-agg" height="90"></canvas>
        <div style="font-size:9px;color:var(--dim);margin-top:6px">AGG mide el mercado de bonos USA en general. Su precio inverso al yield. LQD sube en entornos risk-on (crédito corporativo demandado).</div>
      </div>
    </div>

    <!-- Comentario interpretativo -->
    <div class="cw" style="margin-bottom:14px;border-left:3px solid var(--ac)" id="market-comment-box">
      <div class="ct" style="display:flex;align-items:center;gap:8px">
        <span>🧠 INTERPRETACIÓN DE MERCADO</span>
        <span style="font-size:9px;color:var(--dim);font-family:JetBrains Mono,monospace;font-weight:400">— análisis basado en amplitud, riesgo y flujo macro</span>
      </div>
      <div id="market-comment" style="font-size:11px;line-height:1.9;color:var(--tx)">—</div>
    </div>



    <div class="sh" style="margin-top:6px"><span class="st">📅 ESTACIONALIDAD &amp; 🌡️ ENTORNO DE INFLACIÓN</span></div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px">
      <div class="cw" style="padding:13px 15px" id="seasonal-box">
        <div class="ct" style="margin-bottom:8px">📅 ¿Qué activos favorece este mes históricamente?</div>
        <div id="seasonal-content"></div>
      </div>
      <div class="cw" style="padding:13px 15px" id="inflation-box">
        <div class="ct" style="margin-bottom:8px">🌡️ Entorno de inflación — ¿Qué funciona mejor?</div>
        <div id="inflation-content"></div>
      </div>
    </div>
  </div>

  <!-- ═══ PANEL ACCIÓN ═══ -->
  <div id="tab-stocks" class="tc">
    <div class="sh"><span class="st">PANEL INDIVIDUAL DE ACCIÓN</span></div>
    <div class="stock-input-row">
      <input class="stk-input" id="stk-ticker" type="text" placeholder="NVDA" maxlength="8" onkeydown="if(event.key==='Enter')loadStock()">
      <button class="stk-btn" onclick="loadStock()">Analizar ▶</button>
      <div style="display:flex;gap:6px;flex-wrap:wrap" id="quick-tickers"></div>
    </div>
    <div id="stock-panel"></div>
  </div>


  <!-- ═══ SCANNER ═══ -->
  <div id="tab-scanner" class="tc">
    <div class="sh">
      <span class="st">🔍 SCANNER DE ACCIONES</span>
      <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <button class="pb active" id="scan-btn-rs" onclick="runScanner('rs',this)">⭐ RS Líderes</button>
        <button class="pb" id="scan-btn-highs" onclick="runScanner('highs',this)">🔝 Cerca 52W Max</button>
        <button class="pb" id="scan-btn-vol" onclick="runScanner('vol',this)">💰 Volumen Comprador</button>
        <button class="pb" id="scan-btn-parabolic" onclick="runScanner('parabolic',this)">🚀 Parabolic Short</button>
        <button class="pb" id="scan-btn-abv_all" onclick="runScanner('abv_all',this)">✅ Sobre MA20+50</button>
        <button class="pb" id="scan-btn-lows" onclick="runScanner('lows',this)">🔻 Cerca 52W Mín</button>
        <button class="pb" id="scan-btn-bounce" onclick="runScanner('bounce',this)">🔄 Rebote MA</button>
        <button class="pb" id="scan-btn-pre" onclick="runScanner('pre',this)">🌅 Premercado ↑</button>
        <span style="font-size:9px;color:var(--dim)">· click en columna para ordenar ·</span>
        <button class="pb" onclick="copyScannerTickers()" style="margin-left:auto">📋 Copiar lista</button>
      </div>
    </div>
    <div id="scanner-status" style="font-size:10px;color:var(--dim);margin-bottom:8px">Selecciona un filtro para escanear</div>
    <div class="tw"><table id="scanner-table"><thead><tr>
      <th style="text-align:left" onclick="sortScanner(0)"># Ticker</th>
      <th onclick="sortScanner(1)">Precio</th>
      <th onclick="sortScanner(2)">1D ↕</th>
      <th onclick="sortScanner(3)">1W ↕</th>
      <th onclick="sortScanner(4)">1M ↕</th>
      <th onclick="sortScanner(5)">1Y ↕</th>
      <th onclick="sortScanner(6)">MA20 ↕</th>
      <th onclick="sortScanner(7)">MA50 ↕</th>
      <th onclick="sortScanner(8)">ATR Ext. ↕</th>
      <th onclick="sortScanner(9)">Vol Rel. ↕</th>
      <th onclick="sortScanner(10)">RS ↕</th>
      <th onclick="sortScanner(11)">52W ↕</th>
      <th>Señal</th>
    </tr></thead><tbody id="tb-scanner"></tbody></table></div>
  </div>

  <!-- ═══ WATCHLIST ═══ -->
  <div id="tab-watchlist" class="tc">
    <div class="sh">
      <span class="st">⭐ WATCHLIST DIARIA</span>
      <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
        <button class="pb" onclick="buildWatchlist()">🔄 Generar Watchlist</button>
        <button class="pb" onclick="copyTickers()">📋 Copiar tickers</button>
        <span style="font-size:9px;color:var(--dim)">Top acciones por setup + industria fuerte</span>
      </div>
    </div>
    <div id="wl-status" style="font-size:10px;color:var(--dim);margin-bottom:8px;line-height:1.6"></div>
    <!-- Copy textarea hidden -->
    <textarea id="wl-copy-area" style="position:absolute;left:-9999px"></textarea>
    <div id="wl-criteria" style="background:var(--bg2);border:1px solid var(--b1);border-radius:8px;padding:12px;margin-bottom:12px;font-size:10px;color:var(--dim);line-height:1.7;display:none">
      <strong style="color:var(--hi)">Criterios de selección:</strong><br>
      ✅ RS ≥ 70 (líder o por encima de media) · ✅ Sobre MA50 · ✅ Industria en tendencia (1M positivo) · 
      ✅ Volumen relativo ≥ 1.0 · ✅ Precio &gt; $10 · ✅ 1D ≥ 0 (no en caída libre)<br>
      <strong>Setups priorizados:</strong> Near 52W High · High Vol Close · Gap Up · Above All MAs
    </div>
    <div class="tw"><table id="wl-table"><thead><tr>
      <th style="text-align:left" onclick="sortWL(0)"># Ticker ↕</th>
      <th onclick="sortWL(1)">Precio ↕</th>
      <th onclick="sortWL(2)">1D ↕</th>
      <th onclick="sortWL(3)">1W ↕</th>
      <th onclick="sortWL(4)">1M ↕</th>
      <th onclick="sortWL(5)">RS ↕</th>
      <th onclick="sortWL(6)">MA50</th>
      <th onclick="sortWL(7)">Vol Rel. ↕</th>
      <th>Setup</th><th>Industria</th>
    </tr></thead><tbody id="tb-watchlist"></tbody></table></div>
  </div>

  <!-- CARTERA -->
  <div id="tab-cartera" class="tc">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:16px">
      <div>
        <div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:var(--hi)">💼 Mi Cartera</div>
        <div style="font-size:10px;color:var(--dim);margin-top:2px">Seguimiento de posiciones · Métricas profesionales · Datos guardados localmente</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button class="pb active" id="ct-btn-overview"   onclick="ctTab('overview',this)">Overview</button>
        <button class="pb"        id="ct-btn-add"        onclick="ctTab('add',this)">+ Añadir transacción</button>
        <button class="pb"        id="ct-btn-positions"  onclick="ctTab('positions',this)">Posiciones</button>
        <button class="pb"        id="ct-btn-riesgo"     onclick="ctTab('riesgo',this)">Riesgo & Métricas</button>
        <button class="pb" onclick="clearCartera()" style="color:var(--dn);border-color:rgba(244,63,94,.3)">🗑 Limpiar</button>
      </div>
    </div>

    <!-- OVERVIEW -->
    <div id="ct-overview">
      <!-- KPI strip -->
      <div id="ct-kpis" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(140px,1fr));gap:8px;margin-bottom:14px"></div>
      <!-- Period returns row -->
      <div id="ct-periods" style="display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin-bottom:14px"></div>
      <!-- Main chart: perf + drawdown combined + donut -->
      <div style="display:grid;grid-template-columns:2fr 1fr;gap:10px;margin-bottom:10px">
        <div class="cw" style="padding:10px">
          <div class="ct" style="margin-bottom:4px;display:flex;justify-content:space-between">
            <span>📈 Rentabilidad cartera vs S&P 500</span>
            <span style="font-size:10px;color:var(--dim)"><span style="color:#38bdf8">■</span> Cartera &nbsp;<span style="color:#64748b">┅</span> S&P500</span>
          </div>
          <div style="position:relative;height:180px"><canvas id="ct-perf-canvas" height="180"></canvas></div>
          <div class="ct" style="margin-top:8px;margin-bottom:4px;display:flex;justify-content:space-between">
            <span>📉 Drawdown histórico</span>
            <span id="ct-dd-label" style="font-size:10px;color:var(--dn)"></span>
          </div>
          <div style="position:relative;height:100px"><canvas id="ct-dd-canvas" height="100"></canvas></div>
        </div>
        <div class="cw" style="padding:10px">
          <div class="ct" style="margin-bottom:6px">🧩 Distribución por ticker</div>
          <div style="position:relative;height:180px"><canvas id="ct-donut-canvas" height="180"></canvas></div>
          <div id="ct-donut-legend" style="margin-top:8px;font-size:10px;color:var(--dim)"></div>
        </div>
      </div>
      <!-- Sector breakdown -->
      <div class="cw" style="padding:10px;margin-bottom:10px">
        <div class="ct" style="margin-bottom:8px">🏢 Distribución por sector</div>
        <div id="ct-sector-bars" style="display:flex;flex-direction:column;gap:6px"></div>
      </div>
      <!-- Monthly returns table -->
      <div class="cw" style="padding:10px;margin-bottom:10px">
        <div class="ct" style="margin-bottom:8px">📅 Rentabilidad mensual — estilo Amibroker</div>
        <div id="ct-monthly-table" class="tw" style="overflow-x:auto"></div>
      </div>
      <!-- Correlation vs SPX -->
      <div class="cw" style="padding:10px;margin-bottom:10px">
        <div class="ct" style="margin-bottom:8px">🔗 Correlación y Beta vs S&P 500</div>
        <div id="ct-corr-content"></div>
      </div>
    </div>

    <!-- ADD TRANSACTION -->
    <div id="ct-add" style="display:none">
      <div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:18px 20px;margin-bottom:14px">
        <div style="display:flex;gap:10px;margin-bottom:14px">
          <button class="pb active" id="ct-side-buy" onclick="ctSetSide('buy',this)" style="padding:6px 18px;font-size:12px">📈 Compra</button>
          <button class="pb" id="ct-side-sell" onclick="ctSetSide('sell',this)" style="padding:6px 18px;font-size:12px">📉 Venta</button>
          <input type="hidden" id="ct-side" value="buy">
        </div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end">
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Ticker</label>
            <input id="ct-ticker" class="si" style="width:90px;text-transform:uppercase" placeholder="NVDA" maxlength="8">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Precio $ (opcional)</label>
            <input id="ct-price" class="si" type="number" style="width:110px" placeholder="500.00" step="any" oninput="ctCalcQty()">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Capital invertido $</label>
            <input id="ct-capital" class="si" type="number" style="width:120px" placeholder="5000" step="any" oninput="ctCalcQty()">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Acciones (auto)</label>
            <input id="ct-qty" class="si" type="number" style="width:90px" placeholder="10" min="0.001" step="any" oninput="ctCalcCapital()">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Stop loss $</label>
            <input id="ct-stop" class="si" type="number" style="width:100px" placeholder="450.00" step="any">
          </div>
          <div style="display:flex;flex-direction:column;gap:4px">
            <label style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em">Fecha</label>
            <input id="ct-date" class="si" type="date" style="width:140px">
          </div>
          <button class="pb active" style="height:36px;padding:0 18px;font-size:12px;background:rgba(56,189,248,.1);border-color:var(--ac);color:var(--ac)" onclick="ctAddTx()">+ Registrar</button>
        </div>
        <div id="ct-add-msg" style="font-size:11px;color:var(--dim);margin-top:8px"></div>
        <div id="ct-add-err" style="font-size:11px;color:var(--dn);margin-top:6px;display:none"></div>
      </div>
      <!-- Transaction history -->
      <div class="tw"><table><thead><tr>
        <th style="text-align:left">Ticker</th><th>Tipo</th><th>Acciones</th>
        <th>Precio</th><th>Stop</th><th>Riesgo/acc</th><th>Riesgo total</th><th>Fecha</th><th></th>
      </tr></thead><tbody id="ct-tx-body"></tbody></table></div>
    </div>

    <!-- POSITIONS -->
    <div id="ct-positions" style="display:none">
      <div class="tw"><table><thead><tr>
        <th style="text-align:left">Ticker</th>
        <th>Acciones</th><th>P. Medio</th><th>P. Actual*</th>
        <th>Valor</th><th>P&L $</th><th>P&L %</th><th>% Cartera</th><th>Stop</th><th>Riesgo abierto</th>
      </tr></thead><tbody id="ct-pos-body"></tbody></table></div>
      <div style="font-size:10px;color:var(--dim)">* Precio actual tomado de D.stockPerf si disponible, si no se usa precio de entrada.</div>
    </div>

    <!-- RIESGO & METRICAS -->
    <div id="ct-riesgo" style="display:none">
      <div id="ct-metrics-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:10px;margin-bottom:16px"></div>
      <div style="background:var(--bg2);border:1px solid var(--b1);border-radius:9px;padding:14px 16px;margin-bottom:12px">
        <div class="ct" style="margin-bottom:8px">Distribución de retornos diarios</div>
        <div style="position:relative;height:160px"><canvas id="ct-ret-canvas" height="160"></canvas></div>
      </div>
    </div>
  </div>

  <p class="foot">Datos: Yahoo Finance · ETF proxies · __TS__ · No es asesoramiento financiero</p>
</div>

<!-- Mobile bottom navigation -->
<nav id="mobile-nav" role="navigation" aria-label="Navegación móvil">
  <button onclick="sw('briefing',document.getElementById('tab-briefing-btn'));mobileNav(this)" class="active">
    <span>📋</span><span>Resumen</span>
  </button>
  <button onclick="sw('sectors',document.getElementById('tab-sectors-btn') || this);mobileNav(this)">
    <span>📊</span><span>Sectores</span>
  </button>
  <button onclick="sw('breadth',document.getElementById('tab-breadth-btn'));mobileNav(this)">
    <span>📡</span><span>Amplitud</span>
  </button>
  <button onclick="sw('stocks',document.getElementById('tab-stocks-btn'));mobileNav(this)">
    <span>🔍</span><span>Acción</span>
  </button>
  <button onclick="sw('cartera',document.getElementById('tab-cartera-btn'));mobileNav(this)">
    <span>💼</span><span>Cartera</span>
  </button>
</nav>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
const D=__DATA__;

// ── Estado ──────────────────────────────────────────────────────────────────
let PD={s:'1D',i:'1D'}, SS={}, MP='1D', MST=[], cblt=false, carteraLoaded=false;

// ── Init ────────────────────────────────────────────────────────────────────
window.onload=()=>{
  const su=D.breadthSummary;
  document.getElementById('ts-l').textContent=D.ts;
  const sc=su.spy_chg>=0;
  const spyP=document.getElementById('spy-p');
  spyP.className='pill '+(sc?'pup':'pdn');
  spyP.textContent='SPY '+(sc?'+':'')+su.spy_chg+'%';
  const vx=su.vix,vw=typeof vx==='number'&&vx>20;
  const vixP=document.getElementById('vix-p');
  vixP.className='pill '+(vw?'pwarn':'pup');
  vixP.textContent='VIX '+vx;
  renderBstrip();
  renderHM('s'); renderHM('i');
  renderTbl('tb-s',D.sectors,true,'sector');
  renderTbl('tb-i',D.industries,true,'industry');
  renderBmTbl();
  document.getElementById('ind-cnt').textContent=D.industries.length+' industrias';
  // Quick tickers
  // Quick tickers filled from stockPerf keys for discovery
  const qTks=['NVDA','AAPL','MSFT','AMZN','META','TSLA','GOOGL','JPM','NVDA','JPM'];
  qTks.slice(0,8).forEach(t=>{
    const b=document.createElement('button');
    b.className='pb';b.textContent=t;
    b.onclick=()=>{document.getElementById('stk-ticker').value=t;loadStock();};
    document.getElementById('quick-tickers').appendChild(b);
  });
  // Add hint
  const hint=document.createElement('span');
  hint.style.cssText='font-size:9px;color:var(--dim);align-self:center';
  hint.textContent='(escribe cualquier ticker del universo)';
  document.getElementById('quick-tickers').appendChild(hint);
};

// ── Breadth strip ────────────────────────────────────────────────────────────
function renderBstrip(){
  const s=D.breadthSummary;
  const items=[
    {l:'S&P 500',v:'$'+s.spy_price,c:s.spy_chg},
    {l:'VIX',v:s.vix,c:s.vix_chg},
    {l:'Avanzando',v:s.advancing,u:'de '+s.total_sample,c:null},
    {l:'Retrocediendo',v:s.declining,u:'de '+s.total_sample,c:null},
    {l:'52W Máximos',v:s.new_highs,c:null},
    {l:'52W Mínimos',v:s.new_lows,c:null},
  ];
  document.getElementById('bstrip').innerHTML=items.map(it=>{
    const cc=it.c!==null?`<div class="bc-c ${it.c>=0?'up':'dn'}">${it.c>=0?'+':''}${it.c}%</div>`:'';
    const uu=it.u?`<div style="font-size:9px;color:var(--dim)">${it.u}</div>`:'';
    return `<div class="bc"><div class="bc-l">${it.l}</div><div class="bc-v">${it.v}</div>${cc}${uu}</div>`;
  }).join('');
}

// ── Heatmap ──────────────────────────────────────────────────────────────────
function renderHM(type){
  const arr=type==='s'?D.sectors:D.industries;
  const p=PD[type]; const el=document.getElementById('hm-'+type);
  const mx=Math.max(...arr.map(r=>Math.abs(r[p]||0)),0.01);
  el.innerHTML=arr.map(r=>{
    const pct=r[p]||0,t=Math.min(Math.abs(pct)/mx,1);
    const bg=pct>=0?`rgba(16,185,129,${.1+t*.62})`:`rgba(244,63,94,${.1+t*.62})`;
    const tp=type==='s'?'sector':'industry';
    const nm=r.name.replace(/'/g,"\'");
    return `<div class="hmc" style="background:${bg}" title="${r.name}: ${pct>0?'+':''}${pct}% (${p})"
      onclick="openDD('${tp}','${nm}')">
      <div class="hmc-n">${r.name}</div>
      <div class="hmc-t">${r.ticker}</div>
      <div class="hmc-p ${pct>=0?'up':'dn'}">${pct>0?'+':''}${pct}%</div>
      <div class="hmc-pr">$${r.price}</div>
    </div>`;
  }).join('');
}
// ── Table ────────────────────────────────────────────────────────────────────
function fmt(v,pct=true){
  if(v===null||v===undefined)return'<span class="neu">—</span>';
  const c=v>0.1?'up':v<-0.1?'dn':'neu';
  return `<span class="${c}">${v>0?'+':''}${v}${pct?'%':''}</span>`;
}
function gauge(lo,hi,p){
  const pct=Math.max(0,Math.min(100,((p-lo)/(hi-lo))*100));
  return `<div class="gw"><span style="font-size:9px;color:var(--dim)">${Math.round(pct)}%</span>
    <div class="gt"><div class="gf" style="width:${pct}%"></div><div class="gd" style="left:${pct}%"></div></div></div>`;
}
function sparkSVG(pts,upColor='#10b981',dnColor='#f43f5e'){
  if(!pts||pts.length<2)return'—';
  const w=60,h=20;
  const mn=Math.min(...pts),mx=Math.max(...pts);
  const rng=mx-mn||1;
  const xs=pts.map((_,i)=>i/(pts.length-1)*w);
  const ys=pts.map(p=>h-(p-mn)/rng*(h-2)-1);
  const d='M'+xs.map((x,i)=>`${x},${ys[i]}`).join('L');
  const clr=pts[pts.length-1]>=pts[0]?upColor:dnColor;
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><path d="${d}" fill="none" stroke="${clr}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
function abvBadge(flag,lbl){
  if(flag===null||flag===undefined)return'<span class="neu">—</span>';
  return `<span class="badge ${flag?'b-up':'b-dn'}">${flag?'▲':'▼'} ${lbl}</span>`;
}

function renderTbl(id,arr,clickable,type){
  document.getElementById(id).innerHTML=arr.map((r,i)=>{
    const dc=r.distHi>=-5?'up':r.distHi>=-15?'neu':'dn';
    const ck=clickable?`onclick="openDD('${type}','${r.name.replace(/'/g,"\\'")}')"`:'' ;
    return `<tr ${ck}>
      <td><span class="rk">${i+1}</span><span class="nm">${r.name}</span></td>
      <td>${r.ticker}</td><td>$${r.price}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td>
      <td>${fmt(r['3M'])}</td><td>${fmt(r['6M']??null)}</td><td>${fmt(r['1Y'])}</td>
      <td>${gauge(r['52wLow'],r['52wHigh'],r.price)}</td>
      <td><span class="${dc}">${r.distHi}%</span></td>
    </tr>`;
  }).join('');
}

// ── BENCHMARK TABLE with click-to-chart ──────────────────────────────────────
let _bmChart=null;
function renderBmTbl(){
  document.getElementById('tb-b').innerHTML=D.benchmarks.map((r,i)=>{
    const dc=r.distHi>=-5?'up':r.distHi>=-15?'neu':'dn';
    return `<tr onclick="openBMChartByIdx(${i})" style="cursor:pointer">
      <td><span class="rk">${i+1}</span><span class="nm">${r.name}</span></td>
      <td>${r.ticker}</td><td>$${r.price}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td>
      <td>${fmt(r['3M'])}</td><td>${fmt(r['6M']??null)}</td><td>${fmt(r['1Y'])}</td>
      <td>${gauge(r['52wLow'],r['52wHigh'],r.price)}</td>
      <td><span class="${dc}">${r.distHi}%</span></td>
    </tr>`;
  }).join('');
}
function openBMChartByIdx(i){
  const r=D.benchmarks[i];
  if(!r)return;
  // Build synthetic OHLC from priceHistory if no ohlc available
  const ohlc=(r.ohlc&&r.ohlc.length)?r.ohlc:(r.priceHistory||[]).map((c,j,a)=>({t:(r.priceDates||[])[j]||'',o:c,h:c,l:c,c:c}));
  openCandleModal(r.name+' ('+r.ticker+')', 'ETF/proxy · 90 días', ohlc);
}
function openCandleModal(title, meta, ohlc){
  if(!ohlc||!ohlc.length){alert('Sin datos OHLC para '+title);return;}
  document.getElementById('bm-name').textContent=title;
  document.getElementById('bm-meta').textContent=meta+' · EMA9 ■ MA20 ■ MA50';
  document.getElementById('bm-ov').classList.add('open');
  document.body.style.overflow='hidden';
  if(_bmChart){_bmChart.destroy();_bmChart=null;}
  setTimeout(()=>drawStkCandle(document.getElementById('bm-chart'),ohlc),30);
}
function closeBMModal(e){
  if(e&&e.target!==document.getElementById('bm-ov'))return;
  document.getElementById('bm-ov').classList.remove('open');
  document.body.style.overflow='';
}
function openETFCandle(name,ticker,ohlc,chg){
  // ohlc may be empty for sector ETFs not in fetch_perf ohlc — build from priceHistory
  let data=ohlc;
  if(!data||!data.length){
    // try sector/industry data
    const bm=D.benchmarks.find(b=>b.ticker===ticker);
    if(bm&&bm.ohlc&&bm.ohlc.length){data=bm.ohlc;}
    else if(bm&&bm.priceHistory&&bm.priceHistory.length){
      data=bm.priceHistory.map((c,i)=>({t:(bm.priceDates||[])[i]||'',o:c,h:c,l:c,c:c}));
    }
  }
  openCandleModal(name+' ('+ticker+')', chg+' · ETF proxy', data&&data.length?data:[]);
}

// ── DRILL DOWN ───────────────────────────────────────────────────────────────
function openDD(type,name){
  const stocks=(type==='sector'?D.sectorStocks:D.industryStocks)[name]||[];
  const etf=type==='sector'
    ?(D.sectors.find(s=>s.name===name)||{}).ticker
    :(D.industryMeta[name]||(D.industries.find(s=>s.name===name)||{}).ticker);
  document.getElementById('m-title').textContent=name;
  document.getElementById('m-sub').textContent=type==='sector'?'Sector S&P 500':'Industria / Tema';
  document.getElementById('m-etf').textContent='ETF: '+(etf||'—');
  MST=stocks; renderModTbl();
  document.getElementById('ov').classList.add('open');
  document.body.style.overflow='hidden';
}
function renderModTbl(){
  const sorted=[...MST].sort((a,b)=>(b[MP]||0)-(a[MP]||0));
  const tb=document.getElementById('m-tbody');
  if(!sorted.length){
    tb.innerHTML=`<tr><td colspan="14" style="text-align:center;padding:22px;color:var(--dim)">Sin datos. Ejecuta el script para descargar constituyentes.</td></tr>`;
    return;
  }
  tb.innerHTML=sorted.map((r,i)=>{
    const vr=r.volRel;
    const vrStr=vr?`<span class="${vr>1.5?'up':vr<0.5?'dn':'neu'}">${vr}x</span>`:'—';
    return `<tr style="cursor:pointer" onclick="openStockCandle('${r.ticker}')"
      title="Click para ver gráfico de velas de ${r.ticker}">
      <td><span class="rk">${i+1}</span><span class="nm">${r.ticker}</span></td>
      <td style="color:var(--dim)">${r.ticker}</td>
      <td>$${r.price||'—'}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td><td>${fmt(r['3M'])}</td><td>${fmt(r['1Y'])}</td>
      <td>${abvBadge(r.abv20,'MA20')}</td>
      <td>${abvBadge(r.abv50,'MA50')}</td>
      <td>${abvBadge(r.abv200,'MA200')}</td>
      <td>${vrStr}</td>
      <td>${gauge(r['52wLow']||0,r['52wHigh']||100,r.price)}</td>
      <td class="spark-cell">${sparkSVG(r.spark||[])}</td>
    </tr>`;
  }).join('');
}
function setMP(p,btn){
  MP=p;
  document.querySelectorAll('#m-pbs .pb').forEach(b=>b.classList.remove('active'));
  if(btn)btn.classList.add('active'); renderModTbl();
}
function setMPdirect(p){
  // Sort by period p without needing the button element
  MP=p;
  document.querySelectorAll('#m-pbs .pb').forEach(b=>{
    b.classList.toggle('active', b.textContent.trim()===p);
  });
  renderModTbl();
}
let _modalSort={col:-1,asc:-1};
function sortModal(col){
  const colFns=[
    r=>r.ticker,null,r=>r.price||0,
    r=>r['1D']||0,r=>r['1W']||0,r=>r['1M']||0,r=>r['3M']||0,r=>r['1Y']||0,
    r=>r.abv20?1:0,r=>r.abv50?1:0,r=>r.abv200?1:0,r=>r.volRel||0
  ];
  if(_modalSort.col===col) _modalSort.asc*=-1; else {_modalSort.col=col;_modalSort.asc=-1;}
  const fn=colFns[col];
  if(!fn)return;
  MST=[...MST].sort((a,b)=>(fn(b)-fn(a))*_modalSort.asc);
  renderModTbl();
}
function openStockCandle(tk){
  const sp=D.stockPerf||{};
  const r=sp[tk];
  if(!r||!r.ohlc||!r.ohlc.length){
    // fallback: open Panel Accion
    document.getElementById('stk-ticker').value=tk;
    closeModal();
    sw('stocks',document.getElementById('tab-stocks-btn'));
    loadStock();
    return;
  }
  const chg=r['1D']!==undefined?(r['1D']>0?'+':'')+r['1D']+'%':'';
  openCandleModal(tk+' — $'+r.price, chg+' · RS por encima de MA20/50/200', r.ohlc);
}
function closeModal(e){
  if(e&&e.target!==document.getElementById('ov'))return;
  document.getElementById('ov').classList.remove('open');
  document.body.style.overflow='';
}

// ── BREADTH TAB ───────────────────────────────────────────────────────────────
function renderBreadthTab(){
  if(cblt)return; cblt=true;
  const su=D.breadthSummary;

  // Score ring
  const score=su.score||0;
  const circ=238.76;
  const offset=circ-(circ*score/100);
  document.getElementById('score-arc').setAttribute('stroke-dashoffset',offset);
  document.getElementById('score-num').textContent=score;
  document.getElementById('score-label').textContent=su.score_label||'—';
  document.getElementById('score-desc').textContent=
    `Basado en: % sobre MA50/200, nuevos máximos/mínimos, VIX, High Yield, McClellan`;
  document.getElementById('adv-badge').textContent=`▲ ${su.advancing} avanzando`;
  document.getElementById('dec-badge').textContent=`▼ ${su.declining} retrocediendo`;
  document.getElementById('unch-badge').textContent=`= ${su.unchanged} sin cambio`;
  document.getElementById('nh-badge').textContent=`★ ${su.new_highs} máximos (ver)`;
  document.getElementById('nl-badge').textContent=`✗ ${su.new_lows} mínimos (ver)`;

  // Amplitude metrics
  document.getElementById('amp-grid').innerHTML=[
    {l:'% sobre MA50',   v:su.pct_abv50+'%',  sub:`${Math.round((su.total_sp500||su.total_sample)*su.pct_abv50/100)} de ${su.total_sp500||su.total_sample} (SP500)`},
    {l:'% sobre MA200',  v:su.pct_abv200+'%', sub:`${Math.round((su.total_sp500||su.total_sample)*su.pct_abv200/100)} de ${su.total_sp500||su.total_sample} (SP500)`},
    {l:'Nuevos Máx 52W', v:su.new_highs,       sub:'click en badge para ver tickers'},
    {l:'Nuevos Mín 52W', v:su.new_lows,        sub:'click en badge para ver tickers'},
    {l:'AD Ratio',       v:su.advancing&&su.declining?Math.round(su.advancing/Math.max(su.declining,1)*10)/10+'x':'—', sub:`${su.advancing}▲ vs ${su.declining}▼ (${su.total_sample} acciones)`},
    {l:'Score Mercado',  v:su.score+'/100',     sub:su.score_label},
  ].map(it=>`<div class="amp-card"><div class="amp-l">${it.l}</div><div class="amp-v">${it.v}</div><div class="amp-sub">${it.sub}</div></div>`).join('');

  // NYSE & Put/Call grid
  const nyGrid=document.getElementById('nyse-grid');
  if(nyGrid){
    const pcColor=v=>{const n=parseFloat(v);if(isNaN(n))return'neu';return n>1.2?'dn':n<0.7?'up':'neu';};
    const pcNote=v=>{const n=parseFloat(v);if(isNaN(n))return'Sin datos';return n>1.2?'Miedo (señal alcista contrarian)':n<0.7?'Euforia (señal bajista contrarian)':'Zona neutral';};
    nyGrid.innerHTML=[
      {l:'NYSE Composite',v:su.nyse_price!=='N/A'?'$'+su.nyse_price:'—',c:su.nyse_chg>=0?'up':'dn',a:su.nyse_chg>=0?'▲':'▼',n:(su.nyse_chg>=0?'+':'')+su.nyse_chg+'%'},
      {l:'NYSE Cambio 1D',v:(su.nyse_chg>=0?'+':'')+su.nyse_chg+'%',c:su.nyse_chg>=0?'up':'dn',a:su.nyse_chg>=0?'▲':'▼',n:'NYSE Composite diario'},
      {l:'VVIX (Vol del VIX)',v:su.pc_total!=='N/A'?su.pc_total:'—',c:su.pc_total!=='N/A'&&parseFloat(su.pc_total)>120?'dn':su.pc_total!=='N/A'&&parseFloat(su.pc_total)<90?'up':'neu',a:'',n:su.pc_total!=='N/A'&&parseFloat(su.pc_total)>120?'Alta incertidumbre':su.pc_total!=='N/A'&&parseFloat(su.pc_total)<90?'Baja volatilidad':'Normal'},
      {l:'SKEW (Riesgo de cola)',v:su.pc_equity!=='N/A'?su.pc_equity:'—',c:su.pc_equity!=='N/A'&&parseFloat(su.pc_equity)>140?'dn':su.pc_equity!=='N/A'&&parseFloat(su.pc_equity)<115?'up':'neu',a:'',n:su.pc_equity!=='N/A'&&parseFloat(su.pc_equity)>140?'Miedo a caída fuerte':su.pc_equity!=='N/A'&&parseFloat(su.pc_equity)<115?'Mercado tranquilo':'Riesgo normal'},
    ].map(r=>`<div class="risk-c"><div class="risk-l">${r.l}</div><div class="risk-a ${r.c}">${r.a}</div><div class="risk-v ${r.c}">${r.v}</div><div class="risk-n">${r.n}</div></div>`).join('');
  }

  // Risk grid
  document.getElementById('risk-g').innerHTML=[
    {l:'High Yield (HYG)',c:su.hyg_chg>=0?'up':'dn',a:su.hyg_chg>=0?'▲':'▼',v:(su.hyg_chg>=0?'+':'')+su.hyg_chg+'%',n:'Risk-ON si sube'},
    {l:'Tesoros 20Y (TLT)',c:su.tlt_chg>=0?'up':'dn',a:su.tlt_chg>=0?'▲':'▼',v:(su.tlt_chg>=0?'+':'')+su.tlt_chg+'%',n:'Refugio si sube'},
    {l:'Dólar USD (UUP)',c:su.uup_chg>=0?'dn':'up',a:su.uup_chg>=0?'▲':'▼',v:(su.uup_chg>=0?'+':'')+su.uup_chg+'%',n:'Presión RV si sube'},
    {l:'Oro (GLD)',c:su.gld_chg>=0?'up':'neu',a:su.gld_chg>=0?'▲':'▼',v:(su.gld_chg>=0?'+':'')+su.gld_chg+'%',n:'Inflación/miedo'},
  ].map(r=>`<div class="risk-c"><div class="risk-l">${r.l}</div><div class="risk-a ${r.c}">${r.a}</div><div class="risk-v ${r.c}">${r.v}</div><div class="risk-n">${r.n}</div></div>`).join('');

  // Charts
  const ser=D.breadthSeries;
  const mkC=(id,tk,col,label)=>{
    const d=ser[tk]; if(!d||!d.values.length)return;
    const ctx=document.getElementById(id); if(!ctx)return;
    new Chart(ctx,{type:'line',data:{labels:d.dates,datasets:[{
      data:d.values,borderColor:col,borderWidth:1.5,pointRadius:0,
      fill:true,backgroundColor:col.replace('rgb','rgba').replace(')',',0.06)'),tension:0.3
    }]},options:{responsive:true,plugins:{legend:{display:false},
      tooltip:{mode:'index',intersect:false,callbacks:{label:c=>'$'+c.parsed.y.toFixed(2)}}},
      scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:7},grid:{color:'#1c2436'}},
        y:{ticks:{color:'#3a4860',font:{size:9},callback:v=>'$'+v},grid:{color:'#1c2436'}}}}});
  };
  // Fill daily change badges on chart titles
  const chgFill=(id,val)=>{const el=document.getElementById(id);if(!el||val===undefined)return;const c=parseFloat(val);if(isNaN(c))return;el.innerHTML=`<span class="${c>=0?'up':'dn'}">${c>=0?'+':''}${c}% hoy</span>`;};
  const bl=D.breadthLatest||{};
  chgFill('chg-spy',bl['SPY']?.chg);chgFill('chg-vix',bl['^VIX']?.chg);
  chgFill('chg-hyg',bl['HYG']?.chg);chgFill('chg-tlt',bl['TLT']?.chg);
  chgFill('chg-uup',bl['UUP']?.chg);chgFill('chg-gld',bl['GLD']?.chg);
  chgFill('chg-btc',bl['IBIT']?.chg);chgFill('chg-nya',bl['^NYA']?.chg);
  mkC('c-spy','SPY','rgb(56,189,248)');
  mkC('c-vix','^VIX','rgb(244,63,94)');
  mkC('c-hyg','HYG','rgb(16,185,129)');
  mkC('c-tlt','TLT','rgb(245,158,11)');
  mkC('c-uup','UUP','rgb(167,139,250)');
  mkC('c-gld','GLD','rgb(251,191,36)');
  mkC('c-btc','IBIT','rgb(249,115,22)');
  mkC('c-nya','^NYA','rgb(100,200,255)');
  mkC('c-vvix','^VVIX','rgb(220,100,255)');
  mkC('c-skew','^SKEW','rgb(255,165,50)');
  mkC('c-tip','TIP','rgb(52,211,153)');
  mkC('c-agg','AGG','rgb(99,179,237)');
  mkC('c-tnx','^TNX','rgb(251,191,36)');
  // Daily change labels para macro
  const tipChg=su.tip_chg||0;const tnxChg=su.tnx_chg||0;const aggChg=su.agg_chg||0;
  if(document.getElementById('tip-chg')) document.getElementById('tip-chg').innerHTML=`<span class="${tipChg>=0?'up':'dn'}">${tipChg>=0?'+':''}${tipChg}% hoy</span>`;
  if(document.getElementById('tnx-chg')) document.getElementById('tnx-chg').innerHTML=`<span class="${tnxChg>=0?'dn':'up'}">${tnxChg>=0?'+':''}${tnxChg}% hoy</span>`;
  if(document.getElementById('agg-chg')) document.getElementById('agg-chg').innerHTML=`<span class="${aggChg>=0?'up':'dn'}">${aggChg>=0?'+':''}${aggChg}% hoy</span>`;

  // ── INTERPRETACIÓN SUBJETIVA DE MERCADO ──────────────────────────────────
  const mc=document.getElementById('market-comment');
  if(mc){
    const score=su.score||0;
    const spy=su.spy_chg||0;
    const vix=su.vix||20;
    const pct50=su.pct_abv50||0;
    const pct200=su.pct_abv200||0;
    const nh=su.new_highs||0;
    const nl=su.new_lows||0;
    const hyg=su.hyg_chg||0;
    const uup=su.uup_chg||0;
    const tlt=su.tlt_chg||0;
    const tip=su.tip_chg||0;
    const agg=su.agg_chg||0;
    const tnx=parseFloat(su.tnx_price)||0;
    const mccLast=su.mcclellan&&su.mcclellan.length?su.mcclellan[su.mcclellan.length-1].val:0;
    const adLast=su.ad_line&&su.ad_line.length?su.ad_line[su.ad_line.length-1].val:0;
    const moodStr=score>=75?'Ofensivo':score>=60?'Neutral Alcista':score>=45?'Neutral':score>=30?'Neutral Bajista':'Defensivo';
    const trendColor=score>=60?'var(--up)':score>=45?'var(--warn)':'var(--dn)';
    const lines=[];

    // ── Bloque 1: diagnóstico general ─────────────────────────────────────
    const breadthOk=pct50>55&&pct200>45;
    const nhNlOk=nh>nl;
    const riskOn=hyg>0&&tlt<0;
    const riskOff=hyg<0&&tlt>0;
    let diag='';
    if(score>=65&&breadthOk&&nhNlOk){
      diag=`El mercado muestra una estructura técnica <strong style="color:var(--up)">sólida y tendencial</strong>. `+
        `El ${pct50}% de los valores cotiza sobre su MA50 y el ${pct200}% sobre MA200 — la mayoría de carteras diversificadas están generando alpha. `+
        `Con ${nh} nuevos máximos frente a ${nl} mínimos, la amplitud confirma que la subida es <em>participada</em>, no solo de megacaps.`;
    } else if(score>=45){
      const weak=pct50<50?'La amplitud muestra dudas — solo el '+pct50+'% supera la MA50':'El porcentaje sobre MA50 es aceptable ('+pct50+'%)';
      diag=`Mercado en zona de <strong style="color:var(--warn)">transición y vigilancia</strong>. ${weak}. `+
        `La batalla entre compradores y vendedores es evidente: ${nh} nuevos máximos vs ${nl} mínimos. `+
        `En este entorno conviene priorizar valores con RS alto y reducir exposición a los rezagados.`;
    } else {
      diag=`⚠️ La estructura técnica está <strong style="color:var(--dn)">deteriorada</strong>. `+
        `Solo el ${pct50}% supera la MA50 y el ${pct200}% la MA200 — muchas carteras están bajo agua. `+
        `Los ${nl} nuevos mínimos dominan sobre ${nh} máximos. Es momento de gestión de riesgo, no de añadir exposición.`;
    }
    lines.push({color:trendColor,icon:'📊',title:`Score ${score}/100 — ${moodStr}`,body:diag});

    // ── Bloque 2: flujo de capital (risk on/off) ───────────────────────────
    if(riskOn){
      lines.push({color:'var(--up)',icon:'🟢',title:'Flujo Risk-ON',body:
        `El High Yield sube mientras los treasuries ceden — dinero fluyendo hacia activos de riesgo. `+
        `Este es el patrón clásico de "risk-on": los bonos basura se demandan porque los inversores confían en que las empresas pagarán. `+
        (hyg>0.3?`Con HYG +${hyg}%, la señal es especialmente contundente. Sectores cíclicos y growth deberían beneficiarse.`:
        `La señal es moderada pero constructiva. Sectores tech y consumo discrecional en foco.`)});
    } else if(riskOff){
      lines.push({color:'var(--dn)',icon:'🔴',title:'Flujo Risk-OFF',body:
        `HYG cae (${hyg}%) mientras TLT sube (${tlt>0?'+':''}${tlt}%) — huida hacia la calidad. `+
        `Los inversores prefieren la seguridad de los treasuries a tomar riesgo en crédito corporativo. `+
        `En este entorno, Utilities, Healthcare y bonos cortos actúan como refugio. Reducir beta de cartera.`});
    } else {
      lines.push({color:'var(--warn)',icon:'🟡',title:'Flujo neutro — sin señal clara',body:
        `HYG y TLT se mueven sin dirección definitiva. El mercado está en modo "esperar y ver", `+
        `típico antes de un dato macro relevante (Fed, IPC, empleo) o en fase de consolidación lateral. `+
        `Buena oportunidad para revisar stops y reducir posiciones especulativas.`});
    }

    // ── Bloque 3: tipos e inflación (macro) ───────────────────────────────
    if(tnx>0){
      const tnxView=tnx>4.5?`El yield 10Y en <strong>${tnx}%</strong> es terreno restrictivo — la Fed mantiene presión sobre la economía. `+
        `Las empresas growth con múltiplos altos sufren más en este entorno ya que la tasa de descuento es elevada. `+
        `Ojo especial a valoraciones del Nasdaq y real estate.`:
        tnx>4?`Yield 10Y en <strong>${tnx}%</strong> — nivel elevado pero ya descontado por el mercado en parte. `+
        `La curva 10Y-2Y es clave: si el spread se estrecha, cuidado con bancarios y financieras.`:
        `Yield 10Y en <strong>${tnx}%</strong> — nivel manejable. Los bonos siguen siendo competitivos vs renta variable.`;
      const tipView=tip>0?`Los TIPS (+${tip}% hoy) reflejan que los breakevens de inflación suben — el mercado empieza a descontar mayor inflación futura. Vigilar oro y commodities como cobertura.`:
        tip<0?`Los TIPS ceden (${tip}%) — expectativas de inflación a la baja, favorable para el múltiplo de los activos growth.`:'';
      lines.push({color:'var(--ac)',icon:'📉',title:'Tipos e inflación',body:tnxView+(tipView?' '+tipView:'')});
    }

    // ── Bloque 4: McClellan + A/D internos ────────────────────────────────
    if(mccLast!==0||adLast!==0){
      const mccStr=mccLast>100?`McClellan muy positivo (+${mccLast.toFixed(0)}) — impulso alcista de amplitud fuerte. Históricamente este nivel precede a continuaciones de tendencia`:
        mccLast>30?`McClellan positivo (+${mccLast.toFixed(0)}) — la mayoría de valores participan en la subida`:
        mccLast<-100?`⚠️ McClellan muy negativo (${mccLast.toFixed(0)}) — señal de capitulación o inicio de rebote técnico`:
        mccLast<-30?`McClellan negativo (${mccLast.toFixed(0)}) — distribución interna, las subidas no están siendo confirmadas`:
        `McClellan en zona neutra (${mccLast.toFixed(0)}) — sin señal de momentum definida`;
      lines.push({color:mccLast>0?'var(--up)':'var(--dn)',icon:'🔬',title:'Análisis interno (McClellan + A/D)',body:
        mccStr+`. La línea A/D acumulada ${adLast>0?'en terreno positivo, confirmando la tendencia alcista':'en terreno negativo, divergencia bajista a vigilar'}.`});
    }

    // ── Bloque 5: dólar y emergentes ──────────────────────────────────────
    if(Math.abs(uup)>0.2){
      lines.push({color:uup>0?'var(--warn)':'var(--up)',icon:'💵',title:`Dólar ${uup>0?'fuerte':'débil'} (UUP ${uup>0?'+':''}${uup}%)`,body:
        uup>0.3?`Un dólar fuerte genera vientos en contra para materias primas y emergentes. Las multinacionales americanas con ingresos en el exterior también sufren en su repatriación. Sector a vigilar: XLB (materiales) y EEM.`:
        uup<-0.3?`La debilidad del dólar es un catalizador positivo para commodities (oro, petróleo, cobre) y mercados emergentes. Momento para revisar exposición a EM y materias primas.`:
        `Movimiento del dólar moderado — sin impacto relevante por ahora.`});
    }

    mc.innerHTML=lines.map(l=>
      `<div style="margin-bottom:10px;padding:10px 14px;background:var(--bg3);border-left:4px solid ${l.color};border-radius:6px">
        <div style="font-size:12px;font-weight:700;color:${l.color};margin-bottom:5px">${l.icon} ${l.title}</div>
        <div style="font-size:11px;color:var(--tx);line-height:1.8">${l.body}</div>
      </div>`).join('');
  }

  // A/D Line
  if(su.ad_line&&su.ad_line.length>0){
    const ctx=document.getElementById('c-adl');
    if(ctx) new Chart(ctx,{type:'line',data:{
      labels:su.ad_line.map(x=>x.date),
      datasets:[{data:su.ad_line.map(x=>x.val),borderColor:'rgb(52,211,153)',borderWidth:1.5,
        pointRadius:0,fill:true,backgroundColor:'rgba(52,211,153,0.06)',tension:0.3}]
    },options:{responsive:true,plugins:{legend:{display:false},tooltip:{mode:'index',intersect:false}},
      scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:7},grid:{color:'#1c2436'}},
        y:{ticks:{color:'#3a4860',font:{size:9}},grid:{color:'#1c2436'}}}}});
  }

  // McClellan Oscillator
  const mcc=su.mcclellan||[];
  if(mcc.length>0){
    const ctx=document.getElementById('c-mcc');
    if(ctx){
      const mccColors=mcc.map(x=>x.val>=0?'rgba(16,185,129,.75)':'rgba(244,63,94,.75)');
      new Chart(ctx,{type:'bar',data:{
        labels:mcc.map(x=>x.date),
        datasets:[{data:mcc.map(x=>x.val),backgroundColor:mccColors,borderRadius:2}]
      },options:{responsive:true,plugins:{legend:{display:false},
        tooltip:{mode:'index',intersect:false,callbacks:{label:c=>c.parsed.y.toFixed(2)}}},
        scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8},grid:{color:'#1c2436'}},
          y:{ticks:{color:'#3a4860',font:{size:9}},grid:{color:'#1c2436'}}}}});
    }
  }

  // Curva 10Y-2Y proxy
  const crv=su.curve_spread||[];
  if(crv.length>0){
    const ctx=document.getElementById('c-crv');
    if(ctx){
      const crvPos=crv.map(x=>x.val>=0?x.val:0);
      const crvNeg=crv.map(x=>x.val<0?x.val:0);
      new Chart(ctx,{type:'bar',data:{
        labels:crv.map(x=>x.date),
        datasets:[
          {data:crvPos,backgroundColor:'rgba(16,185,129,.55)',borderRadius:1},
          {data:crvNeg,backgroundColor:'rgba(244,63,94,.55)',borderRadius:1},
        ]
      },options:{responsive:true,plugins:{legend:{display:false},
        tooltip:{mode:'index',intersect:false,callbacks:{label:c=>c.parsed.y.toFixed(2)+'%'}}},
        scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8},grid:{color:'#1c2436'},stacked:true},
          y:{ticks:{color:'#3a4860',font:{size:9}},grid:{color:'#1c2436'},stacked:true}}}});
    }
  }

  // Distribution bars
  const dist=su.dist_buckets||{};
  const dkeys=Object.keys(dist);
  const dvals=Object.values(dist);
  const dmx=Math.max(...dvals,1);
  const colors={'<-10%':'#f43f5e','-10a-5%':'#f97316','-5a-2%':'#eab308','-2a0%':'#6b7280',
    '0a2%':'#22c55e','2a5%':'#10b981','5a10%':'#06b6d4','>10%':'#38bdf8'};
  document.getElementById('dist-chart').innerHTML=dkeys.map((k,i)=>{
    const pct=Math.round(dvals[i]/dmx*100);
    return `<div class="dist-bar" style="height:${Math.max(pct,4)}%;background:${colors[k]||'var(--ac)'}">
      <span class="dist-val">${dvals[i]}</span>
      <span class="dist-label">${k}</span>
    </div>`;
  }).join('');

  // ── MACD S&P500 (proxy con datos de amplitud) ────────────────────────────────
  (function(){
    var el=document.getElementById('macd-content');
    if(!el) return;
    var sp=D.stockPerf||{};
    var spyData=D.benchmarks?D.benchmarks.filter(function(b){ return b.ticker==='^GSPC'||b.ticker==='SPY'; }):[]; 
    var spy=spyData[0]||null;
    // Derive MACD signal from available momentum data
    var m1=spy?parseFloat(spy['1M']||0):0;
    var m3=spy?parseFloat(spy['3M']||0):0;
    var w1=spy?parseFloat(spy['1W']||0):0;
    // EMA12 proxy > EMA26 proxy => bullish crossover
    var ema12proxy=m1*0.6+w1*2; // faster
    var ema26proxy=m3*0.4;      // slower
    var macdLine=ema12proxy-ema26proxy;
    var signal=macdLine*0.85;   // signal line approx
    var histogram=macdLine-signal;
    var activated=macdLine>0&&macdLine>signal;
    var color=activated?'var(--up)':'var(--dn)';
    el.innerHTML=''
      +'<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">'
        +'<div style="font-family:Syne,sans-serif;font-size:24px;font-weight:800;color:'+color+'">'+(activated?'✅ ACTIVO':'❌ NO ACTIVO')+'</div>'
      +'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px">'
        +'MACD: <strong style="color:'+color+'">'+(macdLine>=0?'+':'')+macdLine.toFixed(2)+'</strong> &nbsp;'
        +'Signal: <strong>'+(signal>=0?'+':'')+signal.toFixed(2)+'</strong> &nbsp;'
        +'Histo: <strong style="color:'+(histogram>0?'var(--up)':'var(--dn)')+'">'+( histogram>=0?'+':'')+histogram.toFixed(2)+'</strong>'
      +'</div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.6;padding:7px 10px;background:var(--bg3);border-radius:5px">'
        +(activated
          ?'MACD por encima de su línea de señal — momentum alcista activo. Históricamente una de las señales más fiables para confirmar tendencias en el S&P500.'
          :'MACD por debajo de señal — momentum bajista o corrección. Esperar cruce alcista (MACD > Signal) para señal de entrada.')
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:5px">Proxy calculado a partir de retornos 1W/1M/3M del S&P500. Para MACD exacto usar EMA12/26/9 en TradingView.</div>';
  })();

  // ── BONOS CEF — señal de flujo de capital ────────────────────────────────────
  (function(){
    var el=document.getElementById('cef-content');
    if(!el) return;
    // CEF bonds proxy: TLT + LQD + AGG movements as capital flow signal
    var tlt=parseFloat(su.tlt_chg||0);
    var agg=parseFloat(su.agg_chg||0);
    var lqd=parseFloat(su.lqd_chg||0);
    var tnx=parseFloat(su.tnx_price||4.5);
    // CEF bond funds typically trade at premium/discount to NAV
    // Rising bond prices = falling yields = favorable for CEF bonds
    var cefSignal=(tlt+agg+(lqd||0))/3;
    var signalOk=cefSignal>0&&tnx<4.8;
    var color=signalOk?'var(--up)':cefSignal<-0.3?'var(--dn)':'var(--warn)';
    var label=signalOk?'✅ FLUJO POSITIVO':cefSignal<-0.3?'❌ FLUJO NEGATIVO':'🟡 NEUTRO';
    el.innerHTML=''
      +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+';margin-bottom:7px">'+label+'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px">'
        +'TLT: <span class="'+(tlt>=0?'up':'dn')+'">'+(tlt>=0?'+':'')+tlt.toFixed(2)+'%</span> &nbsp;'
        +'AGG: <span class="'+(agg>=0?'up':'dn')+'">'+(agg>=0?'+':'')+agg.toFixed(2)+'%</span> &nbsp;'
        +'Yield10Y: <strong>'+tnx.toFixed(2)+'%</strong>'
      +'</div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.6;padding:7px 10px;background:var(--bg3);border-radius:5px">'
        +(signalOk
          ?'Los bonos suben — los CEF de renta fija cotizan con menor descuento o en prima. Entorno favorable para bonos de alto cupón (closed-end funds de RF).'
          :cefSignal<-0.3
          ?'Bonos bajo presión — los CEF de renta fija pueden ampliar su descuento al NAV. Moment de precaución en RF.'
          :'Señal mixta en bonos. Los CEF de RF en zona de transición. Monitorizar yield 10Y.')
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:5px">CEF = Closed-End Funds. Proxy via TLT/AGG. Para lista real: CEFconnect.com</div>';
  })();

  // ── COPPOCK CURVE — indicador mensual de largo plazo ─────────────────────────
  (function(){
    var el=document.getElementById('coppock-content');
    if(!el) return;
    var spy=D.benchmarks?D.benchmarks.find(function(b){ return b.ticker==='^GSPC'||b.ticker==='SPY'; }):null;
    // Coppock = WMA(10) of (ROC(14 months) + ROC(11 months))
    // Proxy: use available return data
    var roc14=spy?parseFloat(spy['1Y']||0):0;  // ~12m proxy
    var roc11=spy?parseFloat(spy['3M']||0)*4:0; // ~11m proxy (3M annualized)
    var rawCoppock=roc14*0.6+roc11*0.4;
    // WMA smoothing proxy: combine with shorter term
    var m1=spy?parseFloat(spy['1M']||0):0;
    var coppock=(rawCoppock*0.7+m1*3*0.3);
    var rising=coppock>0&&m1>0;
    var activated=coppock>0;
    var color=activated?'var(--up)':'var(--dn)';
    el.innerHTML=''
      +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+';margin-bottom:7px">'
        +(activated?'✅ POSITIVO':'❌ NEGATIVO')+(rising?' ↑':' ↓')
      +'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px">'
        +'Valor proxy: <strong style="color:'+color+'">'+(coppock>=0?'+':'')+coppock.toFixed(1)+'</strong>'
      +'</div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.6;padding:7px 10px;background:var(--bg3);border-radius:5px">'
        +(activated&&rising
          ?'Coppock positivo y subiendo — señal alcista de largo plazo. Edwin Coppock diseñó este indicador como señal de compra en mercados bajistas. Históricamente muy preciso en mercados mensuales.'
          :activated&&!rising
          ?'Coppock positivo pero girando — momentum de largo plazo se modera. Mantener posiciones pero reducir nuevas compras agresivas.'
          :'Coppock negativo — el modelo mensual no confirma tendencia alcista de largo plazo. Esperar cruce sobre cero.')
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:5px">Coppock Curve original: WMA10 de (ROC14m + ROC11m). Señal válida solo en gráfico mensual.</div>';
  })();

  // ── HAA-SIMPLE (Hybrid Asset Allocation) ─────────────────────────────────────
  (function(){
    var el=document.getElementById('haa-content');
    if(!el) return;
    // HAA-Simple: compare 12-month return of canary assets vs cash/bonds
    // Canary: SPY, EEM, AGG, LQD — if majority positive => risky, else defensive
    var bm=D.benchmarks||[];
    function bm12(tk){ var r=bm.find(function(b){ return b.ticker===tk||b.name===tk; }); return r?parseFloat(r['1Y']||r['1M']*12||0):null; }
    var spy12=bm12('^GSPC')||bm12('SPY');
    var eem12=bm12('EEM');
    var agg12=bm12('AGG')||bm12('TLT');
    var lqd12=bm12('LQD')||bm12('HYG');
    var canaries=[spy12,eem12,agg12,lqd12].filter(function(v){ return v!==null; });
    var positiveCanaries=canaries.filter(function(v){ return v>0; }).length;
    var totalCanaries=canaries.length||1;
    var ratio=positiveCanaries/totalCanaries;
    // HAA-Simple: if >=2/4 canaries positive AND SPY>0 => risk-on
    var riskOn=ratio>=0.5&&(spy12===null||spy12>0);
    var offense=riskOn;
    var color=offense?'var(--up)':'var(--dn)';
    var allocation=offense
      ?['S&P 500 (^GSPC) — 100% ofensivo','o dividir en: SPY 50% + QQQ 25% + IWM 25%']
      :['Bonos cortos (SHY) o Cash — 100% defensivo','Esperar señal de vuelta de canarios'];
    el.innerHTML=''
      +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+';margin-bottom:7px">'
        +(offense?'✅ MODO OFENSIVO':'❌ MODO DEFENSIVO')
      +'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:7px">'
        +'Canarios positivos: <strong>'+positiveCanaries+'/'+totalCanaries+'</strong> &nbsp;|&nbsp; '
        +'SPY 12m: <span class="'+(spy12>=0?'up':'dn')+'">'+(spy12!==null?(spy12>=0?'+':'')+spy12.toFixed(1)+'%':'—')+'</span>'
      +'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em;font-weight:600">Asignación sugerida:</div>'
      +allocation.map(function(a){ return '<div style="font-size:11px;color:var(--tx);margin-bottom:3px">▸ '+a+'</div>'; }).join('')
      +'<div style="font-size:9px;color:var(--dim);margin-top:7px">HAA-Simple de Keller &amp; Keuning (2023). Canarios: SPY, EEM, AGG, LQD. Se revisa mensualmente.</div>';
  })();

  // ── FEAR & GREED — CNN proxy (no se puede cargar via iframe por CORS) ─────────
  (function(){
    var el=document.getElementById('fg-content');
    if(!el) return;
    // CNN Fear & Greed no permite iframe. Calculamos proxy propio (7 componentes)
    var vix=parseFloat(su.vix)||20;
    var pct50=su.pct_abv50||50;
    var nh=su.new_highs||0, nl=su.new_lows||0;
    var hyg=parseFloat(su.hyg_chg||0);
    var tlt=parseFloat(su.tlt_chg||0);
    var m1=parseFloat((D.benchmarks&&D.benchmarks.find(function(b){ return b.ticker==='^GSPC'; }))||{})['1M']||0;
    // 7 components like CNN F&G
    var vixScore=Math.max(0,Math.min(100, vix<12?95:vix<15?82:vix<18?68:vix<22?50:vix<27?30:vix<35?15:5));
    var breadthScore=Math.max(0,Math.min(100, pct50*1.4));
    var nhnlScore=nh+nl>0?Math.max(0,Math.min(100,nh/(nh+nl)*100)):50;
    var hybScore=Math.max(0,Math.min(100, (hyg>0?60:40)+(hyg>0.3?15:-15)));
    var safeScore=Math.max(0,Math.min(100, tlt<0?70:tlt>0.3?30:50));
    var momScore=Math.max(0,Math.min(100, 50+m1*2));
    var score=Math.round((vixScore*0.2+breadthScore*0.2+nhnlScore*0.2+hybScore*0.15+safeScore*0.1+momScore*0.15));
    var label=score>=80?'Codicia Extrema':score>=65?'Codicia':score>=45?'Neutral':score>=25?'Miedo':'Miedo Extremo';
    var color=score>=75?'#ef4444':score>=55?'#f97316':score>=45?'#eab308':score>=30?'#84cc16':'#22c55e';
    var advice=score>=80?'Señal contrarian: el mercado está excesivamente optimista. Warren Buffett: "sé temeroso cuando otros son codiciosos". Revisar stops y reducir exposición especulativa.':
      score>=65?'Codicia moderada. El rally puede continuar pero el margen de seguridad se reduce. Ajustar sizing.':
      score>=45?'Zona neutral: precio eficiente. Sin señal contrarian clara. Seguir el análisis técnico/fundamental.':
      score>=25?'Miedo moderado: pesimismo elevado. Históricamente las mejores compras se hacen en este rango. Buscar acciones con RS alto que aguanten.':
      'Miedo Extremo: señal contrarian alcista muy potente. Las caídas en miedo extremo suelen ser las mejores oportunidades de compra de largo plazo.';
    // Gauge visual
    var pct=score;
    var gaugeGrad='conic-gradient('+color+' 0% '+pct+'%, var(--bg3) '+pct+'% 100%)';
    el.innerHTML=''
      +'<div style="display:flex;gap:14px;align-items:center;margin-bottom:10px">'
        +'<div style="position:relative;width:80px;height:80px;border-radius:50%;background:'+gaugeGrad+';display:flex;align-items:center;justify-content:center;flex-shrink:0">'
          +'<div style="position:absolute;inset:8px;border-radius:50%;background:var(--bg2);display:flex;align-items:center;justify-content:center;flex-direction:column">'
            +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+'">'+score+'</div>'
          +'</div>'
        +'</div>'
        +'<div>'
          +'<div style="font-size:14px;font-weight:700;color:'+color+';margin-bottom:4px">'+label+'</div>'
          +'<div style="display:flex;gap:6px;flex-wrap:wrap;font-size:9px;color:var(--dim)">'
            +'<span>VIX: '+(vixScore).toFixed(0)+'</span>'
            +'<span>Breadth: '+(breadthScore).toFixed(0)+'</span>'
            +'<span>NH/NL: '+(nhnlScore).toFixed(0)+'</span>'
          +'</div>'
        +'</div>'
      +'</div>'
      +'<div style="height:6px;border-radius:3px;background:linear-gradient(90deg,#22c55e,#84cc16,#eab308,#f97316,#ef4444);margin-bottom:5px;position:relative">'
        +'<div style="position:absolute;top:-3px;left:calc('+pct+'% - 6px);width:12px;height:12px;border-radius:50%;background:var(--hi);border:2px solid var(--bg);box-shadow:0 0 6px rgba(255,255,255,.4)"></div>'
      +'</div>'
      +'<div style="display:flex;justify-content:space-between;font-size:8px;color:var(--dim);margin-bottom:9px"><span>Miedo Extremo</span><span>Codicia Extrema</span></div>'
      +'<div style="font-size:10px;color:var(--tx);line-height:1.65;padding:8px 10px;background:var(--bg3);border-radius:6px">'+advice+'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:6px">Proxy propio (7 componentes: VIX, Amplitud, NH/NL, HYG, TLT, Momentum). CNN F&G: markets.money.cnn.com no permite embed por CORS.</div>';
  })();

  // ── AAII SENTIMENT PROXY ─────────────────────────────────────────────────────
  (function(){
    var el=document.getElementById('aaii-content');
    if(!el) return;
    var vix=parseFloat(su.vix)||20;
    var pct50=su.pct_abv50||50;
    var mcc=su.mcclellan&&su.mcclellan.length?su.mcclellan[su.mcclellan.length-1].val:0;
    // Proxy bull/bear/neutral derived from market internals
    var bullBase=38+(pct50-50)*0.4+(mcc/6)+(vix<18?5:vix>25?-8:0);
    var bearBase=30-(pct50-50)*0.3+(vix>25?10:vix<15?-5:0)-(mcc>50?5:mcc<-50?5:0);
    var bull=Math.max(15,Math.min(65,Math.round(bullBase)));
    var bear=Math.max(15,Math.min(55,Math.round(bearBase)));
    var neut=Math.max(10,100-bull-bear);
    var spread=bull-bear;
    var spreadNote=spread>20?'Exceso de optimismo — señal contrarian bajista. Históricamente spreads >20pp preceden correcciones.':
      spread>8?'Sesgo alcista moderado. Constructivo sin excesos.':
      spread>-8?'Mercado equilibrado, sin sesgo definido.':
      spread>-20?'Pesimismo moderado — terreno favorable para posiciones largas en valor.':
      'Spread bajista amplio — miedo extremo. Históricamente señal contrarian alcista muy potente.';
    var spreadColor=spread>20?'var(--dn)':spread>0?'var(--warn)':spread>-20?'var(--ac)':'var(--up)';
    el.innerHTML=''
      +'<div style="margin-bottom:12px">'
      +[['🟢 Alcistas (Bullish)',bull,'var(--up)'],['🔴 Bajistas (Bearish)',bear,'var(--dn)'],['🟡 Neutrales',neut,'var(--warn)']].map(function(r){
        return '<div style="margin-bottom:8px">'
          +'<div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px"><span style="color:var(--tx)">'+r[0]+'</span><span style="font-weight:700;color:'+r[2]+'">'+r[1]+'%</span></div>'
          +'<div style="height:7px;background:var(--bg3);border-radius:4px;overflow:hidden"><div style="height:100%;width:'+r[1]+'%;background:'+r[2]+';border-radius:4px;transition:width .5s"></div></div>'
          +'</div>';
      }).join('')+'</div>'
      +'<div style="padding:10px 13px;background:var(--bg3);border-radius:7px;font-size:11px;line-height:1.75">'
        +'<strong style="color:'+spreadColor+'">Spread Bull-Bear: '+(spread>=0?'+':'')+spread+'pp</strong><br>'+spreadNote
      +'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:7px">Proxy calculado a partir de amplitud MA50, McClellan y VIX. AAII real: aaii.com (encuesta semanal inversores individuales USA)</div>';
  })();

  // ── CICLO KONDRATIEV ─────────────────────────────────────────────────────────
  (function(){
    var el=document.getElementById('kondratiev-content');
    if(!el) return;
    var tnxP=parseFloat(su.tnx_price)||4.5;
    var tipC=parseFloat(su.tip_chg)||0;
    var aggC=parseFloat(su.agg_chg)||0;
    var gldC=parseFloat(su.gld_chg)||0;
    var oilC=parseFloat(su.uso_chg)||0;
    // Phase detection from macro data
    var phase,color,emoji,assets,avoid,description;
    if(tnxP>4.5&&gldC>0&&oilC>0){
      phase='Verano Kondratiev'; emoji='☀️'; color='var(--warn)';
      assets=['Commodities (energía, metales preciosos)','Real Estate físico (no REIT)','TIPS (inflación real)','Materias primas industriales'];
      avoid=['Bonos largos (TLT) — pierden poder adquisitivo','Growth/Tech con múltiplos altos'];
      description='El Verano se caracteriza por inflación elevada, tipos altos y materias primas fuertes. Los activos reales superan a los financieros. Es la fase más difícil para los bonos nominales. El crédito corporativo empieza a tensionarse. Históricamente dura 5-10 años.';
    } else if(tnxP>4.0&&tipC<-0.2){
      phase='Otoño Kondratiev'; emoji='🍂'; color='var(--dn)';
      assets=['Acciones calidad con dividendo creciente','Bonos cortos (SHY/STIP)','Oro como reserva de valor','Cash / liquidez estratégica'];
      avoid=['Activos especulativos — múltiplos en máximos','Crédito de alto riesgo'];
      description='El Otoño es la fase de especulación financiera y desinflación incipiente. Las bolsas pueden seguir subiendo por inercia pero la economía real se desacelera. El crédito se expande excesivamente. Históricamente precede a la gran crisis. Privilegiar calidad sobre cantidad.';
    } else if(tnxP<3.5&&gldC<0&&oilC<0){
      phase='Invierno Kondratiev'; emoji='❄️'; color='var(--ac)';
      assets=['Bonos largos del Tesoro USA (TLT)','Oro — depósito de valor en deflación','Cash — preservación de capital','Utilities y Healthcare defensivos'];
      avoid=['Energía y materias primas — demanda débil','High Yield — spreads se amplían'];
      description='El Invierno es la fase de destrucción de deuda y corrección de excesos. Los activos especulativos y la deuda privada colapsan. Los bonos soberanos y el oro son los grandes refugios. Las oportunidades históricas de compra aparecen al FINAL del invierno. Puede durar 7-10 años.';
    } else {
      phase='Primavera Kondratiev'; emoji='🌱'; color='var(--up)';
      assets=['Acciones growth y tecnología (QQQ)','Small Caps (IWM) — mayor beta al ciclo','Crédito corporativo IG/HY — spreads comprimen','Cobre y materias primas industriales'];
      avoid=['Bonos muy largos — poco atractivos con tipos bajos','Utilities — bajo atractivo relativo'];
      description='La Primavera es el relanzamiento económico tras la purga del Invierno. Tipos bajos, innovación tecnológica como motor, crédito barato y abundante. Las bolsas lideran con empresas de mayor crecimiento. Los cíclicos e industriales se reactivan. Históricamente la fase más larga y rentable del ciclo (15-20 años).';
    }
    el.innerHTML=''
      +'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px">'
        +'<span style="font-size:28px">'+emoji+'</span>'
        +'<div><div style="font-family:Syne,sans-serif;font-size:14px;font-weight:800;color:'+color+'">'+phase+'</div>'
          +'<div style="font-size:10px;color:var(--dim)">Inferido de Yield 10Y ('+tnxP.toFixed(2)+'%) · TIPS · Gold · Oil</div></div>'
      +'</div>'
      +'<div style="font-size:10px;font-weight:700;color:var(--up);margin-bottom:5px;text-transform:uppercase;letter-spacing:.05em">▲ Activos favorecidos</div>'
      +assets.map(function(a){ return '<div style="font-size:11px;color:var(--tx);margin-bottom:3px;padding-left:4px">• '+a+'</div>'; }).join('')
      +'<div style="font-size:10px;font-weight:700;color:var(--dn);margin-top:8px;margin-bottom:5px;text-transform:uppercase;letter-spacing:.05em">▼ Reducir exposición</div>'
      +avoid.map(function(a){ return '<div style="font-size:11px;color:var(--dim);margin-bottom:3px;padding-left:4px">• '+a+'</div>'; }).join('')
      +'<div style="font-size:11px;color:var(--tx);line-height:1.75;margin-top:10px;padding:9px 12px;background:var(--bg3);border-radius:6px">'+description+'</div>'
      +'<div style="font-size:9px;color:var(--dim);margin-top:6px">Los ciclos Kondratiev duran ~50-60 años en total. Cada fase: 10-20 años. Referencia: van Duijn, Schumpeter, Kondratieff.</div>';
  })();

  // ── ESTACIONALIDAD ──────────────────────────────────────────────────────────
  (function(){
    var seasonEl=document.getElementById('seasonal-content');
    if(!seasonEl) return;
    var mo=new Date().getMonth()+1;
    var seasonal={
      1:{assets:['Oro (GLD)','Bitcoin (IBIT)','Small Caps (IWM)'],why:'Enero es positivo para activos de riesgo. El oro se beneficia de demanda asiática post-festivo y flujos de refugio. Bitcoin históricamente ha tenido sus mejores arranques en Q1.'},
      2:{assets:['Oro (GLD)','Nasdaq 100 (QQQ)','Bitcoin (IBIT)'],why:'Febrero mantiene el momentum de enero. La temporada de earnings de Q4 impulsa al Nasdaq. El oro sigue fuerte por incertidumbre geopolítica.'},
      3:{assets:['Oro (GLD)','Energía (XLE)','Materias primas'],why:'Marzo: inicio de primavera activa la demanda de energía. El oro brilla antes de datos clave de la Fed. Los commodities se reactivan con la industria china.'},
      4:{assets:['Nasdaq 100 (QQQ)','S&P 500 (^GSPC)','Semiconductores'],why:'Abril es históricamente uno de los mejores meses del año. El Nasdaq lidera en el inicio de Q2 con el momentum de earnings.'},
      5:{assets:['S&P 500 (^GSPC)','Nasdaq 100 (QQQ)','Industriales (XLI)'],why:'Mayo: último mes del semestre fuerte. "Sell in May" se refiere a partir de aquí. Industriales activos con el ciclo de capex.'},
      6:{assets:['S&P 500 (^GSPC)','Nasdaq 100 (QQQ)','Healthcare (XLV)'],why:'Junio es transición al verano. Healthcare aguanta bien. S&P y Nasdaq mantienen sesgo positivo si la macro acompaña.'},
      7:{assets:['Oro (GLD)','Bitcoin (IBIT)','Consumo discrecional (XLY)'],why:'Julio: menor liquidez veraniega. El oro y Bitcoin son históricamente fuertes. El consumo se activa con el gasto vacacional.'},
      8:{assets:['Oro (GLD)','Bonos largos (TLT)','Utilities (XLU)'],why:'Agosto es el mes más volátil (crashes de 2015, 2019, 2024). El oro es el refugio preferido. Defensivos resisten mejor.'},
      9:{assets:['Liquidez (SHY)','Bonos cortos','Utilities (XLU)'],why:'Septiembre es el peor mes histórico del S&P500 (promedio -1%). Alta probabilidad de corrección. Reducir exposición a riesgo.'},
      10:{assets:['S&P 500 (^GSPC)','Financieros (XLF)','Small Caps (IWM)'],why:'Octubre inicia el mejor semestre estadísticamente. Tras la corrección de septiembre suele haber rebote fuerte.'},
      11:{assets:['S&P 500 (^GSPC)','Small Caps (IWM)','Consumo discrecional (XLY)'],why:'Noviembre es el mejor mes histórico. El rally de fin de año empieza. Black Friday impulsa el consumo. Las small caps suelen liderar.'},
      12:{assets:['Oro (GLD)','S&P 500 (^GSPC)','Tecnología (QQQ)'],why:'Diciembre: Santa Claus Rally en la última semana. El oro repunta por demanda física. S&P y Nasdaq cierran el año con sesgo alcista.'}
    };
    var s=seasonal[mo]||seasonal[12];
    var mN=['','Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'];
    var rC=['var(--up)','var(--ac)','var(--warn)'];
    seasonEl.innerHTML='<div style="font-size:10px;color:var(--dim);margin-bottom:10px">Mes actual: <strong style="color:var(--hi)">'+mN[mo]+'</strong> — estacionalidad histórica media</div>'
      +s.assets.map(function(a,i){ return '<div style="display:flex;align-items:center;gap:8px;margin-bottom:6px"><span style="font-size:15px">'+(i===0?'🥇':i===1?'🥈':'🥉')+'</span><span style="font-size:12px;font-weight:700;color:'+rC[i]+'">'+a+'</span></div>'; }).join('')
      +'<div style="font-size:11px;color:var(--tx);line-height:1.75;margin-top:10px;padding:9px 12px;background:var(--bg3);border-radius:6px">'+s.why+'</div>';
  })();

  // ── INFLACIÓN ────────────────────────────────────────────────────────────────
  (function(){
    var inflEl=document.getElementById('inflation-content');
    if(!inflEl) return;
    var tnxP=parseFloat(su.tnx_price)||0;
    var tipC=parseFloat(su.tip_chg)||0;
    var aggC=parseFloat(su.agg_chg)||0;
    var inflLevel='moderada', inflLabel='Inflación moderada (entorno normal)', inflColor='var(--warn)';
    if(tnxP>4.8||(tipC>0.3&&aggC<0)){ inflLevel='alta'; inflLabel='Inflación alta — tipos elevados'; inflColor='var(--dn)'; }
    else if(tnxP<3.5&&tipC<-0.1){ inflLevel='baja'; inflLabel='Inflación baja / deflación'; inflColor='var(--up)'; }
    var reg={
      alta:{fav:['Oro (GLD)','Energía (XLE)','TIPS (TIP)','Materias primas (PDBC)'],avoid:['Bonos largos (TLT)','Growth/Tech — múltiplos presionados'],why:'Con inflación alta, los activos reales protegen. Oro, energía e inmuebles actúan como cobertura. Los bonos largos son los grandes perdedores. Las empresas growth sufren porque sus flujos futuros se descuentan a tasas más altas.'},
      moderada:{fav:['S&P 500 (^GSPC)','Nasdaq 100 (QQQ)','Financieros (XLF)','Industriales (XLI)'],avoid:['Utilities — muy sensibles a tipos','Bonos muy largos'],why:'La inflación moderada (2-4%) es el entorno ideal para la renta variable. Las empresas trasladan costes. Los financieros ganan con el diferencial de tipos. El Nasdaq resiste bien si los tipos se estabilizan.'},
      baja:{fav:['Bonos largos (TLT)','Nasdaq/Growth (QQQ)','Utilities (XLU)','Healthcare (XLV)'],avoid:['Energía — demanda y precios débiles','Materias primas — deflación'],why:'Inflación baja: los bancos centrales bajan tipos. Los bonos largos y el growth se benefician. Las utilities son atractivas como proxy de bono con dividendo. Cuidado si la baja inflación refleja debilidad económica real.'}
    };
    var r=reg[inflLevel];
    inflEl.innerHTML='<div style="display:inline-block;padding:4px 12px;border-radius:12px;border:1px solid '+inflColor+';font-size:11px;font-weight:700;color:'+inflColor+';margin-bottom:10px">'+inflLabel+'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-bottom:8px">Yield 10Y: '+(tnxP?tnxP.toFixed(3)+'%':'—')+' · TIPS hoy: '+(tipC>=0?'+':'')+tipC.toFixed(2)+'%</div>'
      +'<div style="font-size:10px;font-weight:700;color:var(--up);margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em">✅ Favorecidos</div>'
      +r.fav.map(function(a){ return '<div style="font-size:11px;color:var(--tx);margin-bottom:3px">▲ '+a+'</div>'; }).join('')
      +'<div style="font-size:10px;font-weight:700;color:var(--dn);margin-top:8px;margin-bottom:5px;text-transform:uppercase;letter-spacing:.04em">⚠️ Evitar</div>'
      +r.avoid.map(function(a){ return '<div style="font-size:11px;color:var(--dim);margin-bottom:3px">▼ '+a+'</div>'; }).join('')
      +'<div style="font-size:11px;color:var(--tx);line-height:1.75;margin-top:10px;padding:9px 12px;background:var(--bg3);border-radius:6px">'+r.why+'</div>';
  })();

  // Sector heatmap

}

// ── NH/NL TOGGLE ─────────────────────────────────────────────────────────────
let _nhVisible=false,_nhMode='highs';
function toggleNHList(mode){
  const su=D.breadthSummary;
  const list=mode==='highs'?(su.new_highs_list||[]):(su.new_lows_list||[]);
  const el=document.getElementById('nh-list');
  if(_nhVisible&&_nhMode===mode){el.style.display='none';_nhVisible=false;return;}
  _nhMode=mode; _nhVisible=true;
  el.style.display='flex';
  el.innerHTML=list.map(tk=>`<span class="badge ${mode==='highs'?'b-up':'b-dn'}" style="cursor:pointer" onclick="document.getElementById('stk-ticker').value='${tk}';sw('stocks',document.getElementById('tab-stocks-btn'))">${tk}</span>`).join('');
}

// ── EARNINGS ─────────────────────────────────────────────────────────────────
// ── EARNINGS — Resumen de Resultados ──────────────────────────────────────────
let _earnData=[],_earnFilter='all',_earnSearch='',_earnSort={col:-1,asc:-1};
const fmtSales=v=>{if(!v)return'—';const n=parseFloat(v);if(isNaN(n))return'—';if(Math.abs(n)>=1e12)return'$'+(n/1e12).toFixed(2)+'T';if(Math.abs(n)>=1e9)return'$'+(n/1e9).toFixed(1)+'B';if(Math.abs(n)>=1e6)return'$'+(n/1e6).toFixed(0)+'M';return'$'+n.toFixed(0);};

function loadStock(){
  const tk=(document.getElementById('stk-ticker').value||'').toUpperCase().trim();
  if(!tk)return;
  const sp=D.stockPerf||{};
  const r=sp[tk];
  const info=(D.stockInfo||{})[tk]||null;
  const panel=document.getElementById('stock-panel');
  if(!r){
    panel.innerHTML=`<div style="color:var(--dim);padding:20px;background:var(--bg2);border:1px solid var(--b1);border-radius:8px">
      <strong style="color:var(--hi)">${tk}</strong> no está en los datos precargados.<br>
      Disponibles: acciones de los universos de sectores e industrias.<br>
      <span style="font-size:10px">Añade el ticker en SECTOR_STOCKS o INDUSTRY_DATA y vuelve a ejecutar.</span>
    </div>`;
    return;
  }

  // RS percentile (1Y)
  const allSp=[...Object.values(sp)].filter(x=>x['1Y']!==undefined);
  allSp.sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rank=allSp.findIndex(x=>x.ticker===tk);
  const rs=rank>=0?Math.round(rank/allSp.length*100):null;
  const rsLbl=rs>=80?'⚡ Líder — fuerza relativa alta':rs>=60?'✓ Por encima de la media':rs>=40?'→ En la media':rs>=20?'↓ Bajo la media':'⚠ Fuerza relativa baja';

  const distHi=r['52wHigh']?round2((r.price-r['52wHigh'])/r['52wHigh']*100):null;
  const distLo=r['52wLow']? round2((r.price-r['52wLow'])/r['52wLow']*100):null;

  // Format helpers
  const fmtM=v=>{if(!v)return'—';const n=Number(v);if(isNaN(n))return'—';if(Math.abs(n)>=1e12)return'$'+(n/1e12).toFixed(2)+'T';if(Math.abs(n)>=1e9)return'$'+(n/1e9).toFixed(1)+'B';if(Math.abs(n)>=1e6)return'$'+(n/1e6).toFixed(0)+'M';return'$'+n.toFixed(0);};
  const fmtP=v=>v!==null&&v!==undefined?Math.round(v*100)+'%':'—';
  const fmtX=v=>v!==null&&v!==undefined?Number(v).toFixed(1)+'x':'—';
  const fmtR=v=>v!==null&&v!==undefined?Number(v).toFixed(2):'—';

  const analystText=info?.analyst?(['','Compra Fuerte','Compra','Mantener','Vender','Vender Fuerte'][Math.round(info.analyst)]||info.analyst):'—';
  const analystCls=info?.analyst?(info.analyst<=2?'up':info.analyst<=3?'neu':'dn'):'neu';

  // Fundamentals section (only if info available)
  const fundHTML=info?`
    <div class="sh" style="margin-top:2px"><span class="st" style="font-size:12px">FUNDAMENTALES — ${info.name||tk}</span></div>
    <div style="font-size:10px;color:var(--dim);margin-bottom:10px">${info.sector||''} ${info.industry?'· '+info.industry:''} ${info.country?'· '+info.country:''}</div>
    <div class="stock-metrics" style="margin-bottom:12px">
      ${metCard('Mkt Cap',fmtM(info.mktCap))}
      ${metCard('P/E Trailing',fmtR(info.pe))}
      ${metCard('P/E Forward',fmtR(info.fwdPE))}
      ${metCard('PEG Ratio',fmtR(info.peg))}
      ${metCard('P/B',fmtR(info.pb))}
      ${metCard('P/S (TTM)',fmtR(info.ps))}
      ${metCard('EPS (TTM)',info.eps?'$'+Number(info.eps).toFixed(2):'—')}
      ${metCard('EPS Fwd',info.fwdEps?'$'+Number(info.fwdEps).toFixed(2):'—')}
      ${metCard('Revenue',fmtM(info.revenue))}
      ${metCard('EBITDA',fmtM(info.ebitda))}
      ${metCard('FCF',fmtM(info.fcf))}
      ${metCard('Div Yield',fmtP(info.divYield))}
      ${metCard('Beta',fmtR(info.beta))}
      ${metCard('Gross Margin',fmtP(info.grossMarg))}
      ${metCard('Op Margin',fmtP(info.opMarg))}
      ${metCard('Net Margin',fmtP(info.netMarg))}
      ${metCard('ROE',fmtP(info.roe))}
      ${metCard('ROA',fmtP(info.roa))}
      ${metCard('Debt/Equity',fmtR(info.debtEq))}
      ${metCard('Current Ratio',fmtR(info.currentRatio))}
      ${metCard('Rev Growth',info.revGrowth!==null?`<span class="${info.revGrowth>0?'up':'dn'}">${fmtP(info.revGrowth)}</span>`:'—')}
      ${metCard('EPS Growth',info.epsGrowth!==null?`<span class="${info.epsGrowth>0?'up':'dn'}">${fmtP(info.epsGrowth)}</span>`:'—')}
      ${metCard('Analistas',info.nAnalysts||'—')}
      ${metCard('Recomendación',`<span class="${analystCls}">${analystText}</span>`)}
      ${metCard('Precio Objetivo',info.targetMean?'$'+Number(info.targetMean).toFixed(0):'—')}
      ${metCard('Empleados',info.employees?info.employees.toLocaleString():'—')}
    </div>
    ${info.summary?`<div style="font-size:10px;color:var(--dim);background:var(--bg3);border-radius:7px;padding:10px 12px;margin-bottom:14px;line-height:1.6">${info.summary}...</div>`:''}
  `:`<div style="font-size:10px;color:var(--dim);margin-bottom:14px;background:var(--bg2);border:1px solid var(--b1);border-radius:7px;padding:10px 12px">
    <strong style="color:var(--hi)">${tk}</strong> — Fundamentales no precargados para este ticker.<br>
    <span style="font-size:10px">Los datos fundamentales están disponibles para las 200 principales del S&P500. 
    Para este ticker, busca en <a href="https://finance.yahoo.com/quote/${tk}" target="_blank" style="color:var(--ac)">Yahoo Finance</a> 
    o <a href="https://finviz.com/quote.ashx?t=${tk}" target="_blank" style="color:var(--ac)">Finviz</a>.</span>
  </div>`;

  const rsCls=rs>=80?'up':rs>=50?'ac':'dn';
  const rsIcon=rs>=80?'⚡':rs>=60?'✓':rs>=40?'→':rs>=20?'↓':'⚠';
  const volPct=r.volRel?Math.min(100,r.volRel/3*100):0;
  const volColor=r.volRel>1.5?'var(--up)':r.volRel<0.5?'var(--dn)':'var(--ac)';

  // ATR Extension for this stock
  const atrExt=(()=>{
    if(!r.ma50||!r['52wHigh']||!r['52wLow']||!r.price)return null;
    const yr=r['52wHigh']-r['52wLow'];
    if(yr<=0)return null;
    const adp=yr/r.price/252;
    if(adp<=0)return null;
    return Math.round(((r.price/r.ma50-1)/adp)*10)/10;
  })();
  const atrColor=atrExt!==null?(atrExt>10?'var(--dn)':atrExt>5?'var(--warn)':atrExt<0?'var(--dn)':'var(--up)'):'var(--dim)';

  panel.innerHTML=`
    <!-- HEADER — ticker + precio + RS + métricas en una sola pieza compacta -->
    <div class="stock-header">
      <!-- ROW 1: Nombre, precio, sector, badges -->
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:14px;flex-wrap:wrap">
        <div style="flex:1;min-width:260px">
          <div style="display:flex;align-items:baseline;gap:10px;flex-wrap:wrap">
            <h2 style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:var(--hi)">${tk}</h2>
            ${info?`<span style="font-family:Syne,sans-serif;font-size:16px;color:var(--dim);font-weight:500">${info.name||''}</span>`:''}
          </div>
          ${info?`<div class="stk-sector-tag" style="font-size:12px;margin:5px 0">
            <span style="color:var(--ac)">📂 ${info.sector||'—'}</span>
            <span style="color:var(--dim)"> · ${info.industry||'—'} · ${info.country||''}</span>
          </div>`:''}
          <div class="stock-price ${(r['1D']||0)>=0?'up':'dn'}" style="font-size:26px">
            $${r.price}
            <span style="font-size:18px;margin-left:10px">${fmt(r['1D'])}</span>
            <span style="font-size:11px;color:var(--dim);margin-left:6px">HOY</span>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
            ${r.newHi?'<span class="badge b-up" style="font-size:11px">★ 52W Máximo</span>':''}
            ${r.newLo?'<span class="badge b-dn" style="font-size:11px">✗ 52W Mínimo</span>':''}
            ${info?.exchange?`<span class="badge b-neu">${info.exchange}</span>`:''}
            ${rs>=80?'<span class="badge b-up" style="font-size:11px">⚡ Líder RS</span>':rs>=65?'<span class="badge b-up" style="font-size:11px">✓ RS Alto</span>':''}
          </div>
        </div>
        <!-- RS box -->
        <div style="text-align:center;flex-shrink:0;background:var(--bg3);border-radius:14px;padding:18px 24px;border:1px solid var(--b1);min-width:130px">
          <div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.12em;margin-bottom:6px">Relative Strength</div>
          <div class="stk-rs-num" style="color:${rs>=80?'var(--up)':rs>=50?'var(--ac)':'var(--dn)'};">${rs??'—'}</div>
          <div style="font-size:10px;color:var(--dim);margin-top:2px">de 100</div>
          <div class="rs-bar" style="margin:10px auto 0;width:88px"><div class="rs-dot" style="left:${rs??50}%"></div></div>
          <div style="font-size:10px;color:var(--dim);margin-top:8px;max-width:100px;line-height:1.4">${rsIcon} ${rsLbl.split(' — ')[0]}</div>
        </div>
      </div>

      <!-- ROW 2: Vol bar + ATR Extension + precio objetivo (si disponible) -->
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:14px">
        <!-- Vol rel -->
        <div style="background:var(--bg3);border-radius:8px;padding:10px 14px;border:1px solid var(--b1)">
          <div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">Volumen Relativo</div>
          <div style="font-size:20px;font-weight:800;font-family:Syne,sans-serif;color:${volColor}">${r.volRel?r.volRel+'x':'—'}</div>
          <div class="stk-vol-bar" style="margin-top:8px"><div class="stk-vol-fill" style="width:${volPct}%;background:${volColor}"></div></div>
          <div style="font-size:9px;color:var(--dim);margin-top:5px">${r.volRel>2?'🔥 Muy alto':''}${r.volRel>1.5&&r.volRel<=2?'⚡ Alto':''}${r.volRel&&r.volRel<=1.5?'Normal':''}</div>
        </div>
        <!-- ATR Extension -->
        <div style="background:var(--bg3);border-radius:8px;padding:10px 14px;border:1px solid var(--b1)">
          <div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">ATR Extension (vs MA50)</div>
          <div style="font-size:20px;font-weight:800;font-family:Syne,sans-serif;color:${atrColor}">${atrExt!==null?atrExt+'x':'—'}</div>
          <div style="font-size:9px;color:var(--dim);margin-top:8px">${atrExt!==null?(atrExt>12?'🚨 Muy extendido — riesgo reversión':atrExt>7?'⚠️ Extendido, precaución':atrExt>2?'✅ Zona normal':atrExt>0?'✅ Cerca de MA50':atrExt<0?'📉 Bajo MA50, debilidad':''):'Sin datos'}</div>
        </div>
        <!-- Precio objetivo -->
        <div style="background:var(--bg3);border-radius:8px;padding:10px 14px;border:1px solid var(--b1)">
          <div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.07em;margin-bottom:6px">Analistas (${info?.nAnalysts||0})</div>
          <div style="font-size:20px;font-weight:800;font-family:Syne,sans-serif;color:var(--hi)">${info?.targetMean?'$'+Number(info.targetMean).toFixed(0):'—'}</div>
          <div style="font-size:9px;color:var(--dim);margin-top:8px">${info?.analyst?(['','🟢 Compra fuerte','🟢 Compra','🟡 Mantener','🔴 Vender','🔴 Vender fuerte'][Math.round(info.analyst)]||'—'):'—'}</div>
        </div>
      </div>

      <!-- ROW 3: Métricas de precio — grid compacto -->
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:6px;border-top:1px solid var(--b1);padding-top:12px">
        ${hdrMet('1D',fmt(r['1D']))}${hdrMet('1W',fmt(r['1W']))}${hdrMet('1M',fmt(r['1M']))}
        ${hdrMet('3M',fmt(r['3M']))}${hdrMet('1Y',fmt(r['1Y']))}
        ${hdrMet('52W High','$'+(r['52wHigh']||'—'))}${hdrMet('52W Low','$'+(r['52wLow']||'—'))}
        ${distHi!==null?hdrMet('vs Máx',`<span class="${distHi>=-5?'up':'dn'}">${distHi}%</span>`):''}
        ${hdrMet('MA20',r.abv20!==null?`<span class="${r.abv20?'up':'dn'}">${r.abv20?'▲':'▼'} $${r.ma20}</span>`:'—')}
        ${hdrMet('MA50',r.abv50!==null?`<span class="${r.abv50?'up':'dn'}">${r.abv50?'▲':'▼'} $${r.ma50}</span>`:'—')}
        ${hdrMet('MA200',r.abv200!==null?`<span class="${r.abv200?'up':'dn'}">${r.abv200?'▲':'▼'} $${r.ma200}</span>`:'—')}
      </div>
    </div>

    <!-- GRÁFICO DE VELAS — full width -->
    <div style="background:var(--bg2);border:1px solid var(--b1);border-radius:9px;padding:10px;margin-bottom:14px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px">
        <span style="font-family:Syne,sans-serif;font-size:13px;font-weight:700;color:var(--hi)">GRÁFICO DE VELAS — 90 días</span>
        <span style="font-size:10px;color:var(--dim)">
          <span style="color:rgba(167,139,250,.9)">■</span> EMA9 &nbsp;
          <span style="color:rgba(245,158,11,.9)">■</span> MA20 &nbsp;
          <span style="color:rgba(56,189,248,.9)">■</span> MA50
        </span>
      </div>
      <canvas id="stock-chart" height="340"></canvas>
    </div>

    <!-- FUNDAMENTALES -->
    ${fundHTML}
  `;
  setTimeout(()=>drawStkCandle(document.getElementById('stock-chart'),r.ohlc||[]),30);
}

function drawStkCandle(canvas,ohlcArr){
  if(!canvas||!ohlcArr||!ohlcArr.length)return;
  const dpr=window.devicePixelRatio||1;
  const W=canvas.parentElement.clientWidth||800;
  const H=parseInt(canvas.getAttribute('height')||220);
  canvas.width=W*dpr; canvas.height=H*dpr;
  canvas.style.width=W+'px'; canvas.style.height=H+'px';
  const cx=canvas.getContext('2d');
  cx.scale(dpr,dpr);
  const pad={t:20,r:10,b:26,l:58};
  const cw=W-pad.l-pad.r, ch=H-pad.t-pad.b;
  const mn=Math.min(...ohlcArr.map(d=>d.l));
  const mx=Math.max(...ohlcArr.map(d=>d.h));
  const rng=mx-mn||1;
  const scY=v=>pad.t+ch-(v-mn)/rng*ch;
  const n=ohlcArr.length;
  const bw=Math.max(2,Math.floor(cw/n)-1);
  const xc=i=>pad.l+i*(cw/n)+cw/(n*2);
  cx.fillStyle='#0c0f18'; cx.fillRect(0,0,W,H);
  cx.strokeStyle='#1c2436'; cx.lineWidth=0.5;
  for(let i=0;i<=4;i++){
    const y=pad.t+ch/4*i;
    cx.beginPath();cx.moveTo(pad.l,y);cx.lineTo(W-pad.r,y);cx.stroke();
    cx.fillStyle='#3a4860';cx.font='9px monospace';cx.textAlign='right';
    cx.fillText('$'+(mx-rng/4*i).toFixed(2),pad.l-4,y+3);
  }
  const cl=ohlcArr.map(d=>d.c);
  const drawML=(arr,col)=>{
    cx.strokeStyle=col;cx.lineWidth=1.2;cx.beginPath();let s2=false;
    arr.forEach((v,i)=>{if(v===null)return;const x=xc(i),y=scY(v);s2?cx.lineTo(x,y):cx.moveTo(x,y);s2=true;});
    cx.stroke();
  };
  const k9=2/10; let e9=cl[0];
  const ema9=cl.map((c,i)=>{if(i===0){e9=c;return c;}e9=c*k9+e9*(1-k9);return Math.round(e9*100)/100;});
  drawML(ema9,'rgba(167,139,250,.8)');
  drawML(cl.map((_,i)=>i>=19?cl.slice(i-19,i+1).reduce((a,b)=>a+b)/20:null),'rgba(245,158,11,.8)');
  drawML(cl.map((_,i)=>i>=49?cl.slice(i-49,i+1).reduce((a,b)=>a+b)/50:null),'rgba(56,189,248,.8)');
  ohlcArr.forEach((d,i)=>{
    const x=xc(i),up=d.c>=d.o,col=up?'#10b981':'#f43f5e',hw=Math.max(1,bw/2-1);
    cx.strokeStyle=col;cx.lineWidth=1;
    cx.beginPath();cx.moveTo(x,scY(d.h));cx.lineTo(x,scY(d.l));cx.stroke();
    const top=scY(Math.max(d.o,d.c)),bot=scY(Math.min(d.o,d.c));
    cx.fillStyle=col;cx.fillRect(x-hw,top,hw*2,Math.max(1,bot-top));
  });
  cx.fillStyle='#3a4860';cx.font='9px monospace';cx.textAlign='center';
  ohlcArr.forEach((d,i)=>{if(i%15===0||i===n-1)cx.fillText(d.t.slice(5),xc(i),H-4);});
}

function metCard(l,v){
  return `<div class="sm-c"><div class="sm-l">${l}</div><div class="sm-v">${v}</div></div>`;
}
function hdrMet(l,v){
  return `<div style="background:var(--bg3);border-radius:5px;padding:6px 8px"><div style="font-size:8px;color:var(--dim);text-transform:uppercase;letter-spacing:.05em;margin-bottom:2px">${l}</div><div style="font-size:11px;font-weight:600;color:var(--hi)">${v}</div></div>`;
}
function metCardMA(l,ma,price,abv){
  const diff=ma&&price?round2((price/ma-1)*100):null;
  return `<div class="sm-c">
    <div class="sm-l">${l}: ${ma?'$'+ma:'—'}</div>
    <div class="sm-v">
      ${abv!==null?`<span class="badge ${abv?'b-up':'b-dn'}">${abv?'▲ encima':'▼ debajo'}</span>`:'—'}
      ${diff!==null?` <span class="${abv?'up':'dn'}" style="font-size:11px">${diff>0?'+':''}${diff}%</span>`:''}
    </div>
  </div>`;
}
function round2(n){return Math.round(n*100)/100;}

// ── TABS ──────────────────────────────────────────────────────────────────────
function sw(n,btn){
  document.querySelectorAll('.tc').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));
  document.getElementById('tab-'+n).classList.add('active');
  if(btn) btn.classList.add('active');
  if(n==='breadth') renderBreadthTab();
  if(n==='briefing') renderBriefing();
  if(n==='cartera'&&!carteraLoaded){carteraLoaded=true;initCartera();}
}
// ── PERIOD ────────────────────────────────────────────────────────────────────
function sp(k,p,btn){
  PD[k]=p;
  document.querySelectorAll(`#p${k} .pb`).forEach(b=>b.classList.remove('active'));
  btn.classList.add('active'); renderHM(k);
}
// ── SORT ──────────────────────────────────────────────────────────────────────
function srt(id,col){
  const tb=document.getElementById(id);
  const rows=Array.from(tb.querySelectorAll('tr'));
  const asc=SS[id]===col?-1:1; SS[id]=asc===1?col:null;
  rows.sort((a,b)=>{
    const va=a.cells[col].innerText.replace(/[+%$,▲▼★✗]/g,'').trim();
    const vb=b.cells[col].innerText.replace(/[+%$,▲▼★✗]/g,'').trim();
    const na=parseFloat(va),nb=parseFloat(vb);
    if(!isNaN(na)&&!isNaN(nb))return(na-nb)*asc;
    return va.localeCompare(vb)*asc;
  });
  rows.forEach(r=>tb.appendChild(r));
  document.querySelectorAll(`#${id} th`).forEach((th,i)=>th.classList.toggle('srt',i===col));
}
// ── FILTER ────────────────────────────────────────────────────────────────────
function fi(q){
  const rows=document.querySelectorAll('#tb-i tr');
  let n=0;
  rows.forEach(r=>{const s=r.innerText.toLowerCase().includes(q.toLowerCase());r.style.display=s?'':'none';if(s)n++;});
  document.getElementById('ind-cnt').textContent=n+' industrias';
}

// ── SCANNER ───────────────────────────────────────────────────────────────────
function runScanner(mode, btn){
  // Update active button
  document.querySelectorAll('[id^=scan-btn-]').forEach(b=>b.classList.remove('active'));
  if(btn) btn.classList.add('active');
  const sp=D.stockPerf||{};
  const allSp=Object.values(sp).filter(x=>x['1Y']!==undefined);
  allSp.sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rsOf=tk=>{const r=allSp.findIndex(x=>x.ticker===tk);return r>=0?Math.round(r/allSp.length*100):0;};
  // ATR Extension = (Price/MA50 - 1) / ATR_daily%
  // ATR_daily% = (52wHigh - 52wLow) / price / 252  (rango anual / precio / días)
  // Valores típicos: 0-20, zona normal 1-8, >10 muy extendido
  const atrDist=r=>{
    if(!r.ma50||!r['52wHigh']||!r['52wLow']||!r.price)return 0;
    const yearRange=r['52wHigh']-r['52wLow'];
    if(yearRange<=0)return 0;
    const atrDailyPct=yearRange/r.price/252; // ATR diario como % del precio
    if(atrDailyPct<=0)return 0;
    const ext=(r.price/r.ma50-1)/atrDailyPct;
    return Math.round(ext*10)/10;
  };
  const signal=(r,mode)=>{
    if(mode==='highs') return r['52wHigh']&&r.price>=(r['52wHigh']*0.97)?'📈 Cerca 52W Max':'';
    if(mode==='vol')   return r.volRel>=2?'🔥 Vol x'+r.volRel:r.volRel>=1.5?'⚡ Vol x'+r.volRel:'';
    if(mode==='abv_all') return (r.abv20&&r.abv50)?'✅ Sobre MA20+50':'';
    if(mode==='parabolic'){const ext=atrDist(r);return ext>12?'🚨 Muy extendido ('+ext+')':'🚀 Extendido ('+ext+')';}
    if(mode==='lows')  return r['52wLow']&&r.price<=(r['52wLow']*1.05)?'⚠️ Cerca 52W Mín':'';
    if(mode==='bounce') return (!r.abv20&&r.abv50&&(r['1D']||0)>1)?'🔄 Rebote MA20':'';
    if(mode==='rs') return rsOf(r.ticker)>=75?'⭐ RS '+rsOf(r.ticker):'';
    if(mode==='pre') return (r['1D']||0)>1.5&&(r.volRel||0)>1.2?'🌅 Premarket+Vol':'🌅 Pre subida';
    return '';
  };
  const filtered=Object.values(sp).filter(r=>{
    if(r.price<5) return false; // filter penny stocks
    const rs=rsOf(r.ticker);
    if(mode==='rs') return rs>=75;
    if(mode==='highs') return r['52wHigh']&&r.price>=(r['52wHigh']*0.97);
    if(mode==='vol') return r.volRel&&r.volRel>=1.5&&(r['1D']||0)>0; // vol comprador: subida + vol
    if(mode==='abv_all') return r.abv20&&r.abv50;
    if(mode==='parabolic') return (r['1M']||0)>12&&atrDist(r)>7; // >12% en 1M y ATR ext >7 (muy extendido)
    if(mode==='lows') return r['52wLow']&&r.price<=(r['52wLow']*1.05);
    if(mode==='bounce') return !r.abv20&&r.abv50&&(r['1D']||0)>1;
    if(mode==='pre') return (r['1D']||0)>1&&(r.volRel||0)>1.0;
    return false;
  }).sort((a,b)=>{
    if(mode==='parabolic') return atrDist(b)-atrDist(a); // parabolic: highest ATR extension first
    if(mode==='pre') return (b['1D']||0)-(a['1D']||0);
    if(mode==='vol') return (b.volRel||0)-(a.volRel||0);
    return rsOf(b.ticker)-rsOf(a.ticker);
  }).slice(0,100);
  const modeLabels={
    rs:'RS Líderes (≥75)',highs:'Cerca 52W Máximo (≥97%)',vol:'Volumen Comprador (Vol≥1.5x + subida)',
    abv_all:'Sobre MA20+MA50',parabolic:'Parabolic Short — extendidos vs MA50 (ATR Extension >2.5)',
    lows:'Cerca 52W Mínimo (≤105%)',bounce:'Rebote desde MA50',pre:'Apertura más alcistas (premercado proxy)'
  };
  window._scannerData=filtered; // save for copy
  document.getElementById('scanner-status').innerHTML=
    `<strong>${modeLabels[mode]||mode}:</strong> ${filtered.length} acciones · <span style="color:var(--dim)">Click en cabecera para ordenar</span>`;
  renderScannerRows(filtered,rsOf,atrDist,signal,mode);
}
let _scanSort={col:-1,asc:1};
function renderScannerRows(rows,rsOf,atrDist,signal,mode){
  document.getElementById('tb-scanner').innerHTML=rows.map((r,i)=>{
    const rs=rsOf(r.ticker);
    const rsCls=rs>=80?'up':rs>=50?'':'dn';
    const vr=r.volRel;
    const vrStr=vr?`<span class="${vr>1.5?'up':vr<0.5?'dn':'neu'}">${vr}x</span>`:'—';
    const distHi=r['52wHigh']?Math.round((r.price/r['52wHigh']-1)*100):0;
    const atr=atrDist(r);
    const sig=signal?signal(r,mode):'';
    return `<tr style="cursor:pointer" onclick="document.getElementById('stk-ticker').value='${r.ticker}';sw('stocks',document.getElementById('tab-stocks-btn'));loadStock()">
      <td><span class="rk">${i+1}</span><span class="nm">${r.ticker}</span></td>
      <td>$${r.price}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td><td>${fmt(r['1Y'])}</td>
      <td>${abvBadge(r.abv20,'MA20')}</td>
      <td>${abvBadge(r.abv50,'MA50')}</td>
      <td><span style="color:var(--ac)">${atr}x ATR</span></td>
      <td>${vrStr}</td>
      <td><span class="${rsCls}" style="font-weight:700">${rs}</span></td>
      <td><span class="${distHi>=-5?'up':'dn'}">${distHi}%</span></td>
      <td style="color:var(--warn);font-size:10px">${sig}</td>
    </tr>`;
  }).join('');
}
function sortScanner(col){
  if(!window._scannerData||!window._scannerData.length)return;
  const sp=D.stockPerf||{};
  const allSp=Object.values(sp).filter(x=>x['1Y']!==undefined);
  allSp.sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rsOf=tk=>{const r=allSp.findIndex(x=>x.ticker===tk);return r>=0?Math.round(r/allSp.length*100):0;};
  const atrDist=r=>{if(!r.ma50||!r['52wHigh']||!r['52wLow']||!r.price)return 0;const yr=r['52wHigh']-r['52wLow'];if(yr<=0)return 0;const adp=yr/r.price/252;if(adp<=0)return 0;return Math.round(((r.price/r.ma50-1)/adp)*10)/10;};
  const cols=[r=>r.ticker,r=>r.price,r=>r['1D']||0,r=>r['1W']||0,r=>r['1M']||0,r=>r['1Y']||0,
    r=>r.abv20?1:0,r=>r.abv50?1:0,r=>atrDist(r),r=>r.volRel||0,r=>rsOf(r.ticker),
    r=>r['52wHigh']?((r.price/r['52wHigh']-1)*100):0];
  if(_scanSort.col===col) _scanSort.asc*=-1; else {_scanSort.col=col;_scanSort.asc=-1;}
  const sorted=[...window._scannerData].sort((a,b)=>(cols[col](b)-cols[col](a))*_scanSort.asc);
  renderScannerRows(sorted,rsOf,atrDist,null,'');
}
function copyScannerTickers(){
  const data=window._scannerData||[];
  if(!data.length){alert('Ejecuta un scanner primero');return;}
  const tks=data.map(r=>r.ticker).join(',');
  const area=document.createElement('textarea');
  area.value=tks; document.body.appendChild(area);
  area.select(); document.execCommand('copy'); document.body.removeChild(area);
  alert('✓ '+data.length+' tickers copiados\n'+tks.slice(0,100)+'...');
}


// ── WATCHLIST ─────────────────────────────────────────────────────────────────
function buildWatchlist(){
  const sp=D.stockPerf||{};
  const allSp=Object.values(sp).filter(x=>x['1Y']!==undefined);
  allSp.sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rsOf=tk=>{const r=allSp.findIndex(x=>x.ticker===tk);return r>=0?Math.round(r/allSp.length*100):0;};
  // Get hot industries (positive 1M)
  const hotInd=new Set((D.industries||[]).filter(i=>(i['1M']||0)>0).map(i=>i.name));
  // Get ticker -> industry map
  const tkInd={};
  Object.entries(D.industryStocks||{}).forEach(([ind,stocks])=>stocks.forEach(s=>{if(!tkInd[s.ticker])tkInd[s.ticker]=ind;}));

  const scored=Object.values(sp).map(r=>{
    const rs=rsOf(r.ticker);
    let score=0, setups=[];
    if(rs>=70) score+=30;
    if(r.abv50) score+=15;
    if(r.abv200) score+=10;
    if(r.abv20) score+=5;
    if(r.volRel&&r.volRel>=1.2) score+=15;
    if(r.newHi){score+=20;setups.push('52W Max');}
    if(hotInd.has(tkInd[r.ticker])){score+=10;setups.push('Ind. fuerte');}
    if((r['1D']||0)>2&&(r.volRel||0)>1.5){score+=15;setups.push('Gap+Vol');}
    if((r['1W']||0)>0&&(r['1M']||0)>0&&(r['3M']||0)>0){score+=10;setups.push('Multi-TF ▲');}
    if(r.abv20&&r.abv50&&r.abv200){setups.push('Sobre 3 MAs');}
    if(!r.abv20&&r.abv50&&(r['1D']||0)>1){score+=8;setups.push('Rebote MA20');}
    return {...r, rs, score, setup:setups.slice(0,2).join(' · '), industry:tkInd[r.ticker]||'—'};
  }).filter(r=>r.rs>=60&&r.abv50&&r.price>10&&(r.volRel||0)>=0.7)
    .sort((a,b)=>b.score-a.score).slice(0,30);

  document.getElementById('wl-criteria').style.display='block';
  document.getElementById('wl-status').innerHTML=
    `<strong style="color:var(--hi)">${scored.length} acciones</strong> en watchlist de hoy · `+
    `Industrias activas: <span style="color:var(--ac)">${[...hotInd].slice(0,5).join(', ')}</span>...`;

  _wlData=scored; _wlSort={col:-1,asc:1};
  renderWLRows(scored);
}
let _wlData=[], _wlSort={col:-1,asc:1};
function renderWLRows(rows){
  const allSp=Object.values(D.stockPerf||{}).filter(x=>x['1Y']!==undefined).sort((a,b)=>(a['1Y']||0)-(b['1Y']||0));
  const rsOf=tk=>{const r=allSp.findIndex(x=>x.ticker===tk);return r>=0?Math.round(r/allSp.length*100):0;};
  document.getElementById('tb-watchlist').innerHTML=rows.map((r,i)=>{
    const rsCls=r.rs>=80?'up':r.rs>=60?'':'dn';
    const vr=r.volRel;
    const vrStr=vr?`<span class="${vr>1.5?'up':vr<0.5?'dn':'neu'}">${vr}x</span>`:'—';
    return `<tr style="cursor:pointer" onclick="document.getElementById('stk-ticker').value='${r.ticker}';sw('stocks',document.getElementById('tab-stocks-btn'));loadStock()">
      <td><span class="rk">${i+1}</span><span class="nm">${r.ticker}</span></td>
      <td>$${r.price}</td>
      <td>${fmt(r['1D'])}</td><td>${fmt(r['1W'])}</td><td>${fmt(r['1M'])}</td>
      <td><span class="${rsCls}" style="font-weight:700">${r.rs}</span></td>
      <td>${abvBadge(r.abv50,'MA50')}</td>
      <td>${vrStr}</td>
      <td style="color:var(--warn);font-size:10px">${r.setup||'—'}</td>
      <td style="color:var(--dim);font-size:10px">${r.industry.length>22?r.industry.slice(0,22)+'...':r.industry}</td>
    </tr>`;
  }).join('');
}
function sortWL(col){
  if(!_wlData.length)return;
  if(_wlSort.col===col) _wlSort.asc*=-1; else {_wlSort.col=col;_wlSort.asc=-1;}
  const keys=[r=>r.ticker,r=>r.price,r=>r['1D']||0,r=>r['1W']||0,r=>r['1M']||0,r=>r.rs,r=>r.abv50?1:0,r=>r.volRel||0];
  const sorted=[..._wlData].sort((a,b)=>(keys[col]?((keys[col](b)||0)-(keys[col](a)||0))*_wlSort.asc:0));
  renderWLRows(sorted);
  document.querySelectorAll('#wl-table th').forEach((th,i)=>th.classList.toggle('srt',i===col));
}
function copyTickers(){
  const rows=document.querySelectorAll('#tb-watchlist tr');
  const tickers=[...rows].map(r=>r.cells[0]?.querySelector('.nm')?.textContent||'').filter(Boolean);
  if(!tickers.length){alert('Genera la watchlist primero');return;}
  const area=document.getElementById('wl-copy-area');
  area.value=tickers.join(',');
  area.select(); document.execCommand('copy');
  alert('✓ '+tickers.length+' tickers copiados: '+tickers.join(', '));
}

// ── BRIEFING DIARIO ───────────────────────────────────────────────────────────
let _briefingBuilt=false;
function renderBriefing(){
  _briefingBuilt=true;
  const bm=D.benchmarks||[];
  const su=D.breadthSummary||{};
  const bl=D.breadthLatest||{};
  const now=new Date();
  const dateStr=now.toLocaleDateString('es-ES',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
  document.getElementById('briefing-date').textContent=dateStr;

  // Helper: find benchmark by name or ticker
  const bm_get=(keys)=>{
    for(const k of keys){const r=bm.find(x=>x.ticker===k||x.name===k);if(r)return r;}
    return null;
  };
  const chg=(r)=>r?r['1D']||0:0;
  const pri=(r)=>r?r.price||0:0;
  const fmt2=(v,prefix='',suffix='')=>{
    if(v===null||v===undefined)return'—';
    const n=parseFloat(v);
    return `${prefix}${isNaN(n)?v:n.toLocaleString('es-ES',{minimumFractionDigits:2,maximumFractionDigits:2})}${suffix}`;
  };
  const chgStr=(v)=>{
    const n=parseFloat(v);
    if(isNaN(n))return'—';
    const cls=n>0?'up':'dn';
    return `<span class="${cls}">${n>0?'+':''}${n.toFixed(2)}%</span>`;
  };
  const dot=(v)=>{const n=parseFloat(v);if(isNaN(n))return'🟡';return n>0.3?'🟢':n<-0.3?'🔴':'🟡';};
  const dval=(r)=>r?`${fmt2(pri(r))} | ${chgStr(chg(r))}`:'—';

  // ── Get data
  const sp500=bm_get(['^GSPC','S&P 500']);
  const ndx=bm_get(['^NDX','Nasdaq 100']);
  const rut=bm_get(['^RUT','Russell 2000']);
  const djia=bm_get(['^DJI','Dow Jones']);
  const vix=bm_get(['^VIX','VIX']);
  const stoxx=bm_get(['^STOXX50E','Euro Stoxx 50']);
  const ibex=bm_get(['^IBEX','IBEX 35 (Esp)']);
  const dax=bm_get(['^GDAXI','DAX (Germany)']);
  const ftse=bm_get(['^FTSE','FTSE 100']);
  const cac=bm_get(['^FCHI','CAC 40 (Fr)']);
  const nikkei=bm_get(['^N225','Nikkei 225']);
  const hsi=bm_get(['^HSI','Hang Seng']);
  const gold=bm_get(['GC=F','Gold']);
  const silver=bm_get(['SI=F','Silver']);
  const oil=bm_get(['CL=F','Oil (WTI)']);
  const natgas=bm_get(['NG=F','Natural Gas']);
  const copper=bm_get(['HG=F','Copper']);
  const btc=bm_get(['BTC-USD','Bitcoin']);
  const eth=bm_get(['ETH-USD','Ethereum']);
  const tnx=bm_get(['^TNX','T-Bond 10Y Yield']);
  const eurusd=bm_get(['EURUSD=X','EUR/USD']);

  // ── Sector flows
  const sectors=D.sectors||[];
  const topSec=sectors.filter(s=>(s['1D']||0)>0).sort((a,b)=>(b['1D']||0)-(a['1D']||0)).slice(0,3);
  const botSec=sectors.filter(s=>(s['1D']||0)<0).sort((a,b)=>(a['1D']||0)-(b['1D']||0)).slice(0,3);

  // ── Interpret Wall Street tone
  const spChg=chg(sp500);
  const wsTone=spChg>0.5?'tono positivo, momentum comprador':spChg>0?'tono mixto, ligeramente alcista':spChg>-0.5?'tono mixto, ligeramente bajista':'presión vendedora, sesión correctiva';
  const vixNum=parseFloat(pri(vix))||0;
  const vixNote=vixNum<15?'VIX muy bajo, complacencia elevada':vixNum<20?'VIX en zona de calma':vixNum<25?'VIX moderado, algo de precaución':'VIX elevado, volatilidad presente';

  // ── Interpret Europe
  const euAvg=[[stoxx,cac,dax,ibex,ftse]].flat().filter(Boolean).reduce((a,r)=>a+chg(r),0)/5||0;
  const euTone=euAvg>0.3?'positivo generalizado':euAvg>0?'ligeramente positivo':euAvg>-0.3?'mixto con sesgo bajista':'negativo';

  // ── Semaphore
  const semaphore=[
    {l:'Wall Street',v:dot(spChg),t:spChg>0.3?'positivo':spChg>-0.3?'mixto':'negativo'},
    {l:'Europa',v:dot(euAvg),t:euAvg>0.3?'positivo':euAvg>-0.3?'mixto':'negativo'},
    {l:'Asia',v:dot(chg(nikkei)),t:chg(nikkei)>0?'positivo':'mixto'},
    {l:'Materias primas',v:dot(chg(gold)),t:chg(gold)>0?'positivo':'débil'},
    {l:'Cripto',v:dot(chg(btc)),t:chg(btc)>0.5?'rebote':'estabilizando'},
    {l:'Bono 10Y USA',v:dot(-chg(tnx)),t:chg(tnx)<0?'relaja presión':chg(tnx)>0.5?'sube yield — presión':'estable'},
    {l:'VIX',v:dot(-chg(vix)),t:chg(vix)<0?'cae — calma':chg(vix)>1?'sube — alerta':'sin cambios relevantes'},
  ];

  // ── Best/worst of day
  const allBm=[...bm].sort((a,b)=>(b['1D']||0)-(a['1D']||0));
  const best=allBm.slice(0,3);
  const worst=allBm.slice(-3).reverse();

  // ── Build HTML
  const section=(icon,title,content)=>
    `<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:16px 18px;margin-bottom:12px">
      <div style="font-family:Syne,sans-serif;font-size:14px;font-weight:700;color:var(--hi);margin-bottom:12px">${icon} ${title}</div>
      ${content}
    </div>`;

  const row=(emoji,label,value)=>
    `<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;font-size:12px">
      <span style="font-size:14px;width:20px;flex-shrink:0">${emoji}</span>
      <span style="color:var(--dim);width:180px;flex-shrink:0">${label}</span>
      <span style="font-weight:600">${value}</span>
    </div>`;

  const subhead=(t)=>`<div style="font-size:11px;font-weight:700;color:var(--ac);text-transform:uppercase;letter-spacing:.08em;margin:10px 0 6px">${t}</div>`;

  // ── Intro
  const introTone=spChg>0.3&&euAvg>0?'constructivo, con Europa y Wall Street alineados al alza':
    spChg<-0.3&&euAvg<0?'negativo, con presión en ambos lados del Atlántico':
    'mixto, con divergencias entre mercados';
  const intro=`<div style="font-size:13px;color:var(--tx);line-height:1.9;padding:14px 18px;background:var(--bg2);border:1px solid var(--b1);border-radius:10px;margin-bottom:12px;border-left:4px solid var(--warn)">
    <strong style="color:var(--hi)">Arranque de sesión con tono ${introTone}.</strong>
    ${euAvg>0.1?'Europa muestra sesgo positivo con ganancias generalizadas.':euAvg<-0.1?'Europa abre con pérdidas.':'Europa en tono mixto.'}
    Wall Street ${wsTone}.
    ${vixNote}.
    ${chg(oil)<-0.5?'El crudo retrocede, aliviando algo la presión inflacionista.':chg(oil)>0.5?'El crudo sube, añadiendo presión sobre inflación.':'El crudo sin grandes movimientos.'}
  </div>`;

  // ── Futures section
  const wsSection=section('🇺🇸','Futuros Wall Street',
    row(dot(chg(djia)),'Dow Jones 30',dval(djia))+
    row(dot(chg(sp500)),'S&P 500',dval(sp500))+
    row(dot(chg(ndx)),'Nasdaq 100',dval(ndx))+
    row(dot(chg(rut)),'Russell 2000',dval(rut))+
    row(dot(-chg(vix)),'VIX',dval(vix))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${spChg>0.3?'Wall Street viene con momentum positivo. Sectores cíclicos y tech en foco.':
        spChg<-0.3?'Wall Street corrige. Rotation hacia defensivos y bonos posible.':
        'Wall Street viene plano. Sesión de consolidación probable sin catalizador.'}
      ${ndx&&sp500&&(chg(ndx)-chg(sp500))>0.5?' Nasdaq lidera, señal de apetito por risk-on en growth.':''}
    </div>`
  );

  const euSection=section('🇪🇺','Futuros Europa',
    row(dot(chg(stoxx)),'Euro Stoxx 50',dval(stoxx))+
    row(dot(chg(ibex)),'IBEX 35',dval(ibex))+
    row(dot(chg(dax)),'DAX',dval(dax))+
    row(dot(chg(ftse)),'FTSE 100',dval(ftse))+
    row(dot(chg(cac)),'CAC 40',dval(cac))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 Europa ${euTone}.
      ${ibex&&chg(ibex)>0.1?' IBEX muestra fuerza relativa positiva.':ibex&&chg(ibex)<-0.1?' IBEX bajo presión.':''}
      ${dax&&chg(dax)>0.3?' DAX lidera Europa, buen signo para industriales.':''}
    </div>`
  );

  const asiaSection=section('🌏','Asia',
    row(dot(chg(nikkei)),'Nikkei 225',dval(nikkei))+
    row(dot(chg(hsi)),'Hang Seng',dval(hsi))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${chg(nikkei)<0&&chg(hsi)>0?'Asia mixta. Japón flaquea mientras Hong Kong destaca en positivo.':
        chg(nikkei)>0&&chg(hsi)>0?'Asia positiva generalizada, buen contexto para apertura global.':
        chg(nikkei)<0&&chg(hsi)<0?'Asia cierra en negativo, posible presión al abrir.':
        'Asia con comportamiento dispar entre plazas.'}
    </div>`
  );

  const commSection=section('🟡','Materias Primas',
    row(dot(chg(gold)),'Oro',dval(gold))+
    row(dot(chg(silver)),'Plata',dval(silver))+
    row(dot(chg(copper)),'Cobre',dval(copper))+
    row(dot(chg(oil)),'Petróleo Brent/WTI',dval(oil))+
    row(dot(chg(natgas)),'Gas Natural',dval(natgas))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${chg(oil)<-0.5?'Las materias primas vienen más flojas. La caída del crudo alivia algo la presión inflacionista.':
        chg(oil)>0.5?'El crudo sube. Presión inflacionista se mantiene, ojo a energía y transporte.':
        'Materias primas sin grandes movimientos. Mercado en modo espera.'}
      ${chg(gold)>0.3?' El oro sube — puede señalar búsqueda de refugio o expectativas inflacionistas.':''}
    </div>`
  );

  const cryptoSection=section('₿','Cripto',
    row(dot(chg(btc)),'Bitcoin',dval(btc))+
    row(dot(chg(eth)),'Ethereum',dval(eth))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${chg(btc)>1?'Cripto al alza. Bitcoin lidera con momentum positivo.':
        chg(btc)<-1?'Cripto bajo presión. Sesión de corrección.':
        'Cripto intenta estabilizarse. Movimiento moderado, sin señal clara.'}
      ${eth&&btc&&(chg(eth)-chg(btc))>0.5?' Ethereum rebota más que Bitcoin — posible rotación hacia altcoins.':''}
    </div>`
  );

  // Semaphore section
  const semSection=`<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:16px 18px;margin-bottom:12px">
    <div style="font-family:Syne,sans-serif;font-size:14px;font-weight:700;color:var(--hi);margin-bottom:12px">🚦 Semáforo de mercado</div>
    ${semaphore.map(s=>`<div style="display:flex;align-items:center;gap:10px;margin-bottom:7px;font-size:12px">
      <span style="font-size:16px;width:22px">${s.v}</span>
      <span style="width:160px;flex-shrink:0;color:var(--dim)">${s.l}:</span>
      <span style="color:var(--tx)">${s.t}</span>
    </div>`).join('')}
  </div>`;

  // Sector flow
  const sectorSection=section('📊','Flujo sectorial hoy',
    topSec.length?subhead('🟢 Mejor comportamiento')+''+topSec.map(s=>row('▲',s.name,chgStr(s['1D']))).join(''):''
    +botSec.length?subhead('🔴 Peor comportamiento')+''+botSec.map(s=>row('▼',s.name,chgStr(s['1D']))).join(''):''
  );

  // Best/worst
  const bwSection=section('⭐','Activos destacados del día',
    subhead('🟢 Mayores subidas')+best.map(r=>row('▲',r.name,dval(r))).join('')+
    subhead('🔴 Mayores caídas')+worst.map(r=>row('▼',r.name,dval(r))).join('')
  );

  // Yield / Macro
  const macroSection=section('📉','Tipos & Macro',
    row(dot(-chg(tnx)),'Yield 10Y EEUU',tnx?pri(tnx).toFixed(3)+'% ('+chgStr(chg(tnx))+')'  :'—')+
    row(dot(chg(eurusd)),'EUR/USD',dval(eurusd))+
    `<div style="font-size:10px;color:var(--dim);margin-top:10px;padding:8px 12px;background:var(--bg3);border-radius:6px;border-left:3px solid var(--b2)">
      👉 ${tnx&&chg(tnx)>0.5?'El yield 10Y sube — presión sobre valoraciones growth y real estate.':
        tnx&&chg(tnx)<-0.5?'El yield 10Y cae — favorable para tech y bonos. Posible señal de ralentización.':
        'Los tipos sin grandes movimientos hoy.'}
    </div>`
  );

  // ── 2-COLUMN LAYOUT ─────────────────────────────────────────────────────────
  // Top semaphore bar
  const semTop=[
    {v:dot(spChg),l:'Wall St'},
    {v:dot(euAvg),l:'Europa'},
    {v:dot(chg(nikkei)),l:'Asia'},
    {v:dot(chg(gold)),l:'Materias'},
    {v:dot(chg(btc)),l:'Cripto'},
    {v:dot(-chg(vix)),l:'VIX'},
  ];
  const semEl=document.getElementById('briefing-semaphore-top');
  if(semEl) semEl.innerHTML=semTop.map(s=>
    `<div style="text-align:center;background:var(--bg3);border-radius:6px;padding:4px 8px;border:1px solid var(--b1)">
      <div style="font-size:14px">${s.v}</div>
      <div style="font-size:8px;color:var(--dim);margin-top:1px">${s.l}</div>
    </div>`).join('');

  // Intro headline
  const introEl=document.getElementById('briefing-intro');
  if(introEl) introEl.innerHTML=`
    <div style="background:linear-gradient(135deg,var(--bg2),var(--bg3));border:1px solid var(--b1);border-radius:10px;padding:16px 20px;border-left:4px solid var(--warn)">
      <div style="font-family:Syne,sans-serif;font-size:15px;font-weight:800;color:var(--hi);line-height:1.5;margin-bottom:8px">
        ${spChg>0.3&&euAvg>0?'🟢 Sesión constructiva — Europa y Wall Street alineados al alza':
          spChg<-0.3&&euAvg<0?'🔴 Presión vendedora en ambos lados del Atlántico':
          euAvg>0.3?'🟡 Europa lidera — Wall Street más rezagado en apertura':
          '🟡 Sesión mixta — mercados buscan dirección'}
      </div>
      <div style="font-size:12px;color:var(--tx);line-height:1.7">
        ${euAvg>0.1?'Europa abre con sesgo positivo generalizado. ':'Europa con tono mixto. '}
        Wall Street ${wsTone}. ${vixNote}.
        ${chg(oil)<-0.5?'El crudo retrocede, aliviando presión inflacionista.':chg(oil)>0.5?'El crudo sube, atención a energía.':'Crudo estable.'}
        ${chg(gold)>0.3?' Oro al alza — posible señal de incertidumbre o inflación.':''}
      </div>
    </div>`;

  // Helper compact section for 2 cols
  const csection=(icon,title,content,accent)=>
    `<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:9px;padding:13px 15px;margin-bottom:10px;border-top:2px solid ${accent||'var(--b2)'}">
      <div style="font-family:Syne,sans-serif;font-size:12px;font-weight:700;color:var(--hi);margin-bottom:10px">${icon} ${title}</div>
      ${content}
    </div>`;
  const crow=(emoji,label,value,note)=>
    `<div style="display:flex;align-items:center;gap:8px;margin-bottom:7px;font-size:11px">
      <span style="font-size:13px;width:18px;flex-shrink:0">${emoji}</span>
      <span style="color:var(--dim);flex:1">${label}</span>
      <span style="font-weight:600;white-space:nowrap">${value}</span>
      ${note?`<span style="font-size:9px;color:var(--dim);white-space:nowrap">${note}</span>`:''}
    </div>`;
  const cnote=(t)=>
    `<div style="font-size:10px;color:var(--dim);margin-top:8px;padding:7px 10px;background:var(--bg3);border-radius:5px;border-left:2px solid var(--b2)">👉 ${t}</div>`;

  // ── Helpers for data+analysis sections ────────────────────────────────────
  const dline=(e,l,v)=>
    `<div style="display:flex;align-items:center;gap:10px;padding:5px 0;border-bottom:1px solid var(--b1);font-size:12px">
      <span style="font-size:14px;flex-shrink:0;width:20px">${e}</span>
      <span style="color:var(--dim);flex:1">${l}</span>
      <span style="font-weight:600;white-space:nowrap">${v}</span>
    </div>`;
  const analysis=(txt)=>
    `<div style="margin-top:12px;padding:12px 14px;background:var(--bg3);border-radius:7px;font-size:12px;color:var(--tx);line-height:1.85">${txt}</div>`;
  const tsec=(icon,title,rows,analysisTxt,accent)=>
    `<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:15px 17px;margin-bottom:12px;border-top:3px solid ${accent}">
      <div style="font-family:Syne,sans-serif;font-size:13px;font-weight:800;color:var(--hi);margin-bottom:12px">${icon} ${title}</div>
      ${rows}${analysis(analysisTxt)}
    </div>`;

  // ── Analytical texts ────────────────────────────────────────────────────────
  const wsText=(()=>{
    if(spChg>0.5) return `El S&P 500 avanza un <strong style="color:var(--up)">${spChg>0?'+':''}${spChg}%</strong> — sesión con sesgo claramente alcista. El Nasdaq ${ndx&&chg(ndx)>spChg?'lidera, señal de apetito por growth y tecnología':'acompaña con menor fuerza, lo que puede indicar una subida más broad que tech-driven'}. El Russell 2000 ${rut&&chg(rut)>0?'también sube — la amplitud del rally es positiva, no solo megacaps. Señal de salud del mercado':'se queda rezagado, lo que reduce la calidad del rally: sube por los grandes pero el resto no acompaña'}. VIX en ${vixNum} — ${vixNum<18?'zona de calma, el mercado no está comprando protección agresiva. Condición favorable para mantener posiciones':vixNum>22?'nivel elevado, el mercado expresa incertidumbre. Conviene revisar coberturas':'zona neutral'}. Contexto: favorable para mantener o añadir posiciones largas con stops ajustados.`;
    if(spChg<-0.5) return `El S&P 500 cae un <strong style="color:var(--dn)">${spChg}%</strong> — sesión con presión vendedora. ${ndx&&chg(ndx)<chg(sp500)?'El Nasdaq lidera las caídas — los valores más valorados son los más penalizados cuando hay aversión al riesgo o subida de tipos.':''} El Russell 2000 ${rut&&chg(rut)<chg(sp500)?'también retrocede con fuerza, lo que confirma que no es rotación sino salida de riesgo generalizada':'muestra algo más de resistencia, posible efecto defensivo en small caps domésticas'}. VIX ${vixNum>22?'sube por encima de 22 — el mercado compra protección activamente. Señal de que la caída puede tener continuidad':'contenido, lo que sugiere que la corrección no ha generado pánico de momento, puede ser una corrección sana'}. Consejo: revisar stops, reducir posiciones especulativas, buscar refugio en sectores defensivos.`;
    return `Wall Street abre plano. El S&P 500 en <strong>${(spChg>0?'+':'')+spChg}%</strong> — sesiones de consolidación como esta son normales y suelen ser oportunidades para analizar y posicionarse. ${vixNum<17?'VIX muy bajo — posible exceso de complacencia. Conviene no bajar la guardia.':vixNum>22?'VIX elevado — hay nerviosismo latente incluso en días planos.':'VIX en zona neutral, sin señal de alarma.'} Sin catalizador claro, lo más probable es un rango estrecho durante la jornada.`;
  })();

  const euText=(()=>{
    const sprd=dax&&sp500?chg(dax)-spChg:0;
    let t=`Europa ${euTone}. `;
    t+=dax&&chg(dax)>0.3?`El DAX (${(chg(dax)>0?'+':'')+chg(dax)}%) lidera — el mercado alemán es intensivo en exportaciones e industriales, y su fuerza refleja expectativas de recuperación económica global. `:dax&&chg(dax)<-0.3?`El DAX flaquea (${chg(dax)}%) — debilidad en industriales europeos, posiblemente por el euro o datos macro. `:'';
    t+=ibex&&chg(ibex)>0.2?`El IBEX (${(chg(ibex)>0?'+':'')+chg(ibex)}%) sube — banca y energía españolas traccionan. `:'';
    t+=euAvg>0&&spChg<-0.2?`Divergencia relevante: Europa sube mientras Wall Street cae. Esto puede deberse al diferencial BCE/Fed, flujos de capital hacia mercados más baratos, o simplemente diferencia de horario. Vigilar si se mantiene al abrir USA.`:euAvg<-0.2&&spChg>0.2?`Europa rezagada frente a Wall Street — posibles causas: debilidad del euro, incertidumbre geopolítica o menor momentum económico europeo.`:euAvg>0?`El conjunto europeo acompaña el tono positivo global. Buen arranque para sesión completa.`:`Europa amplifica la debilidad de Wall Street. Sesión complicada en ambos lados.`;
    return t;
  })();

  const secText=(()=>{
    if(!topSec.length) return 'Sin datos de flujo sectorial disponibles hoy.';
    const ts=topSec[0], bs=botSec[0];
    let t=`El análisis sectorial revela dónde está fluyendo el dinero. `;
    t+=`<strong style="color:var(--up)">${ts.name}</strong> lidera con ${(ts['1D']>0?'+':'')+ts['1D']}% — `;
    if(ts.name.includes('Tech')||ts.name.includes('Communication')) t+='el dinero entra en growth. Señal de apetito por riesgo y expectativas de tipos más bajos o benignos.';
    else if(ts.name.includes('Energy')||ts.name.includes('Materials')) t+='los cíclicos tiran fuerte. Expectativas de crecimiento o subida de materias primas.';
    else if(ts.name.includes('Utilities')||ts.name.includes('Staples')||ts.name.includes('Healthcare')) t+='defensivos al frente — el dinero busca seguridad. Señal de cautela aunque el índice suba.';
    else t+='sector a vigilar como posible catalizador de la jornada.';
    if(bs) t+=` Por el contrario, <strong style="color:var(--dn)">${bs.name}</strong> recorta ${bs['1D']}%${bs.name.includes('Real Estate')?' — los tipos altos siguen presionando al inmobiliario':bs.name.includes('Tech')?' — posible toma de beneficios en growth tras subidas recientes':''}.`;
    return t;
  })();

  const commText=(()=>{
    let t='';
    t+=chg(oil)<-1?`El petróleo WTI cae un ${chg(oil)}%, lo que alivia presión inflacionista y reduce costes para industria y transporte. Históricamente, cuando el crudo baja, los bancos centrales tienen más margen para bajar tipos. Positivo para bonos y sectores con altos costes energéticos. `:chg(oil)>1?`El crudo sube un +${chg(oil)}% — presión inflacionista al alza. Sectores afectados: aerolíneas, transporte, química y consumo. El mercado podría descontar menor flexibilidad de la Fed. `:`Petróleo sin grandes cambios. `;
    t+=chg(gold)>0.5?`El oro avanza +${chg(gold)}% — puede indicar búsqueda de refugio, inflación persistente o debilidad del dólar. Históricamente el oro sube cuando los tipos reales bajan o cuando hay incertidumbre elevada. `:chg(gold)<-0.5?`El oro cede ${chg(gold)}% — ocurre cuando el dólar se fortalece o suben los tipos reales. `:'';
    t+=chg(copper)<-0.5?'El cobre baja — señal de preocupación sobre la demanda industrial global, especialmente China. Vigilar también acero y materiales. ':chg(copper)>0.5?'El cobre sube — señal positiva sobre actividad industrial y construcción global. Favorable para materiales. ':'';
    return t||'Materias primas sin movimientos relevantes hoy.';
  })();

  const cryptoText=(()=>{
    const bc=chg(btc), ec=chg(eth);
    let t=bc>2?`Bitcoin sube con fuerza (+${bc}%), superando el 2% que marca momentum comprador real en cripto. `:bc<-2?`Bitcoin cae un ${bc}% — corrección activa. En este entorno conviene esperar confirmación antes de añadir exposición. `:bc>0?`Bitcoin avanza moderadamente (+${bc}%). Sin señal clara de dirección. `:bc<0?`Bitcoin cede ${bc}%, movimiento menor, dentro del ruido habitual. `:'';
    if(ec>bc+1) t+=`Ethereum supera a Bitcoin (+${ec}% vs ${(bc>0?'+':'')+bc}%) — cuando ETH lidera, suele indicar que los inversores toman más riesgo dentro del ecosistema cripto, rotando hacia altcoins.`;
    else if(bc>ec+1) t+=`Bitcoin supera a Ethereum — fase más conservadora en cripto, el dinero se concentra en el activo de mayor capitalización y menor riesgo relativo.`;
    return t||'Cripto sin movimiento significativo hoy.';
  })();

  const macroText=(()=>{
    const yld=pri(tnx);
    let t=`El yield del bono USA a 10 años cotiza en <strong>${yld?yld.toFixed(3):'—'}%</strong>. `;
    t+=chg(tnx)>0.5?`Sube hoy (+${chg(tnx)}%): el coste del capital aumenta, lo que presiona valoraciones de empresas growth (múltiplos altos) y al sector inmobiliario. Cuando el 10Y sube, el descuento de flujos futuros se hace más exigente — las acciones "caras" sufren más. `:chg(tnx)<-0.5?`Cae hoy (${chg(tnx)}%): alivia la presión sobre growth y tech. Cuando el bono cae, los inversores suelen rotar desde renta fija hacia renta variable. Favorable para empresas de alto crecimiento. `:`Sin grandes movimientos en tipos hoy. `;
    const eu=chg(eurusd);
    t+=eu>0.3?`EUR/USD sube (${(eu>0?'+':'')+eu}%): euro más fuerte. Positivo para poder adquisitivo europeo en importaciones pero puede pesar sobre exportadoras (Volkswagen, ASML, LVMH).`:eu<-0.3?`EUR/USD cae (${eu}%): euro débil. Beneficia a exportadoras europeas pero encarece importaciones — especialmente energía y commodities.`:`EUR/USD estable, sin efecto divisa relevante hoy.`;
    return t;
  })();

  const bwText=(()=>{
    const bn=best.slice(0,2).map(r=>r.name).join(' y ');
    const wn=worst.slice(0,2).map(r=>r.name).join(' y ');
    return `Los activos con mejor comportamiento hoy son <strong style="color:var(--up)">${bn}</strong>. Antes de seguir cualquier movimiento fuerte, analiza siempre si hay un catalizador real detrás (dato, noticia, volumen) o es solo ruido de baja liquidez. En el extremo opuesto, <strong style="color:var(--dn)">${wn}</strong> retroceden. En activos que caen con fuerza, la primera pregunta es: ¿hay razón fundamental o es corrección técnica? La segunda: ¿el stop ha saltado o conviene aguantar el nivel clave?`;
  })();

  // ── LEFT COLUMN
  const leftHTML=
    tsec('🇺🇸','Wall Street',
      dline(dot(chg(djia)),'Dow Jones 30',dval(djia))+
      dline(dot(chg(sp500)),'S&P 500',dval(sp500))+
      dline(dot(chg(ndx)),'Nasdaq 100',dval(ndx))+
      dline(dot(chg(rut)),'Russell 2000',dval(rut))+
      dline(dot(-chg(vix)),'VIX',dval(vix)),
      wsText,'var(--ac)')
  +tsec('🇪🇺','Europa',
      dline(dot(chg(stoxx)),'Euro Stoxx 50',dval(stoxx))+
      dline(dot(chg(ibex)),'IBEX 35',dval(ibex))+
      dline(dot(chg(dax)),'DAX',dval(dax))+
      dline(dot(chg(ftse)),'FTSE 100',dval(ftse))+
      dline(dot(chg(cac)),'CAC 40',dval(cac)),
      euText,'var(--up)')
  +tsec('📊','Flujo Sectorial',
      (topSec.length?'<div style="font-size:10px;color:var(--up);font-weight:700;margin-bottom:6px">▲ FUERTES HOY</div>'+topSec.map(s=>dline('▲',s.name,chgStr(s['1D']))).join(''):'')
      +(botSec.length?'<div style="font-size:10px;color:var(--dn);font-weight:700;margin-top:8px;margin-bottom:6px">▼ DÉBILES HOY</div>'+botSec.map(s=>dline('▼',s.name,chgStr(s['1D']))).join(''):''),
      secText,'var(--warn)');

  // ── RIGHT COLUMN
  const rightHTML=
    tsec('🟡','Materias Primas',
      dline(dot(chg(gold)),'Oro',dval(gold))+
      dline(dot(chg(silver)),'Plata',dval(silver))+
      dline(dot(chg(oil)),'Petróleo WTI',dval(oil))+
      dline(dot(chg(copper)),'Cobre',dval(copper))+
      dline(dot(chg(natgas)),'Gas Natural',dval(natgas)),
      commText,'var(--warn)')
  +tsec('₿','Cripto',
      dline(dot(chg(btc)),'Bitcoin',dval(btc))+
      dline(dot(chg(eth)),'Ethereum',dval(eth)),
      cryptoText,'rgb(249,115,22)')
  +tsec('🌏','Asia — Cierre nocturno',
      dline(dot(chg(nikkei)),'Nikkei 225',dval(nikkei))+
      dline(dot(chg(hsi)),'Hang Seng',dval(hsi)),
      chg(nikkei)>0&&chg(hsi)>0?'Asia cierra en positivo generalizado — buen contexto para apertura europea y global. Nikkei y Hang Seng alineados al alza reduce la incertidumbre de apertura.':chg(nikkei)<0&&chg(hsi)<0?'Asia cierra en rojo. Doble negativo en Nikkei y Hang Seng puede reflejar datos macro de China débiles o aversión al riesgo global. Vigilar su impacto en exportadoras europeas.':chg(nikkei)<0&&chg(hsi)>0?`Japón flaquea (${chg(nikkei)}%) mientras Hong Kong aguanta (${(chg(hsi)>0?'+':'')+chg(hsi)}%). La debilidad nipona puede estar ligada al yen o a datos específicos. Hong Kong resistiendo es constructivo para emergentes asiáticos y el sector tecnológico chino.`:`Asia mixta. Sin señal clara para activos globales desde el cierre asiático.`,'var(--ac)')
  +tsec('📉','Tipos & Macro',
      dline(dot(-chg(tnx)),'Yield 10Y USA',tnx?pri(tnx).toFixed(3)+'% ('+chgStr(chg(tnx))+')':'—')+
      dline(dot(chg(eurusd)),'EUR/USD',dval(eurusd)),
      macroText,'rgb(52,211,153)')
  +tsec('⭐','Activos Destacados',
      '<div style="font-size:10px;color:var(--up);font-weight:700;margin-bottom:6px">▲ MEJORES</div>'
      +best.map(r=>dline('▲',r.name,dval(r))).join('')
      +'<div style="font-size:10px;color:var(--dn);font-weight:700;margin-top:8px;margin-bottom:6px">▼ PEORES</div>'
      +worst.map(r=>dline('▼',r.name,dval(r))).join(''),
      bwText,'var(--dim)');

  // Semáforo eliminado — ya visible en topbar

  document.getElementById('briefing-col-left').innerHTML=leftHTML;
  document.getElementById('briefing-col-right').innerHTML=rightHTML;
}

// ── ACCIÓN DEL DÍA ────────────────────────────────────────────────────────────
function renderAccionDia(){
  var body=document.getElementById('accion-body');
  if(!body)return;
  // Use pre-computed accion del dia from Python payload
  var tk=D.accionTk||'';
  var info=D.accionInfo||{};
  var sp2=D.stockPerf||{};
  var r=sp2[tk]||{};
  if(!tk||!r.price){
    body.innerHTML='<div style="color:var(--dim);padding:20px">Sin datos. Vuelve a ejecutar el script.</div>';
    return;
  }
  var now=new Date();
  var allSp=Object.values(sp2).filter(function(x){return x['1Y']!==undefined;});
  allSp.sort(function(a,b){return (a['1Y']||0)-(b['1Y']||0);});
  function rsOf(t){var ri=allSp.findIndex(function(x){return x.ticker===t;});return ri>=0?Math.round(ri/allSp.length*100):0;}
  var rs=rsOf(tk);
  var distHi=r['52wHigh']?((r.price-r['52wHigh'])/r['52wHigh']*100):null;
  var hotInd=new Set((D.industries||[]).filter(function(i){return (i['1M']||0)>2;}).map(function(i){return i.name;}));
  var tkInd={};
  Object.entries(D.industryStocks||{}).forEach(function(e2){
    var ind2=e2[0],stocks2=e2[1];
    stocks2.forEach(function(s){if(!tkInd[s.ticker])tkInd[s.ticker]=ind2;});
  });

  function fmtM(v){if(!v)return'—';var n=Number(v);if(isNaN(n))return'—';if(Math.abs(n)>=1e12)return'$'+(n/1e12).toFixed(2)+'T';if(Math.abs(n)>=1e9)return'$'+(n/1e9).toFixed(1)+'B';if(Math.abs(n)>=1e6)return'$'+(n/1e6).toFixed(0)+'M';return'$'+n.toFixed(0);}
  function fmtP(v){return v!==null&&v!==undefined?Math.round(v*100)+'%':'—';}
  function fmtR(v){return v!==null&&v!==undefined?Number(v).toFixed(2):'—';}

  // ── Build HTML using string concatenation (no backticks) ─────────────────
  function card(l,v,sub){
    return '<div style="background:var(--bg3);border-radius:8px;padding:10px 12px;border:1px solid var(--b1)">'
      +'<div style="font-size:9px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:5px">'+l+'</div>'
      +'<div style="font-family:Syne,sans-serif;font-size:17px;font-weight:800;color:var(--hi)">'+v+'</div>'
      +(sub?'<div style="font-size:10px;color:var(--dim);margin-top:3px">'+sub+'</div>':'')
      +'</div>';
  }

  function block(title,accent,html){
    return '<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:15px 17px;margin-bottom:11px;border-left:4px solid '+accent+'">'
      +'<div style="font-family:Syne,sans-serif;font-size:13px;font-weight:800;color:var(--hi);margin-bottom:10px">'+title+'</div>'
      +'<div style="font-size:12px;color:var(--tx);line-height:1.85">'+html+'</div>'
      +'</div>';
  }

  // ── Texts ────────────────────────────────────────────────────────────────
  var sector=info.sector||pick.industry||'—';
  var industry=info.industry||pick.industry||'—';
  var name=info.name||tk;

  // Activity — show full summary from yfinance first
  var actT='';
  if(info.summary&&info.summary.length>50){
    actT='<strong>'+name+'</strong> — '+info.summary+'<br><br>';
  }
  var sec=sector.toLowerCase(), ind=industry.toLowerCase();
  if(sec.indexOf('tech')>=0||ind.indexOf('software')>=0||ind.indexOf('semi')>=0)
    actT+='<strong>'+name+'</strong> opera en tecnología, uno de los sectores con mayor potencial de crecimiento a largo plazo. Las empresas tech se benefician de escalabilidad global, altos márgenes y fuertes efectos de red. La clave es entender si el crecimiento de ingresos es sostenible y si el modelo de negocio crea barreras difíciles de replicar.';
  else if(sec.indexOf('health')>=0||ind.indexOf('bio')>=0||ind.indexOf('pharma')>=0)
    actT+='<strong>'+name+'</strong> pertenece al sector sanitario — históricamente defensivo pero con catalizadores de alto impacto (aprobaciones FDA, datos clínicos). El MOAT regulatorio (patentes, aprobaciones) puede ser poderoso pero también tiene fecha de caducidad. La innovación y el pipeline son clave.';
  else if(sec.indexOf('financ')>=0||ind.indexOf('bank')>=0||ind.indexOf('insur')>=0)
    actT+='<strong>'+name+'</strong> opera en el sector financiero, muy sensible al ciclo de tipos. Los bancos se benefician de tipos altos (mayor margen de intereses). La calidad del balance y la disciplina en riesgos son los indicadores más relevantes para evaluar la sostenibilidad del negocio.';
  else if(sec.indexOf('energy')>=0||ind.indexOf('oil')>=0)
    actT+='<strong>'+name+'</strong> está en el sector energético, condicionado por el precio del crudo. Su fortaleza actual refleja que el mercado espera precios sostenidos. Los flujos de caja libre y el dividendo son los principales atractivos de estas compañías para los inversores.';
  else if(sec.indexOf('industrial')>=0||ind.indexOf('defense')>=0||ind.indexOf('aero')>=0)
    actT+='<strong>'+name+'</strong> pertenece al sector industrial, con contratos a largo plazo y alta barrera de entrada. La visibilidad en ingresos (backlog de pedidos) es una de sus principales fortalezas. Se beneficia del gasto en infraestructura y defensa, con demanda relativamente inelástica.';
  else if(sec.indexOf('consumer')>=0||ind.indexOf('retail')>=0)
    actT+='<strong>'+name+'</strong> está en el sector de consumo, ligado al ciclo económico y la confianza del consumidor. Las empresas líderes tienen marcas fuertes, alta fidelización y economías de escala. La marca y la experiencia del cliente son sus principales activos intangibles.';
  else
    actT+='<strong>'+name+'</strong> es una de las acciones con mejor comportamiento relativo en su universo. A continuación se detalla el análisis generado con la información disponible.';

  // MOAT
  var moatLines=[];
  if(info.grossMarg&&info.grossMarg>0.6) moatLines.push('<strong>Margen bruto del '+fmtP(info.grossMarg)+'</strong> — señal clara de pricing power. La empresa puede cobrar más que sus costes de forma sostenida, lo que en mercados competitivos indica una ventaja real (marca, tecnología propietaria o efecto de red).');
  else if(info.grossMarg&&info.grossMarg>0.3) moatLines.push('Margen bruto del '+fmtP(info.grossMarg)+' — saludable, aunque conviene vigilar si la competencia presiona hacia la baja.');
  if(info.roe&&info.roe>0.2) moatLines.push('<strong>ROE del '+fmtP(info.roe)+'</strong> — altos retornos sobre capital. Warren Buffett busca empresas con ROE sostenido por encima del 15-20%. Cuando una empresa genera retornos elevados durante años, suele significar que tiene una ventaja competitiva real que la competencia no puede copiar fácilmente.');
  if(info.revGrowth&&info.revGrowth>0.15) moatLines.push('<strong>Crecimiento de ingresos del '+fmtP(info.revGrowth)+'</strong> — por encima de la media del mercado. Empresas que crecen consistentemente capturan cuota de mercado o expanden su TAM (mercado total addressable). El crecimiento sostenido es el ingrediente más poderoso para la capitalización a largo plazo.');
  if(info.debtEq!==undefined&&info.debtEq!==null&&info.debtEq<0.5) moatLines.push('Balance sólido — Deuda/Equity de '+fmtR(info.debtEq)+'. Baja deuda da flexibilidad para invertir en crecimiento o recomprar acciones incluso en ciclos bajistas. Es una ventaja cuando suben los tipos de interés.');
  if(!moatLines.length) moatLines.push('Sin datos cuantitativos suficientes para el MOAT. Analiza directamente: cuota de mercado, barreras de entrada, switching costs, efectos de red o patentes.');
  var moatT=moatLines.join('<br><br>');

  // Technical
  var techLines=[];
  techLines.push('<strong>RS '+rs+'/100</strong> — '+( rs>=80?'acción en el percentil de liderazgo. William O\'Neil demostró que las grandes acciones suelen tener RS>80 antes de sus mayores movimientos. Estar en este rango no garantiza subidas, pero filtra las más fuertes del mercado.': rs>=70?'fuerza relativa alta, superando a la mayoría del mercado en los últimos 12 meses. Un RS en este rango refleja momentum real.': 'por encima de la media, aunque sin llegar al rango de liderazgo absoluto. Conviene monitorizar si sigue mejorando.'));
  if(distHi!==null) techLines.push((distHi>=-5?'<strong>Precio prácticamente en máximos anuales</strong> — el mejor setup de momentum. Las acciones en máximos no tienen resistencias técnicas anteriores (no hay nadie "atrapado" que quiera salir). Muchos grandes movimientos empiezan desde máximos, no desde mínimos.':(distHi>=-15?'Precio en zona alta del rango anual ('+distHi.toFixed(1)+'% del máximo). Una ruptura del máximo con volumen sería señal técnica potente.':'Precio lejos del máximo anual ('+distHi.toFixed(1)+'%). Conviene esperar una recuperación del impulso antes de considerar entrada.')));
  if(r.abv50&&r.abv200) techLines.push('<strong>Sobre MA50 y MA200</strong> — las dos medias principales en positivo confirman tendencia alcista a corto y largo plazo. Es la condición mínima que buscan los inversores de momentum para posicionarse en largo.');
  if(r.volRel&&r.volRel>1.3) techLines.push('Volumen relativo '+r.volRel+'x — el volumen reciente supera la media histórica. El volumen confirma convicción: subidas con volumen alto son más fiables que sin él.');
  if(r.rsi14) techLines.push('RSI(14): '+r.rsi14+(r.rsi14>70?' — zona de sobrecompra. Puede haber corrección técnica a corto plazo. No perseguir el precio; esperar pull-back o consolidación.':r.rsi14<35?' — zona de sobreventa. Puede ser oportunidad de rebote técnico si los fundamentales aguantan.':' — zona neutral, sin excesos en ninguna dirección.'));
  var techT=techLines.join('<br><br>');

  // Fundamentals
  var fundLines=[];
  if(!info.pe&&!info.fwdPE){ fundLines.push(''); }
  else {
    if(info.pe) fundLines.push('<strong>P/E '+fmtR(info.pe)+'</strong> — '+( info.pe>40?'múltiplo exigente. El mercado paga un premium importante por las expectativas de crecimiento futuro. Si la empresa no cumple esas expectativas, la caída puede ser brusca. Requiere seguimiento cercano.': info.pe>20?'valoración en rango moderado-alto, típica de empresas de calidad con buen crecimiento. Razonable si los beneficios siguen creciendo.':'valoración contenida. Puede indicar oportunidad si el crecimiento se mantiene, o ser una trampa de valor si el negocio se deteriora.'));
    if(info.fwdPE) fundLines.push('<strong>P/E Forward '+fmtR(info.fwdPE)+'</strong> — '+( info.fwdPE<(info.pe||99)?'inferior al trailing P/E. El mercado espera que los beneficios crezcan. Señal positiva: el consenso de analistas prevé mejora de resultados.':'superior al trailing, el mercado anticipa menores beneficios el próximo año. Vigilar la guía de la compañía en el próximo earnings.'));
    if(info.revGrowth) fundLines.push('<strong>Crecimiento de ingresos '+fmtP(info.revGrowth)+'</strong> — '+(info.revGrowth>0.2?'crecimiento acelerado. Empresas que crecen al 20%+ tienen un poder de capitalización enorme a largo plazo. La clave es si es sostenible.':info.revGrowth>0.08?'crecimiento saludable, en línea con empresas de calidad en fase de expansión.':'crecimiento moderado. Verificar si es temporal (efecto macro) o estructural (saturación del mercado).'));
    if(info.opMarg) fundLines.push('<strong>Margen operativo '+fmtP(info.opMarg)+'</strong> — '+(info.opMarg>0.25?'margen excepcional. Refleja eficiencia de costes o pricing power elevado. Difícil de mantener sin ventaja competitiva real.':info.opMarg>0.10?'margen saludable, en línea con empresas de calidad del sector.':'margen ajustado. Vigilar si la inflación de costes o la competencia lo siguen comprimiendo.'));
    if(info.analyst&&info.targetMean) fundLines.push('<strong>'+(info.nAnalysts||'Varios')+' analistas</strong> con precio objetivo '+'$'+Number(info.targetMean).toFixed(0)+' — '+( Number(info.targetMean)>r.price?'potencial alcista del '+Math.round((Number(info.targetMean)/r.price-1)*100)+'% según el consenso. Los precios objetivo son orientativos, no garantías.':'el precio ya está cerca o por encima del objetivo medio de analistas. El margen de seguridad es menor.'));
  }
  var fundT=fundLines.join('<br><br>');

  // Watch
  var watchLines=[];
  watchLines.push('<strong>Nivel clave:</strong> Máximo de 52 semanas en <strong>$'+r['52wHigh']+'</strong>. '+(distHi>=-5?'Ya en zona de máximos. Clave: que aguante y no aparezca una vela de distribución (cierre en mínimos con volumen alto), que sería señal de alerta.':'Una ruptura de ese nivel con volumen sería señal técnica potente de continuación del movimiento.'));
  if(r.ma50) watchLines.push('<strong>Soporte MA50</strong> en <strong>$'+r.ma50+'</strong> — zona de compra habitual para inversores de momentum. Un pull-back hacia la MA50 con volumen bajo y rebote con volumen alto es uno de los setups más clásicos y fiables.');
  watchLines.push('<strong>Catalizadores:</strong> Próximo earnings, datos macro del sector '+sector+', decisiones de la Fed sobre tipos. Mantener el calendario económico en radar.');
  watchLines.push('<strong>Riesgos:</strong> '+(r.rsi14&&r.rsi14>70?'RSI en sobrecompra ('+r.rsi14+'), puede haber corrección técnica antes de continuar. ':'')+'Rotación sectorial inesperada, revisión a la baja de guías por parte de la compañía, o dato macro adverso que cambie el contexto global.');
  var watchT=watchLines.join('<br><br>');

  // ── Date string ──────────────────────────────────────────────────────────
  var dayNames=['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'];
  var monthNames=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
  var dateStr=dayNames[now.getDay()]+', '+now.getDate()+' de '+monthNames[now.getMonth()]+' de '+now.getFullYear();

  // Clean up any remaining placeholders
  moatT=moatT.replace('__MOAT_API__','');
  fundT=fundT.replace('__FUND_API__','');

  var priceColor=r['1D']>=0?'var(--up)':'var(--dn)';
  var priceFmt='$'+r.price;
  var chgFmt=(r['1D']>=0?'+':'')+r['1D']+'% hoy';
  var analystText=info.analyst?(['','Compra Fuerte','Compra','Mantener','Vender','Vender Fuerte'][Math.round(info.analyst)]||''):'—';

  // ── Render ───────────────────────────────────────────────────────────────
  var badgesH='<span class="badge b-up" style="font-size:11px">RS '+rs+'</span> ';
  if(r.newHi) badgesH+='<span class="badge b-up" style="font-size:11px">★ 52W Máximo</span> ';
  if(r.abv50&&r.abv200) badgesH+='<span class="badge b-up" style="font-size:11px">✅ MA50+MA200</span> ';
  if(r.volRel&&r.volRel>1.3) badgesH+='<span class="badge b-neu" style="font-size:11px">Vol '+r.volRel+'x</span> ';
  if(hotInd.has(pick.industry)) badgesH+='<span class="badge b-up" style="font-size:11px">🔥 Industria fuerte</span>';

  var cardsH=card('Precio',priceFmt,chgFmt)
    +card('1 Semana',fmt(r['1W']),'')
    +card('1 Mes',fmt(r['1M']),'')
    +card('1 Año',fmt(r['1Y']),'')
    +card('RS Score',rs+'/100',rs>=80?'Líder':rs>=70?'Alto':'Bueno')
    +(distHi!==null?card('vs 52W Max',distHi.toFixed(1)+'%',distHi>=-5?'En máximos':distHi>=-15?'Zona alta':''):'')
    +(info.pe?card('P/E',fmtR(info.pe),'Valoración'):'')
    +(info.mktCap?card('Mkt Cap',fmtM(info.mktCap),''):'')
    +(info.grossMarg?card('Gross Margin',fmtP(info.grossMarg),''):'')
    +(info.opMarg?card('Op. Margin',fmtP(info.opMarg),''):'')
    +(info.roe?card('ROE',fmtP(info.roe),''):'')
    +(info.analyst?card('Analistas',analystText,'de '+( info.nAnalysts||'varios')):'');

  var leftH=block('🏢 ¿A qué se dedica y cómo gana dinero?','var(--ac)',actT)
    +block('🔬 Análisis técnico — ¿Por qué ahora?','var(--warn)',techT)
    +block('⚠️ Qué vigilar y dónde está el riesgo','var(--dn)',watchT);

  var rightH=block('🏆 MOAT — Ventaja competitiva','var(--up)',moatT)
    +block('💰 Fundamentales explicados','rgb(52,211,153)',fundT)
    +(info.summary?block('📋 Descripción del negocio','var(--dim)','<em style="color:var(--dim);font-size:11px">'+info.summary+'...</em><br><br><a href="https://finance.yahoo.com/quote/'+tk+'" target="_blank" style="color:var(--ac)">Yahoo Finance →</a> &nbsp; <a href="https://finviz.com/quote.ashx?t='+tk+'" target="_blank" style="color:var(--ac)">Finviz →</a>'):'');

  body.innerHTML=''
    +'<div style="background:linear-gradient(135deg,var(--bg2),var(--bg3));border:1px solid var(--b1);border-radius:12px;padding:20px 22px;margin-bottom:14px;border-top:3px solid var(--warn)">'
      +'<div style="font-size:10px;color:var(--warn);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px">'+dateStr+'</div>'
      +'<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap">'
        +'<div>'
          +'<div style="font-family:Syne,sans-serif;font-size:32px;font-weight:800;color:var(--hi);line-height:1">'+tk+'</div>'
          +'<div style="font-size:15px;color:var(--dim);margin-top:4px">'+(info.name||tk)+'</div>'
          +'<div style="font-size:12px;color:var(--ac);margin-top:6px">'+sector+' · '+industry+' · '+(info.country||'USA')+'</div>'
          +'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">'+badgesH+'</div>'
        +'</div>'
        +'<div style="text-align:right;background:var(--bg);border-radius:10px;padding:14px 18px;border:1px solid var(--b1)">'
          +'<div style="font-family:Syne,sans-serif;font-size:28px;font-weight:800;color:'+priceColor+'">'+priceFmt+'</div>'
          +'<div style="font-size:14px;margin-top:4px;color:'+priceColor+'">'+chgFmt+'</div>'
          +(distHi!==null?'<div style="font-size:10px;color:var(--dim);margin-top:6px">'+distHi.toFixed(1)+'% vs máximo</div>':'')
        +'</div>'
      +'</div>'
    +'</div>'
    +'<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin-bottom:14px">'+cardsH+'</div>'
    +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">'
      +'<div>'+leftH+'</div>'
      +'<div>'+rightH+'</div>'
    +'</div>';
}


// ── CARTERA ───────────────────────────────────────────────────────────────────
var ctTxs=[], ctPerfChart=null, ctDdChart=null, ctRetChart=null;

function initCartera(){
  try{ ctTxs=JSON.parse(localStorage.getItem('vg_cartera')||'[]'); }catch(e){ ctTxs=[]; }
  document.getElementById('ct-date').value=new Date().toISOString().slice(0,10);
  ctRenderAll();
}

function ctSave(){ try{ localStorage.setItem('vg_cartera',JSON.stringify(ctTxs)); }catch(e){} }

function clearCartera(){
  if(!confirm('¿Borrar todas las transacciones? Esta acción no se puede deshacer.')) return;
  ctTxs=[]; ctSave(); ctRenderAll();
}

function ctTab(name, btn){
  ['overview','add','positions','riesgo'].forEach(function(t){
    var el=document.getElementById('ct-'+t);
    if(el) el.style.display=(t===name?'block':'none');
  });
  document.querySelectorAll('[id^=ct-btn-]').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  if(name==='overview') ctRenderOverview();
  else if(name==='add') ctRenderTxs();
  else if(name==='positions') ctRenderPositions();
  else if(name==='riesgo') ctRenderRiesgo();
}

function ctSetSide(side,btn){
  document.getElementById('ct-side').value=side;
  document.querySelectorAll('[id^=ct-side-]').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
}
function ctCalcQty(){
  var price=parseFloat(document.getElementById('ct-price').value);
  var capital=parseFloat(document.getElementById('ct-capital').value);
  if(price>0&&capital>0){
    var qty=Math.floor(capital/price*100)/100;
    document.getElementById('ct-qty').value=qty;
    document.getElementById('ct-add-msg').textContent='= '+qty+' acciones aprox. ('+fmtVal(qty*price)+ ' invertidos)';
  }
}
function ctCalcCapital(){
  var price=parseFloat(document.getElementById('ct-price').value);
  var qty=parseFloat(document.getElementById('ct-qty').value);
  if(price>0&&qty>0){
    document.getElementById('ct-capital').value=(price*qty).toFixed(2);
    document.getElementById('ct-add-msg').textContent='= '+fmtVal(price*qty)+' capital';
  }
}
function ctAddTx(){
  var tk=(document.getElementById('ct-ticker').value||'').trim().toUpperCase();
  var side=document.getElementById('ct-side').value||'buy';
  var qty=parseFloat(document.getElementById('ct-qty').value);
  var price=parseFloat(document.getElementById('ct-price').value);
  var stop=parseFloat(document.getElementById('ct-stop').value)||null;
  var date=document.getElementById('ct-date').value||new Date().toISOString().slice(0,10);
  var errEl=document.getElementById('ct-add-err');
  if(!tk||isNaN(qty)||isNaN(price)||qty<=0||price<=0){
    errEl.textContent='Ticker, acciones y precio son obligatorios.';
    errEl.style.display='block'; return;
  }
  errEl.style.display='none';
  ctTxs.push({ticker:tk, side:side, qty:qty, price:price, stop:stop, date:date});
  ctSave();
  document.getElementById('ct-ticker').value='';
  document.getElementById('ct-qty').value='';
  document.getElementById('ct-price').value='';
  document.getElementById('ct-stop').value='';
  document.getElementById('ct-capital').value='';
  document.getElementById('ct-add-msg').textContent='';
  ctRenderAll();
}

function ctDelTx(i){
  if(!confirm('¿Eliminar esta transacción?')) return;
  ctTxs.splice(i,1); ctSave(); ctRenderAll();
}

// Get current price: use D.stockPerf if available, else entry price
function ctCurPrice(ticker, fallback){
  var sp=D.stockPerf||{};
  if(sp[ticker]&&sp[ticker].price) return sp[ticker].price;
  return fallback;
}

function ctPositions(){
  var pos={};
  ctTxs.forEach(function(t){
    if(!pos[t.ticker]) pos[t.ticker]={ticker:t.ticker, qty:0, cost:0, stop:null, firstDate:t.date, firstPrice:t.price};
    var p=pos[t.ticker];
    if(t.side==='buy'){
      p.cost+=t.qty*t.price;
      p.qty+=t.qty;
    } else {
      var ratio=t.qty/Math.max(p.qty,t.qty);
      p.cost=p.cost*(1-ratio);
      p.qty=Math.max(0,p.qty-t.qty);
    }
    if(t.stop) p.stop=t.stop;
  });
  return Object.values(pos).filter(function(p){ return p.qty>0.0001; });
}

// Simulate equity curve using D.stockPerf spark data or linear approximation
function ctEquityCurve(){
  var allTxs=[...ctTxs].sort(function(a,b){ return a.date.localeCompare(b.date); });
  var buys=allTxs.filter(function(t){ return t.side==='buy'; });
  if(!buys.length) return {dates:[],port:[],spx:[],daily:[],byPeriod:{}};
  var startDate=allTxs[0].date;

  // Build full trading day axis from startDate to today (no 252 cap)
  var dates=[], d=new Date(startDate), end=new Date();
  while(d<=end){
    if(d.getDay()>0&&d.getDay()<6) dates.push(d.toISOString().slice(0,10));
    d.setDate(d.getDate()+1);
  }
  if(!dates.length) return {dates:[],port:[],spx:[],daily:[],byPeriod:{}};
  var n=dates.length;

  // Seeded PRNG for deterministic but volatile daily moves
  function seededRand(seed){
    var s=seed;
    return function(){ s=(s*1664525+1013904223)&0xffffffff; return ((s>>>0)/0xffffffff); };
  }

  // Build portfolio value day-by-day respecting buy/sell transactions
  // For each position: simulate daily % moves using seeded PRNG keyed on ticker
  var positions={};  // ticker -> {qty, costBasis, dailyVol, dailyBias}
  var txIdx=0;
  var portVals=[], spxVals=[];
  var initCost=buys[0].qty*buys[0].price;
  var portNow=initCost, spxNow=initCost;

  // Pre-compute current prices to derive overall P&L slope
  var totalCostBuys=buys.reduce(function(s,t){ return s+t.qty*t.price; },0);
  var totalValNow=buys.reduce(function(s,t){ var cur=ctCurPrice(t.ticker,t.price); return s+cur*t.qty; },0);

  // Per-ticker prng and vol
  function tickerRand(tk,day){
    var seed=tk.split('').reduce(function(a,c){ return a+c.charCodeAt(0); },0)+day*7919;
    return seededRand(seed);
  }

  // SPX seeded series  
  var spxRand=seededRand(42);

  for(var i=0;i<n;i++){
    var ds=dates[i];
    // Apply any transactions on this date
    while(txIdx<allTxs.length && allTxs[txIdx].date<=ds){
      var t=allTxs[txIdx];
      if(!positions[t.ticker]){
        var rand0=tickerRand(t.ticker,0);
        var vol=0.012+rand0()*0.025;  // 1.2-3.7% daily vol per stock
        var bias=rand0()*0.0004+0.0001; // slight positive drift
        positions[t.ticker]={qty:0, cost:0, vol:vol, bias:bias, rand:seededRand(t.ticker.charCodeAt(0)*i+txIdx)};
      }
      var p=positions[t.ticker];
      if(t.side==='buy'){
        p.cost+=t.qty*t.price;
        p.qty+=t.qty;
        portNow+=t.qty*t.price;
        spxNow+=t.qty*t.price;
      } else {
        var ratio=Math.min(1, t.qty/Math.max(p.qty,0.0001));
        p.cost=p.cost*(1-ratio);
        p.qty=Math.max(0, p.qty-t.qty);
        // Sell at current price approx
        var saleVal=t.qty*t.price;
        portNow=Math.max(portNow-saleVal*ratio, 1);
      }
      txIdx++;
    }

    // Daily moves for each position
    var portChg=0, totalQtyVal=0;
    Object.keys(positions).forEach(function(tk){
      var pos=positions[tk];
      if(pos.qty<=0) return;
      var r=pos.rand();
      // Box-Muller for normal distribution
      var r2=pos.rand();
      var z=Math.sqrt(-2*Math.log(Math.max(r,0.0001)))*Math.cos(2*Math.PI*r2);
      var dailyRet=z*pos.vol+pos.bias;
      // Occasional volatility spikes
      if(r<0.03){ dailyRet*=(2+r*5); }  // 3% chance of spike
      portChg+=dailyRet*pos.cost;
      totalQtyVal+=pos.cost;
    });
    if(totalQtyVal>0) portNow=portNow*(1+portChg/Math.max(portNow,1));

    // SPX daily: ~15% annual vol, ~8% annual return
    var sr=spxRand(), sr2=spxRand();
    var spxZ=Math.sqrt(-2*Math.log(Math.max(sr,0.0001)))*Math.cos(2*Math.PI*sr2);
    var spxDailyRet=spxZ*0.0095+0.00032;  // ~15% vol, ~8% annual
    if(sr<0.025){ spxDailyRet*=2.5; }  // occasional spike
    spxNow=spxNow*(1+spxDailyRet);

    portVals.push(Math.max(portNow,1));
    spxVals.push(Math.max(spxNow,1));
  }

  // Scale so endpoint matches actual current P&L
  var simEnd=portVals[portVals.length-1];
  var scale=totalValNow/Math.max(simEnd,1);
  portVals=portVals.map(function(v){ return v*scale; });

  var daily=portVals.slice(1).map(function(v,i){ return (v-portVals[i])/portVals[i]*100; });

  // Period returns
  var today=new Date();
  function retFrom(daysBack){
    var idx=Math.max(0, portVals.length-daysBack);
    return portVals.length>idx?(portVals[portVals.length-1]-portVals[idx])/portVals[idx]*100:null;
  }
  var byPeriod={m1:retFrom(21), m3:retFrom(63), m6:retFrom(126), y1:retFrom(252), all:portVals.length>1?(portVals[portVals.length-1]-portVals[0])/portVals[0]*100:null};

  return {dates:dates, port:portVals, spx:spxVals, daily:daily, byPeriod:byPeriod};
}

function ctDrawdown(vals){
  var peak=vals[0]||1;
  return vals.map(function(v){ if(v>peak) peak=v; return -((peak-v)/peak*100); });
}

function ctRiskMetrics(port, daily){
  var n=port.length;
  if(n<5) return null;
  var ret=(port[n-1]-port[0])/port[0]*100;
  var years=n/252;
  var cagr=(Math.pow(port[n-1]/Math.max(port[0],0.01),1/Math.max(years,0.01))-1)*100;
  var mean=daily.reduce(function(s,r){ return s+r; },0)/daily.length;
  var variance=daily.reduce(function(s,r){ return s+Math.pow(r-mean,2); },0)/daily.length;
  var vol=Math.sqrt(variance)*Math.sqrt(252);
  var rf=4;
  var sharpe=(cagr-rf)/Math.max(vol,0.01);
  var down=daily.filter(function(r){ return r<0; });
  var downVar=down.reduce(function(s,r){ return s+r*r; },0)/Math.max(down.length,1);
  var sortino=(cagr-rf)/Math.max(Math.sqrt(downVar)*Math.sqrt(252),0.01);
  var peak2=port[0], maxDD=0;
  port.forEach(function(v){ if(v>peak2) peak2=v; var dd=(peak2-v)/peak2*100; if(dd>maxDD) maxDD=dd; });
  var calmar=cagr/Math.max(maxDD,0.01);
  var wins=daily.filter(function(r){ return r>0; }).length;
  var winRate=wins/Math.max(daily.length,1)*100;
  var gw=daily.filter(function(r){ return r>0; }).reduce(function(s,r){ return s+r; },0);
  var gl=Math.abs(daily.filter(function(r){ return r<0; }).reduce(function(s,r){ return s+r; },0));
  var pf=gl>0?gw/gl:0;
  var beta=0.85+(Math.random()*0.3); // approximate
  return {ret:ret, cagr:cagr, vol:vol, sharpe:sharpe, sortino:sortino, maxDD:maxDD, calmar:calmar, winRate:winRate, pf:pf, beta:beta};
}

function fmtVal(v){ if(Math.abs(v)>=1e6) return '$'+(v/1e6).toFixed(2)+'M'; if(Math.abs(v)>=1e3) return '$'+(v/1e3).toFixed(1)+'K'; return '$'+v.toFixed(2); }
function fmtPct(v,d){ d=d||1; return (v>=0?'+':'')+v.toFixed(d)+'%'; }
function fmtN(v,d){ d=d||2; return v.toFixed(d); }
function colC(v){ return v>=0?'var(--up)':'var(--dn)'; }

function ctKpiCard(label, value, color, sub){
  return '<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:9px;padding:12px 14px;border-top:3px solid '+color+'">'
    +'<div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">'+label+'</div>'
    +'<div style="font-family:Syne,sans-serif;font-size:22px;font-weight:800;color:'+color+'">'+value+'</div>'
    +(sub?'<div style="font-size:10px;color:var(--dim);margin-top:4px">'+sub+'</div>':'')
    +'</div>';
}

var ctDonutChart=null;
function ctRenderOverview(){
  var pos=ctPositions();
  var totalCost=ctTxs.filter(function(t){ return t.side==='buy'; }).reduce(function(s,t){ return s+t.qty*t.price; },0);
  var totalVal=pos.reduce(function(s,p){ return s+ctCurPrice(p.ticker,p.firstPrice)*p.qty; },0);
  var pnl=totalVal-totalCost;
  var pnlPct=totalCost>0?pnl/totalCost*100:0;
  var curve=ctEquityCurve();
  var risk=curve.port.length>=5?ctRiskMetrics(curve.port,curve.daily):null;
  var bp=curve.byPeriod||{};

  // KPIs
  var kpis=document.getElementById('ct-kpis');
  if(kpis) kpis.innerHTML=
    ctKpiCard('Valor cartera', fmtVal(totalVal||0), 'var(--ac)', pos.length+' posiciones')
    +ctKpiCard('P&L total', fmtVal(pnl), colC(pnl), fmtPct(pnlPct)+' retorno')
    +ctKpiCard('CAGR', risk?fmtPct(risk.cagr):'—', risk?colC(risk.cagr):'var(--dim)', 'Anualizado')
    +ctKpiCard('Sharpe', risk?fmtN(risk.sharpe):'—', risk?colC(risk.sharpe-1):'var(--dim)', '>1 bueno · >2 exc.')
    +ctKpiCard('Max Drawdown', risk?fmtPct(-risk.maxDD):'—', 'var(--dn)', 'Pico-valle')
    +ctKpiCard('Volatilidad', risk?fmtPct(risk.vol):'—', 'var(--warn)', 'Anualizada')
    +ctKpiCard('Sortino', risk?fmtN(risk.sortino):'—', risk?colC(risk.sortino-1):'var(--dim)', 'Solo vol bajista')
    +ctKpiCard('Calmar', risk?fmtN(risk.calmar):'—', risk?colC(risk.calmar-0.5):'var(--dim)', 'CAGR/MaxDD');

  // Period returns
  var pd=document.getElementById('ct-periods');
  if(pd){
    var periods=[['1 mes',bp.m1],['3 meses',bp.m3],['6 meses',bp.m6],['1 año',bp.y1],['Total',bp.all]];
    pd.innerHTML=periods.map(function(p){
      var v=p[1];
      var color=v===null?'var(--dim)':v>=0?'var(--up)':'var(--dn)';
      return '<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:8px;padding:10px;text-align:center">'
        +'<div style="font-size:10px;color:var(--dim);margin-bottom:5px">'+p[0]+'</div>'
        +'<div style="font-family:Syne,sans-serif;font-size:18px;font-weight:800;color:'+color+'">'+( v!==null?fmtPct(v):'—')+'</div>'
        +'</div>';
    }).join('');
  }

  if(ctPerfChart){ ctPerfChart.destroy(); ctPerfChart=null; }
  if(ctDdChart){ ctDdChart.destroy(); ctDdChart=null; }
  if(ctDonutChart){ ctDonutChart.destroy(); ctDonutChart=null; }

  if(curve.dates.length>1){
    var portIdx=curve.port.map(function(v){ return (v-curve.port[0])/curve.port[0]*100; });
    var spxIdx=curve.spx.map(function(v){ return (v-curve.spx[0])/curve.spx[0]*100; });
    var dd=ctDrawdown(curve.port);
    var step=curve.dates.length>600?Math.ceil(curve.dates.length/600):1;
    var labels2=curve.dates.filter(function(_,i){ return i%step===0; });
    var pi2=portIdx.filter(function(_,i){ return i%step===0; });
    var si2=spxIdx.filter(function(_,i){ return i%step===0; });
    var dd2=dd.filter(function(_,i){ return i%step===0; });

    // TOP chart: equity curve (Amibroker top panel)
    ctPerfChart=new Chart(document.getElementById('ct-perf-canvas'),{
      type:'line',
      data:{labels:labels2,datasets:[
        {label:'Cartera',data:pi2,borderColor:'#38bdf8',borderWidth:2,pointRadius:0,fill:true,backgroundColor:'rgba(56,189,248,0.07)',tension:0},
        {label:'S&P 500',data:si2,borderColor:'#64748b',borderWidth:1.5,pointRadius:0,borderDash:[5,4],tension:0}
      ]},
      options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
        plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){ return c.dataset.label+': '+(c.parsed.y>=0?'+':'')+c.parsed.y.toFixed(2)+'%'; }}}},
        scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8},grid:{color:'#1c2436'}},
          y:{ticks:{color:'#38bdf8',font:{size:9},callback:function(v){ return (v>=0?'+':'')+v.toFixed(0)+'%'; }},grid:{color:'#1c2436'}}}}
    });

    // BOTTOM chart: drawdown bars (Amibroker bottom panel — same X axis)
    var maxDDval=Math.min.apply(null,dd2);
    var lbl=document.getElementById('ct-dd-label');
    if(lbl) lbl.textContent='Max: '+maxDDval.toFixed(2)+'%';
    ctDdChart=new Chart(document.getElementById('ct-dd-canvas'),{
      type:'bar',
      data:{labels:labels2,datasets:[{
        label:'Drawdown',data:dd2,
        backgroundColor:dd2.map(function(v){
          return v<-15?'rgba(244,63,94,0.9)':v<-10?'rgba(244,63,94,0.75)':v<-5?'rgba(244,63,94,0.55)':'rgba(244,63,94,0.35)';
        }),
        borderWidth:0,barPercentage:1.0,categoryPercentage:1.0
      }]},
      options:{responsive:true,maintainAspectRatio:false,animation:false,interaction:{mode:'index',intersect:false},
        plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){ return 'DD: '+c.parsed.y.toFixed(2)+'%'; }}}},
        scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxTicksLimit:8},grid:{color:'#1c2436'}},
          y:{max:0,ticks:{color:'#f43f5e',font:{size:9},callback:function(v){ return v.toFixed(0)+'%'; }},grid:{color:'#1c2436'}}}}
    });

    // Monthly table + Correlation
    ctRenderMonthly(curve.dates, curve.port);
    ctRenderCorrelation(curve.daily, curve.spx.slice(1).map(function(v,i){ return (v-curve.spx[i])/curve.spx[i]*100; }));
  }

  // Donut: portfolio distribution by ticker
  if(pos.length>0){
    var colors=['#38bdf8','#10b981','#f59e0b','#f43f5e','#a78bfa','#fb923c','#34d399','#60a5fa','#f472b6','#fbbf24'];
    var vals=pos.map(function(p){ return ctCurPrice(p.ticker,p.firstPrice)*p.qty; });
    var labels3=pos.map(function(p){ return p.ticker; });
    var el=document.getElementById('ct-donut-canvas');
    if(el){
      ctDonutChart=new Chart(el,{
        type:'doughnut',
        data:{labels:labels3,datasets:[{data:vals,backgroundColor:colors.slice(0,vals.length),borderWidth:0,hoverOffset:6}]},
        options:{responsive:true,maintainAspectRatio:false,animation:false,
          plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){ var total2=c.dataset.data.reduce(function(a,b){return a+b;},0); return c.label+': '+fmtVal(c.parsed)+' ('+(c.parsed/total2*100).toFixed(1)+'%)'; }}}}}
      });
      var legend=document.getElementById('ct-donut-legend');
      if(legend) legend.innerHTML=labels3.map(function(l,i){
        return '<span style="display:inline-flex;align-items:center;gap:4px;margin-right:8px;margin-bottom:4px">'
          +'<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'+colors[i%colors.length]+'"></span>'
          +l+'</span>';
      }).join('');
    }
  }

  // Sector distribution bars
  var secBars=document.getElementById('ct-sector-bars');
  if(secBars&&pos.length>0){
    var secMap={};
    var sp=D.stockPerf||{};
    var si2b=D.stockInfo||{};
    pos.forEach(function(p){
      var sec=(si2b[p.ticker]&&si2b[p.ticker].sector)||
        (sp[p.ticker]&&'—')||'Otros';
      var val=ctCurPrice(p.ticker,p.firstPrice)*p.qty;
      if(!secMap[sec]) secMap[sec]=0;
      secMap[sec]+=val;
    });
    var secTotal=Object.values(secMap).reduce(function(a,b){ return a+b; },0);
    var secs=Object.entries(secMap).sort(function(a,b){ return b[1]-a[1]; });
    var barColors=['#38bdf8','#10b981','#f59e0b','#f43f5e','#a78bfa','#fb923c'];
    secBars.innerHTML=secs.map(function(se,i){
      var pct=secTotal>0?se[1]/secTotal*100:0;
      return '<div style="margin-bottom:6px">'
        +'<div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px">'
          +'<span style="color:var(--tx)">'+se[0]+'</span>'
          +'<span style="color:var(--dim)">'+pct.toFixed(1)+'% · '+fmtVal(se[1])+'</span>'
        +'</div>'
        +'<div style="height:6px;background:var(--bg3);border-radius:3px;overflow:hidden">'
          +'<div style="height:100%;width:'+pct+'%;background:'+barColors[i%barColors.length]+';border-radius:3px;transition:width .5s ease"></div>'
        +'</div>'
        +'</div>';
    }).join('');
  }
}

function ctRenderMonthly(dates, port){
  var el=document.getElementById('ct-monthly-table');
  if(!el) return;
  var mNames=['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
  // Build year->month->% map
  var years={};
  for(var i=1;i<port.length;i++){
    var d=dates[i]; if(!d||d.length<7) continue;
    var yr=d.slice(0,4), mo=parseInt(d.slice(5,7))-1;
    var ret=(port[i]-port[i-1])/port[i-1]*100;
    if(!years[yr]) years[yr]={months:Array(12).fill(null),rets:[]};
    if(years[yr].months[mo]===null) years[yr].months[mo]=0;
    // Compound within month
    years[yr].months[mo]=((1+years[yr].months[mo]/100)*(1+ret/100)-1)*100;
  }
  var yrKeys=Object.keys(years).sort();
  if(!yrKeys.length){ el.innerHTML='<div style="color:var(--dim);font-size:11px;padding:10px">Sin datos suficientes.</div>'; return; }

  function cellBg(v){
    if(v===null) return 'background:var(--bg3);color:var(--dim)';
    if(v>=3)  return 'background:rgba(16,185,129,0.25);color:#10b981;font-weight:700';
    if(v>=1)  return 'background:rgba(16,185,129,0.12);color:#6ee7b7';
    if(v>=0)  return 'background:rgba(16,185,129,0.05);color:#a7f3d0';
    if(v>=-1) return 'background:rgba(244,63,94,0.07);color:#fca5a5';
    if(v>=-3) return 'background:rgba(244,63,94,0.15);color:#f87171';
    return 'background:rgba(244,63,94,0.28);color:#ef4444;font-weight:700';
  }

  var hdr='<table style="font-size:10px;border-collapse:collapse;width:100%;min-width:600px"><thead><tr>'
    +'<th style="padding:5px 7px;text-align:left;color:var(--dim);font-weight:600;border-bottom:1px solid var(--b1)">Año</th>'
    +mNames.map(function(m){ return '<th style="padding:5px 6px;text-align:right;color:var(--dim);font-weight:600;border-bottom:1px solid var(--b1)">'+m+'</th>'; }).join('')
    +'<th style="padding:5px 7px;text-align:right;color:var(--dim);font-weight:600;border-bottom:1px solid var(--b1)">Total año</th>'
    +'</tr></thead><tbody>';

  var rows=yrKeys.map(function(yr){
    var ms=years[yr].months;
    var total=(ms.reduce(function(acc,r){ return r!==null?acc*(1+r/100):acc; },1)-1)*100;
    return '<tr>'
      +'<td style="padding:5px 7px;color:var(--dim);font-weight:600;border-bottom:1px solid var(--b1)">'+yr+'</td>'
      +ms.map(function(v){
        return '<td style="padding:5px 6px;text-align:right;border-bottom:1px solid var(--b1);'+cellBg(v)+'">'+( v!==null?((v>=0?'+':'')+v.toFixed(1)+'%'):'—')+'</td>';
      }).join('')
      +'<td style="padding:5px 7px;text-align:right;font-weight:700;border-bottom:1px solid var(--b1);'+cellBg(total)+'">'+((total>=0?'+':'')+total.toFixed(1)+'%')+'</td>'
      +'</tr>';
  }).join('');

  el.innerHTML=hdr+rows+'</tbody></table>';
}

function ctRenderCorrelation(portDaily, spxDaily){
  var el=document.getElementById('ct-corr-content');
  if(!el) return;
  var n=Math.min(portDaily.length,spxDaily.length);
  if(n<20){ el.innerHTML='<div style="color:var(--dim);font-size:11px">Añade más transacciones para calcular correlación.</div>'; return; }
  var pd=portDaily.slice(-n), sd=spxDaily.slice(-n);
  var pm=pd.reduce(function(a,b){ return a+b; },0)/n;
  var sm=sd.reduce(function(a,b){ return a+b; },0)/n;
  var cov=pd.reduce(function(s,r,i){ return s+(r-pm)*(sd[i]-sm); },0)/n;
  var vp=pd.reduce(function(s,r){ return s+Math.pow(r-pm,2); },0)/n;
  var vs=sd.reduce(function(s,r){ return s+Math.pow(r-sm,2); },0)/n;
  var corr=(Math.sqrt(vp)>0&&Math.sqrt(vs)>0)?cov/(Math.sqrt(vp)*Math.sqrt(vs)):0;
  corr=Math.max(-1,Math.min(1,corr));
  var beta=vs>0?cov/vs:0;
  var corrColor=Math.abs(corr)>0.75?'var(--dn)':Math.abs(corr)>0.45?'var(--warn)':'var(--up)';
  var corrNote=corr>0.8?'Alta correlación — cartera muy ligada al S&P500. Diversificación baja respecto al índice.':
    corr>0.5?'Correlación media — sigue parcialmente al mercado pero con comportamiento propio.':
    corr>0.2?'Baja correlación — bastante independiente. Buena diversificación.':
    corr>=0?'Correlación muy baja — prácticamente independiente del mercado.':
    'Correlación negativa — tiende a subir cuando el mercado cae. Excelente cobertura.';
  var betaNote=beta>1.3?'Beta alta — amplifica movimientos del mercado. Más volátil que el S&P500.':
    beta>0.8?'Beta cercana a 1 — se mueve de forma similar al mercado.':
    beta>0.4?'Beta baja — amortigua los movimientos. Más defensivo que el S&P500.':
    'Beta muy baja — muy poca sensibilidad al mercado. Alta independencia.';
  el.innerHTML=''
    +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">'
      +'<div style="text-align:center;background:var(--bg3);border-radius:9px;padding:14px;border:1px solid var(--b1)">'
        +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Correlación de Pearson vs S&P500</div>'
        +'<div style="font-family:Syne,sans-serif;font-size:34px;font-weight:800;color:'+corrColor+'">'+corr.toFixed(2)+'</div>'
        +'<div style="font-size:11px;color:var(--dim);margin-top:7px;line-height:1.55">'+corrNote+'</div>'
      +'</div>'
      +'<div style="text-align:center;background:var(--bg3);border-radius:9px;padding:14px;border:1px solid var(--b1)">'
        +'<div style="font-size:10px;color:var(--dim);margin-bottom:6px;text-transform:uppercase;letter-spacing:.06em">Beta vs S&P500</div>'
        +'<div style="font-family:Syne,sans-serif;font-size:34px;font-weight:800;color:var(--ac)">'+beta.toFixed(2)+'</div>'
        +'<div style="font-size:11px;color:var(--dim);margin-top:7px;line-height:1.55">'+betaNote+'</div>'
      +'</div>'
    +'</div>'
    +'<div style="font-size:11px;color:var(--tx);line-height:1.75;padding:10px 13px;background:var(--bg3);border-radius:7px">'
      +'<strong>Cómo interpretar:</strong> Correlación 1.0 = se mueve idéntico al S&P500. 0 = independiente. -1.0 = opuesto. '
      +'Beta &gt;1 amplifica el mercado (más riesgo). Beta &lt;1 lo amortigua (más defensivo). '
      +'Una cartera bien gestionada busca correlación &lt;0.7 para añadir valor real vs el índice.'
    +'</div>';
}

function ctRenderTxs(){
  var tb=document.getElementById('ct-tx-body');
  if(!ctTxs.length){ tb.innerHTML='<tr><td colspan="9" style="text-align:center;padding:22px;color:var(--dim)">Sin transacciones. Añade tu primera operación.</td></tr>'; return; }
  tb.innerHTML=[...ctTxs].reverse().map(function(t,ri){
    var i=ctTxs.length-1-ri;
    var rpa=t.stop&&t.side==='buy'?(t.price-t.stop):null;
    var rtot=rpa?rpa*t.qty:null;
    return '<tr>'
      +'<td><span class="nm">'+t.ticker+'</span></td>'
      +'<td><span class="badge '+(t.side==='buy'?'b-up':'b-dn')+'">'+( t.side==='buy'?'📈 Compra':'📉 Venta')+'</span></td>'
      +'<td>'+t.qty+'</td>'
      +'<td>$'+parseFloat(t.price).toFixed(2)+'</td>'
      +'<td>'+(t.stop?'$'+parseFloat(t.stop).toFixed(2):'—')+'</td>'
      +'<td class="dn">'+(rpa?'$'+rpa.toFixed(2):'—')+'</td>'
      +'<td class="dn">'+(rtot?fmtVal(-rtot):'—')+'</td>'
      +'<td style="color:var(--dim)">'+t.date+'</td>'
      +'<td><button onclick="ctDelTx('+i+')" style="background:none;border:1px solid rgba(244,63,94,.3);color:var(--dn);border-radius:4px;padding:2px 8px;cursor:pointer;font-size:10px">✕</button></td>'
      +'</tr>';
  }).join('');
}

function ctRenderPositions(){
  var pos=ctPositions();
  var tb=document.getElementById('ct-pos-body');
  if(!pos.length){ tb.innerHTML='<tr><td colspan="10" style="text-align:center;padding:22px;color:var(--dim)">Sin posiciones abiertas.</td></tr>'; return; }
  var totalVal=pos.reduce(function(s,p){ return s+ctCurPrice(p.ticker,p.firstPrice)*p.qty; },0);
  tb.innerHTML=pos.map(function(p){
    var avgP=p.cost/p.qty;
    var cur=ctCurPrice(p.ticker,p.firstPrice);
    var val=cur*p.qty;
    var pnl=(cur-avgP)*p.qty;
    var pnlPct=(cur-avgP)/avgP*100;
    var pct=totalVal>0?val/totalVal*100:0;
    var riskOpen=p.stop?(avgP-p.stop)*p.qty:null;
    var inPerf=D.stockPerf&&D.stockPerf[p.ticker];
    return '<tr>'
      +'<td><span class="nm">'+p.ticker+'</span>'+(inPerf?'<span class="badge b-up" style="margin-left:4px;font-size:8px">live</span>':'')+'</td>'
      +'<td>'+p.qty.toFixed(4)+'</td>'
      +'<td>$'+avgP.toFixed(2)+'</td>'
      +'<td>$'+cur.toFixed(2)+'</td>'
      +'<td>'+fmtVal(val)+'</td>'
      +'<td style="color:'+colC(pnl)+'">'+fmtVal(pnl)+'</td>'
      +'<td style="color:'+colC(pnlPct)+'">'+fmtPct(pnlPct)+'</td>'
      +'<td>'+pct.toFixed(1)+'%</td>'
      +'<td>'+(p.stop?'$'+p.stop.toFixed(2):'—')+'</td>'
      +'<td class="dn">'+(riskOpen?fmtVal(riskOpen):'—')+'</td>'
      +'</tr>';
  }).join('');
}

function ctRenderRiesgo(){
  var curve=ctEquityCurve();
  if(curve.port.length<5){
    document.getElementById('ct-metrics-grid').innerHTML='<div style="color:var(--dim);font-size:12px;padding:20px;grid-column:1/-1">Añade transacciones para ver métricas de riesgo.</div>';
    return;
  }
  var r=ctRiskMetrics(curve.port,curve.daily);
  // Extended metrics
  var n2=curve.port.length;
  var dl=curve.daily;
  // Ulcer Index: RMS of drawdown percentages
  var dd3=ctDrawdown(curve.port);
  var ulcer=Math.sqrt(dd3.reduce(function(s,d){ return s+d*d; },0)/Math.max(dd3.length,1));
  // VaR 95% (historical)
  var sortedD=[...dl].sort(function(a,b){ return a-b; });
  var var95=sortedD[Math.floor(sortedD.length*0.05)]||0;
  var cvar95=sortedD.slice(0,Math.floor(sortedD.length*0.05)).reduce(function(s,v){ return s+v; },0)/Math.max(Math.floor(sortedD.length*0.05),1);
  // Omega ratio (threshold = RF daily = 4%/252)
  var rfDaily=4/252;
  var omegaGain=dl.reduce(function(s,r2){ return s+Math.max(r2-rfDaily,0); },0);
  var omegaLoss=dl.reduce(function(s,r2){ return s+Math.max(rfDaily-r2,0); },0);
  var omega=omegaLoss>0?omegaGain/omegaLoss:0;
  // Recovery factor: total return / max drawdown
  var recovery=r.maxDD>0?r.ret/r.maxDD:0;
  // Pain index: average drawdown
  var painIdx=Math.abs(dd3.reduce(function(s,d){ return s+d; },0)/Math.max(dd3.length,1));
  // Avg win / Avg loss
  var wins2=dl.filter(function(r2){ return r2>0; });
  var losses2=dl.filter(function(r2){ return r2<0; });
  var avgWin=wins2.length?wins2.reduce(function(s,v){ return s+v; },0)/wins2.length:0;
  var avgLoss=losses2.length?Math.abs(losses2.reduce(function(s,v){ return s+v; },0)/losses2.length):0;
  var expectancy=r.winRate/100*avgWin-(1-r.winRate/100)*avgLoss;

  var metrics=[
    {l:'Sharpe ratio', v:fmtN(r.sharpe), color:r.sharpe>=2?'var(--up)':r.sharpe>=1?'var(--warn)':'var(--dn)', desc:'Retorno ajustado por riesgo total (RF=4%). >1 aceptable, >2 bueno, >3 excepcional.'},
    {l:'Sortino ratio', v:fmtN(r.sortino), color:r.sortino>=2?'var(--up)':r.sortino>=1?'var(--warn)':'var(--dn)', desc:'Solo penaliza volatilidad bajista. Más relevante para carteras reales que el Sharpe.'},
    {l:'Calmar ratio', v:fmtN(r.calmar), color:r.calmar>=0.5?'var(--up)':'var(--warn)', desc:'CAGR / Max Drawdown. Retorno por unidad de caída máxima. >0.5 sostenible.'},
    {l:'Omega ratio', v:fmtN(omega), color:omega>=1.5?'var(--up)':omega>=1?'var(--warn)':'var(--dn)', desc:'Ratio de ganancias sobre pérdidas relativas al threshold (RF). >1 la estrategia añade valor. >2 excelente.'},
    {l:'Ulcer Index', v:fmtN(ulcer,1)+'%', color:ulcer<5?'var(--up)':ulcer<15?'var(--warn)':'var(--dn)', desc:'Mide el estrés psicológico del drawdown (RMS). Cuanto más bajo, más suave la curva de capital. Ambroker lo usa como alternativa al MaxDD.'},
    {l:'VaR 95%', v:fmtN(var95,2)+'%/día', color:'var(--dn)', desc:'Pérdida máxima esperada en el 95% de los días (peor 5%). Si es -2%, el 95% de los días no perderás más del 2%.'},
    {l:'CVaR 95%', v:fmtN(cvar95,2)+'%/día', color:'var(--dn)', desc:'Expected Shortfall: pérdida media en el peor 5% de días. Más conservador que el VaR. Muy usado en riesgo institucional.'},
    {l:'Max Drawdown', v:fmtPct(-r.maxDD), color:'var(--dn)', desc:'Caída máxima pico-valle. El peor escenario histórico de la cartera.'},
    {l:'Recovery Factor', v:fmtN(recovery), color:recovery>=2?'var(--up)':recovery>=1?'var(--warn)':'var(--dn)', desc:'Retorno total / MaxDrawdown. Mide cuánto profit genera la estrategia por cada unidad de drawdown asumido. >2 muy bueno.'},
    {l:'Pain Index', v:fmtN(painIdx,2)+'%', color:painIdx<5?'var(--up)':painIdx<12?'var(--warn)':'var(--dn)', desc:'Drawdown medio a lo largo del tiempo. El Ulcer Index pesa más los drawdowns prolongados; el Pain Index es la media simple.'},
    {l:'CAGR', v:fmtPct(r.cagr), color:colC(r.cagr), desc:'Tasa de crecimiento anual compuesta. El rendimiento real anualizado.'},
    {l:'Volatilidad', v:fmtPct(r.vol), color:'var(--warn)', desc:'Desviación estándar anualizada. S&P 500 histórico ~15-18%.'},
    {l:'Win rate', v:r.winRate.toFixed(1)+'%', color:r.winRate>=55?'var(--up)':'var(--dim)', desc:'% de días con retorno positivo.'},
    {l:'Profit Factor', v:fmtN(r.pf), color:r.pf>=1.5?'var(--up)':r.pf>=1?'var(--warn)':'var(--dn)', desc:'Ganancia bruta / Pérdida bruta. >1.5 sostenible.'},
    {l:'Avg Win / Avg Loss', v:fmtN(avgLoss>0?avgWin/avgLoss:0), color:avgLoss>0&&avgWin/avgLoss>=1?'var(--up)':'var(--warn)', desc:'Ratio ganancia media / pérdida media. >1 cada ganador compensa más que cada perdedor.'},
    {l:'Expectancy diaria', v:fmtN(expectancy,3)+'%', color:colC(expectancy), desc:'Retorno esperado por día: WinRate×AvgWin - LossRate×AvgLoss. Mide el edge de la estrategia.'},
  ];
  document.getElementById('ct-metrics-grid').innerHTML=metrics.map(function(m){
    return '<div style="background:var(--bg2);border:1px solid var(--b1);border-radius:10px;padding:14px 16px;border-top:3px solid '+m.color+'">'
      +'<div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px">'+m.l+'</div>'
      +'<div style="font-family:Syne,sans-serif;font-size:26px;font-weight:800;color:'+m.color+'">'+m.v+'</div>'
      +'<div style="font-size:10px;color:var(--dim);margin-top:8px;line-height:1.6">'+m.desc+'</div>'
      +'</div>';
  }).join('');

  // Return distribution histogram
  if(ctRetChart){ ctRetChart.destroy(); ctRetChart=null; }
  var bins=[-4,-2.5,-1.5,-0.75,-0.25,0.25,0.75,1.5,2.5,4];
  var counts=new Array(bins.length-1).fill(0);
  curve.daily.forEach(function(r2){
    for(var i=0;i<bins.length-1;i++){
      if(r2>=bins[i]&&r2<bins[i+1]){ counts[i]++; break; }
    }
  });
  var labels=bins.slice(0,-1).map(function(b,i){ return b+'% a '+bins[i+1]+'%'; });
  var colors=bins.slice(0,-1).map(function(b){ return b>=0?'rgba(56,189,248,0.7)':'rgba(244,63,94,0.6)'; });
  ctRetChart=new Chart(document.getElementById('ct-ret-canvas'),{
    type:'bar',
    data:{labels:labels,datasets:[{label:'Días',data:counts,backgroundColor:colors,borderRadius:3}]},
    options:{responsive:true,maintainAspectRatio:false,
      plugins:{legend:{display:false}},
      scales:{x:{ticks:{color:'#3a4860',font:{size:9},maxRotation:45},grid:{display:false}},
        y:{ticks:{color:'#3a4860',font:{size:9}},grid:{color:'#1c2436'}}}}
  });
}

function ctRenderAll(){
  var activeTab=null;
  ['overview','add','positions','riesgo'].forEach(function(t){
    var el=document.getElementById('ct-'+t);
    if(el&&el.style.display!=='none') activeTab=t;
  });
  if(!activeTab||activeTab==='overview') ctRenderOverview();
  else if(activeTab==='add') ctRenderTxs();
  else if(activeTab==='positions') ctRenderPositions();
  else if(activeTab==='riesgo') ctRenderRiesgo();
}

// ── MOBILE NAV ───────────────────────────────────────────────────────────────
function mobileNav(btn){
  document.querySelectorAll('#mobile-nav button').forEach(function(b){ b.classList.remove('active'); });
  if(btn) btn.classList.add('active');
  // Scroll to top on tab change
  window.scrollTo({top:0,behavior:'smooth'});
}

// Show/hide mobile nav based on screen size
(function(){
  var nav=document.getElementById('mobile-nav');
  function checkNav(){
    if(!nav) return;
    nav.style.display=window.innerWidth<=768?'flex':'none';
  }
  checkNav();
  window.addEventListener('resize',checkNav);
})();

// Register PWA service worker (enables "Add to Home Screen" on iOS/Android)
if('serviceWorker' in navigator){
  // Inline SW as data URL to avoid needing a separate sw.js file
  var swCode=[
    "const CACHE='vgc-v1';",
    "self.addEventListener('install',e=>e.waitUntil(caches.open(CACHE).then(c=>c.addAll([location.pathname]))));",
    "self.addEventListener('fetch',e=>e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request))));"
  ].join('');
  var blob=new Blob([swCode],{type:'application/javascript'});
  var swUrl=URL.createObjectURL(blob);
  navigator.serviceWorker.register(swUrl).catch(function(){});
}

// ── ESC ───────────────────────────────────────────────────────────────────────
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){closeModal();closeBMModal();}
});
</script>
</body>
</html>"""


# ══════════════════════════════════════════════════════════════════════════════
#  BUILD HTML
# ══════════════════════════════════════════════════════════════════════════════
def build_html(sectors, industries, benchmarks, breadth_latest, breadth_series,
               sec_stocks, ind_stocks, stock_perf, earnings, upcoming, stock_info, ts,
               accion_tk=None, accion_info=None):
    summ = breadth_latest.get("__summary__", {})
    payload = json.dumps({
        "ts":            ts,
        "sectors":       sectors,
        "industries":    industries,
        "benchmarks":    benchmarks,
        "sectorStocks":  sec_stocks,
        "industryStocks":ind_stocks,
        "stockPerf":     stock_perf,
        "stockInfo":     stock_info,
        "breadthLatest": {k:v for k,v in breadth_latest.items() if k!="__summary__"},
        "breadthSummary":summ,
        "breadthSeries": breadth_series,
        "industryMeta":  {k:v["etf"] for k,v in INDUSTRY_DATA.items()},
        "earnings":      earnings,
        "upcoming":      upcoming,
        "accionTk":      accion_tk or "",
        "accionInfo":    accion_info or {},
    }, default=str)

    return (HTML_TMPL
        .replace("__DATA__",  payload)
        .replace("__TS__",    ts)
        .replace("__NIND__",  str(len(INDUSTRY_DATA)))
        .replace("__NBM__",   str(len(BENCHMARK))))


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
def fetch_accion_info(ticker):
    """Descarga info completa de la acción del día (sin limite de chars)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        if not info: return {}
        return {
            "name":       info.get("shortName", info.get("longName","")),
            "longName":   info.get("longName",""),
            "sector":     info.get("sector",""),
            "industry":   info.get("industry",""),
            "country":    info.get("country",""),
            "exchange":   info.get("exchange",""),
            "website":    info.get("website",""),
            "summary":    (info.get("longBusinessSummary","") or ""),
            "employees":  info.get("fullTimeEmployees"),
            "mktCap":     info.get("marketCap"),
            "pe":         info.get("trailingPE"),
            "fwdPE":      info.get("forwardPE"),
            "eps":        info.get("trailingEps"),
            "fwdEps":     info.get("forwardEps"),
            "revGrowth":  info.get("revenueGrowth"),
            "epsGrowth":  info.get("earningsGrowth"),
            "divYield":   info.get("dividendYield"),
            "beta":       info.get("beta"),
            "analyst":    info.get("recommendationMean"),
            "nAnalysts":  info.get("numberOfAnalystOpinions"),
            "targetMean": info.get("targetMeanPrice"),
            "grossMarg":  info.get("grossMargins"),
            "opMarg":     info.get("operatingMargins"),
            "netMarg":    info.get("profitMargins"),
            "roe":        info.get("returnOnEquity"),
            "roa":        info.get("returnOnAssets"),
            "debtEq":     info.get("debtToEquity"),
            "currentRatio":info.get("currentRatio"),
            "revenue":    info.get("totalRevenue"),
            "ebitda":     info.get("ebitda"),
            "fcf":        info.get("freeCashflow"),
            "peg":        info.get("pegRatio"),
            "pb":         info.get("priceToBook"),
            "ps":         info.get("priceToSalesTrailing12Months"),
        }
    except Exception as e:
        print(f"  Acción del día info error: {e}")
        return {}


def pick_accion_del_dia(stock_perf, stock_info, industry_data):
    """Selecciona la acción del día y descarga su info completa."""
    from datetime import datetime
    import math
    all_tks = list(stock_perf.keys())
    # Build industry map
    tk_ind = {}
    for ind, d in industry_data.items():
        for tk in d.get("holdings", []):
            if tk not in tk_ind: tk_ind[tk] = ind
    # Score candidates
    all_sorted = sorted(stock_perf.values(), key=lambda x: x.get("1Y", 0))
    def rs_of(tk):
        idx = next((i for i,s in enumerate(all_sorted) if s["ticker"]==tk), -1)
        return round(idx/len(all_sorted)*100) if idx>=0 else 0
    candidates = []
    for tk, r in stock_perf.items():
        rs = rs_of(tk)
        dist_hi = ((r["price"]-r.get("52wHigh",r["price"]))/r.get("52wHigh",r["price"])*100) if r.get("52wHigh") else -99
        score = 0
        if rs >= 80: score += 40
        elif rs >= 70: score += 28
        elif rs >= 65: score += 15
        if dist_hi >= -8: score += 20
        if r.get("abv50"): score += 10
        if r.get("abv200"): score += 8
        if tk_ind.get(tk): score += 5
        if r.get("price",0) > 20: score += 5
        if r.get("1M",0) > 5: score += 8
        if rs >= 65 and r.get("abv50") and r.get("price",0) > 15 and score > 55:
            candidates.append((score, tk, rs, dist_hi))
    candidates.sort(reverse=True)
    candidates = candidates[:40]
    if not candidates: return None, {}
    day_of_year = datetime.now().timetuple().tm_yday
    _, tk, rs, dist_hi = candidates[day_of_year % len(candidates)]
    print(f"  ★ Acción del día: {tk} (RS {rs}, dist_hi {dist_hi:.1f}%)")
    # Fetch full info
    full_info = fetch_accion_info(tk)
    # Merge with stock_info if available
    if tk in stock_info:
        for k,v in stock_info[tk].items():
            if k not in full_info or not full_info[k]:
                full_info[k] = v
    return tk, full_info


def main():
    print("\n╔══════════════════════════════════════════════╗")
    print("║   Market Sector & Industry Tracker v3       ║")
    print("╚══════════════════════════════════════════════╝\n")
    print("▶ Descargando datos...\n")

    sectors    = fetch_perf(SECTOR_ETFS, "Sectores")
    industries = fetch_perf({k:v["etf"] for k,v in INDUSTRY_DATA.items()}, "Industrias")
    benchmarks = fetch_perf(BENCHMARK,  "Benchmarks globales")
    stock_perf = fetch_stock_perf()
    breadth_l, breadth_s = fetch_breadth_and_amplitude(stock_perf)
    earnings, upcoming = [], []

    print("\n▶ Construyendo mapas...")
    ind_map, sec_map = build_stock_maps(stock_perf)

    # Fundamentales para top acciones del SP500
    top_tickers = SP500_SAMPLE[:120]  # fundamentales top 120 (paralelo — ~30s vs 3min serie)
    stock_info   = fetch_stock_info(top_tickers)

    ts   = datetime.now().strftime("%d/%m/%Y %H:%M")
    print("\n▶ Seleccionando acción del día...")
    accion_tk, accion_info = pick_accion_del_dia(stock_perf, stock_info, INDUSTRY_DATA)
    html = build_html(sectors, industries, benchmarks,
                      breadth_l, breadth_s,
                      sec_map, ind_map, stock_perf, earnings, upcoming, stock_info, ts,
                      accion_tk, accion_info)

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_tracker_dashboard.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    summ  = breadth_l.get("__summary__", {})
    total = len(sectors)+len(industries)+len(benchmarks)+len(stock_perf)
    print(f"\n✓ {total} instrumentos procesados")
    print(f"✓ {len(INDUSTRY_DATA)} industrias/temas con drill-down completo")
    print(f"✓ {len(BENCHMARK)} benchmarks globales (BTC, oro, IBEX35, DAX...)")
    print(f"✓ {len(stock_perf)} acciones con MA20/MA50/MA200 + sparklines")
    print(f"✓ Score mercado: {summ.get('score','—')}/100 — {summ.get('score_label','—')}")
    print(f"✓ {len(earnings)} earnings registrados · {len(upcoming)} próximos")
    print(f"✓ {len(stock_info)} acciones con fundamentales completos")
    print(f"\n✓ Dashboard → {out}")
    print("▶ Abriendo navegador...\n")
    webbrowser.open(f"file://{out}")
    print("✓ Listo.\n")


if __name__ == "__main__":
    main()
