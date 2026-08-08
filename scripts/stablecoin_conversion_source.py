from __future__ import annotations

import csv, hashlib, io, time, urllib.error, urllib.request, zipfile
from pathlib import Path
from urllib.parse import urlparse
import numpy as np
import pandas as pd

START='2023-04-01T00:00:00Z'; END='2025-12-31T23:00:00Z'; ROWS=24144; TRAIN_END=10800
ROOT='https://data.binance.vision/data/spot/monthly/klines'
TARGET_HASHES={
 'BTCUSDT':('c282320ef644ae526eff1eec09b377868fc7ff73395506d65b6bfde6944a876d','30d38944190ebaa80e65308c806be34a572e03fea2f1e695887fbd24c2607cc6'),
 'ETHUSDT':('ecac9b3431afb8875cc00044aa18c434ebe2f4524caef55ed1afce31f9ab7bba','55f38818ed50e3cf0e97412aa22b3606ae7f4ec42f3a010cb14ef85b3f2f169f')}

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def canon(df:pd.DataFrame)->bytes:
 return df.reset_index(names='timestamp').to_csv(index=False,date_format='%Y-%m-%dT%H:%M:%S.%fZ',float_format='%.12g',lineterminator='\n').encode()
def months(): return [str(x) for x in pd.period_range('2023-04','2025-12',freq='M')]
def grid(m):
 p=pd.Period(m,freq='M'); return pd.date_range(p.start_time.tz_localize('UTC'),p.end_time.floor('h').tz_localize('UTC'),freq='h')
def get(url:str)->bytes:
 p=urlparse(url)
 if p.scheme!='https' or p.hostname!='data.binance.vision': raise ValueError('untrusted source URL')
 req=urllib.request.Request(url,headers={'User-Agent':'gpt-quant-research/1.0'}); last=None
 for k in range(4):
  try:
   with urllib.request.urlopen(req,timeout=45) as r:
    b=r.read(); final=urlparse(r.geturl())
   if final.scheme!='https' or final.hostname!='data.binance.vision' or not b: raise ValueError('invalid source response')
   return b
  except (urllib.error.URLError,urllib.error.HTTPError) as e:
   if isinstance(e,urllib.error.HTTPError) and e.code not in {408,429,500,502,503,504}: raise
   last=e; time.sleep(k+1)
 raise last or RuntimeError('source request failed')
def checksum(raw:bytes,name:str)->str:
 parts=raw.decode('ascii').strip().split(); dig=parts[0].lower(); declared=parts[-1].lstrip('*')
 if len(parts)<2 or len(dig)!=64 or declared!=name or any(c not in '0123456789abcdef' for c in dig): raise ValueError(f'{name}: bad checksum')
 return dig
def ts(raw:str,label:str):
 x=int(raw); unit,div=('us',3600000000) if x>10**14 else ('ms',3600000)
 if x%div: raise ValueError(f'{label}: off-grid timestamp')
 return pd.to_datetime(x,unit=unit,utc=True)
def parse(raw:bytes,name:str,m:str)->pd.DataFrame:
 z=zipfile.ZipFile(io.BytesIO(raw)); csvname=name[:-4]+'.csv'; members=[x for x in z.namelist() if not x.endswith('/')]
 if members!=[csvname]: raise ValueError(f'{name}: unexpected members')
 rows=[]
 with z.open(csvname) as h:
  for i,row in enumerate(csv.reader(io.TextIOWrapper(h,encoding='utf-8',newline='')),1):
   if not row: continue
   if len(row)!=12: raise ValueError(f'{name}: schema')
   try: t=ts(row[0],name)
   except ValueError:
    if i==1 and 'open' in row[0].lower(): continue
    raise
   o,hi,lo,c,q=map(float,(row[1],row[2],row[3],row[4],row[7])); a=np.asarray([o,hi,lo,c,q])
   if not np.isfinite(a).all() or min(o,hi,lo,c)<=0 or q<0 or hi<max(o,lo,c) or lo>min(o,hi,c): raise ValueError(f'{name}: invalid kline')
   rows.append((t,o,hi,lo,c,q))
 df=pd.DataFrame(rows,columns=['timestamp','open','high','low','close','quote_volume']).set_index('timestamp').sort_index()
 if df.index.has_duplicates or not df.index.equals(grid(m)): raise ValueError(f'{name}: monthly grid mismatch')
 return df
def acquire(symbol:str,persist:Path|None=None):
 frames=[]; rec=[]
 for m in months():
  name=f'{symbol}-1h-{m}.zip'; url=f'{ROOT}/{symbol}/1h/{name}'; cr=get(url+'.CHECKSUM'); zr=get(url)
  declared=checksum(cr,name); observed=sha(zr)
  if declared!=observed: raise ValueError(f'{name}: checksum mismatch')
  f=parse(zr,name,m); frames.append(f); rec.append({'month':m,'zip_sha256':observed,'checksum_sha256':sha(cr),'rows':len(f)})
  time.sleep(.01)
 df=pd.concat(frames).sort_index(); expected=pd.date_range(START,END,freq='h')
 if len(df)!=ROWS or df.index.has_duplicates or not df.index.equals(expected): raise ValueError(f'{symbol}: 24144H grid mismatch')
 raw=canon(df); meta={'provider':'Binance Public Data','market_type':'SPOT','symbol':symbol,'bar':'1H','rows':len(df),'start':str(df.index[0]),'end':str(df.index[-1]),'normalized_sha256':sha(raw),'training_prefix_sha256':sha(canon(df.iloc[:TRAIN_END])),'months':rec}
 if persist: (persist/f'binance-spot-{symbol}-1h.csv').write_bytes(raw)
 if symbol in TARGET_HASHES and (meta['normalized_sha256'],meta['training_prefix_sha256'])!=TARGET_HASHES[symbol]: raise ValueError(f'{symbol}: frozen identity mismatch')
 return df,meta
