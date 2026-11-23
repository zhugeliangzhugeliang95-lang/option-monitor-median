"""Append config versions for 3+1+3 selection; keep raw records and prior versions.
Run without --apply to inspect. This never submits trades.
"""
import argparse,json,sys
from pathlib import Path
from datetime import datetime,timezone
from dotenv import load_dotenv
ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env');sys.path.insert(0,str(ROOT/'backend'))
from sqlalchemy import select
from app.db import Session,Monitor,DB_PATH
from app.service import config_for,revise
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--apply',action='store_true'); args=parser.parse_args()
with Session() as db:
    monitors=list(db.scalars(select(Monitor).where(Monitor.active==True)))
    before=[dict(id=m.id,configId=m.config_id,config=config_for(db,m).payload) for m in monitors]
    if args.apply:
        path=DB_PATH.parent/('configs-before-median-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'.json')
        with path.open('x') as out:
            path.chmod(0o600);json.dump(before,out,ensure_ascii=False,indent=2)
        for m in monitors:
            old=config_for(db,m).payload
            revise(db,m,dict(nBelow=3,nAbove=3,strikeSelection='nearestCentered',
                optionPricePreset=old.get('optionPricePreset') if old.get('optionPricePreset') in ('MID','LAST') else 'MID',
                callPriceBasis='MID',putPriceBasis='MID'))
    print(json.dumps(dict(applied=args.apply,count=len(monitors),symbols=[x['config']['symbol'] for x in before]),ensure_ascii=False))
