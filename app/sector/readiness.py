"""Read-only downstream payload preparation; never changes a stock score."""
import math

def downstream_readiness(heat, *, primary_sector_id, stock_return_5d,
                         industry_return_5d, return_date, data_status='VALID'):
    same=primary_sector_id==heat.sector_id
    b1=same and heat.overall_status=='VALID' and heat.total_score is not None
    try:
        b2=same and return_date==heat.trade_date and str(data_status)=='VALID' and all(
            math.isfinite(float(x)) for x in (stock_return_5d,industry_return_5d))
    except (ValueError,TypeError):b2=False
    return dict(B1_READY=b1,B2_READY=b2,
        b1_input={'SectorHeatScore':heat.total_score,'score_coverage':heat.score_coverage} if b1 else None,
        b2_input={'stock_return_5d':stock_return_5d,'primary_industry_return_5d':industry_return_5d,
                  'excess_return_5d':stock_return_5d-industry_return_5d} if b2 else None,
        blockers=[] if b1 and b2 else [name for name,ok in [('B1: primary industry or complete heat unavailable',b1),('B2: aligned five-day returns unavailable',b2)] if not ok],
        integrated_into_stock_score=False)
