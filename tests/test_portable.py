import asyncio
import importlib
import json
import sys
import tomllib
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
p=importlib.import_module('Sol_trusted_identity.plugin')
c=importlib.import_module('Sol_trusted_identity.identity_core')

class PortableTests(unittest.TestCase):
 def test_defaults_and_safe_config(self):
  raw=tomllib.loads((ROOT/'config.toml').read_text(encoding='utf-8'))
  cfg=p.Config.model_validate(raw)
  self.assertFalse(cfg.plugin.enabled)
  self.assertFalse(cfg.qq_binding.confirmed)
  self.assertEqual(cfg.qq_binding.creator_qq,'')
  self.assertEqual(cfg.qq_binding.bot_qq,'')
  self.assertEqual(cfg.attention.users,[])
  self.assertEqual(cfg.qq_binding.creator_name,'')
 def test_synthetic_binding(self):
  cfg=p.Config()
  cfg.plugin.enabled=True
  cfg.qq_binding.creator_qq='800000001'
  cfg.qq_binding.bot_qq='900000001'
  cfg.qq_binding.confirmed=True
  settings,reason=p.resolve_settings(cfg)
  self.assertIsNone(reason)
  self.assertIsNone(settings.problem())
 def test_unconfirmed_binding(self):
  self.assertEqual(p.resolve_settings(p.Config())[1],'simple_confirmation_missing')
 def test_capture_and_verify(self):
  settings=c.Settings(enabled=True,binding_semantics_confirmed=True,native_single_sender_confirmed=True,single_source_confirmed=True,platform='qq',account_id='900000001',creator_uid='800000001',allow_missing_scope=True,all_sessions=True)
  engine=c.IdentityEngine(settings)
  sid=c.session_digest('qq','900000001',None,'800000001','700000001')
  message={'platform':'qq','account_id':'900000001','scope':None,'session_id':sid,'message_id':'-42','is_notify':False,'message_info':{'user_info':{'user_id':'800000001'},'group_info':{'group_id':'700000001'},'additional_config':{'napcat_message_type':'group'}},'raw_message':[{'type':'text','data':{'text':'hello'}}]}
  self.assertEqual(engine.capture(message),'cached')
  self.assertTrue(engine.verify(sid,'-42',{'msg_id':'-42'}).creator_verified)
  self.assertFalse(engine.verify(sid,'missing',{}).creator_verified)
 def test_planner_no_target_verdict_and_idempotence(self):
  plugin=p.create_plugin()
  plugin.set_plugin_config(p.Config().model_dump())
  original={'items':[{'item_type':'UserMessageItem','parts':[{'type':'text','text':'hello'}]}],'item_schema_version':1,'future_field':True}
  result=asyncio.run(plugin.planner_policy(**original))['modified_kwargs']
  own=[i for i in result['items'] if p.owned(i)]
  self.assertEqual(len(own),1)
  self.assertEqual(len(own[0]['parts']),1)
  self.assertNotIn('creator_verified',own[0]['parts'][0]['text'])
  again=asyncio.run(plugin.planner_policy(**result))['modified_kwargs']
  self.assertEqual(len(again['items']),2)
  self.assertEqual(len(original['items']),1)
  self.assertTrue(again['future_field'])
 def test_unconfigured_replyer_never_authenticates(self):
  plugin=p.create_plugin()
  plugin.set_plugin_config(p.Config().model_dump())
  result=asyncio.run(plugin.replyer_fact(items=[],item_schema_version=1))['modified_kwargs']
  data=json.loads(result['items'][0]['parts'][1]['text'])
  self.assertFalse(data['creator_verified'])
  self.assertEqual(data['authorization'],'relationship_only')
 def test_registration(self):
  hooks={i['metadata']['hook'] for i in p.create_plugin().get_components()}
  self.assertEqual(hooks,{'chat.receive.before_process','maisaka.planner.before_request','maisaka.replyer.before_model_request'})

if __name__=='__main__': unittest.main(verbosity=2)
