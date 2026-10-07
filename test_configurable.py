import unittest
from configurable_rules import validate_settings,light_reason,decide
from work.fund_discovery_v2.models import FundSnapshot
class RulesTest(unittest.TestCase):
 def fund(self):return FundSnapshot('000001','测试基金',establish_date='2010-01-01',nav_date='2026-10-01',r1w=1,r1m=5,r3m=4,r6m=3,r1y=2,drawdown=12,drawdown_secondary=12)
 def test_pairs_independent(self):
  for key in ['order_1m_3m','order_3m_6m','order_6m_1y']:
   c=validate_settings({k:k==key for k in ['order_1m_3m','order_3m_6m','order_6m_1y']});self.assertTrue(light_reason(self.fund(),'2026-10-06',c))
 def test_disabled(self):
  c=validate_settings({k:False for k in ['order_1m_3m','order_3m_6m','order_6m_1y']});self.assertEqual(light_reason(self.fund(),'2026-10-06',c),'')
  self.assertTrue(decide(self.fund(),'2026-10-06',c).eligibility_passed)
 def test_drawdown(self):
  c=validate_settings({'order_1m_3m':False,'order_3m_6m':False,'order_6m_1y':False,'max_dd':10});f=decide(self.fund(),'2026-10-06',c);self.assertFalse(f.eligibility_passed);self.assertIn('10%',f.eligibility_blockers[0])
  c['dd_enabled']=False;self.assertTrue(decide(self.fund(),'2026-10-06',c).eligibility_passed)
 def test_invalid(self):
  for raw in [{'max_dd':float('nan')},{'watch_score':90},{'xxx':True},{'order_1m_3m':'false'},{'rough_limit':1.5}]:
   with self.assertRaises(ValueError):validate_settings(raw)
 def test_missing(self):
  f=self.fund();f.r1m=None;self.assertIn('数据不足',light_reason(f,'2026-10-06',validate_settings()))
if __name__=='__main__':unittest.main()
