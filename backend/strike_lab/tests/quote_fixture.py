"""Historical GOOG comparison example."""
from app.models import StudyInput

def goog():
    rows=[]
    for k,c,p in [(275,7.59,3.67),(277.5,5.85,4.72),(280,4.66,6.13)]:
        rows.append(dict(strike=k,call=dict(last=c),put=dict(last=p)))
    return StudyInput(symbol='GOOG',spot=None,expiration='2026-11-06',valuationAt='2026-10-30T16:00:00-04:00',
                      rate=.05,timeRule='days',remainingDays=7,rows=rows)
