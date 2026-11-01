import asyncio
import copy
import importlib
import json
import sys
import unittest
from pathlib import Path
from pydantic import ValidationError
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
p=importlib.import_module('Sol_trusted_identity.plugin')
c=importlib.import_module('Sol_trusted_identity.identity_core')


def config(name=''):
    return p.Config.model_validate({'plugin':{'enabled':True},'qq_binding':{'creator_qq':'800000001','bot_qq':'900000001','creator_name':name,'confirmed':True},'attention':{'users':[{'qq':'800000002','name':'小星'},{'qq':'800000003','name':'阿月'}]}})


def message(uid='800000001',mid='-42',group=True):
    gid='700000001' if group else None
    sid=c.session_digest('qq','900000001',None,uid,gid)
    info={'user_info':{'user_id':uid},'additional_config':{'napcat_message_type':'group' if group else 'private'}}
    if group: info['group_info']={'group_id':gid}
    return {'platform':'qq','account_id':'900000001','scope':None,'session_id':sid,'message_id':mid,'is_notify':False,'message_info':info,'raw_message':[{'type':'text','data':{'text':'hello'}}]}


class NamesTests(unittest.TestCase):
    def plugin(self,cfg=None):
        plug=p.create_plugin()
        plug.set_plugin_config((cfg or config()).model_dump())
        return plug

    def payload(self,plug,msg):
        self.assertEqual(plug.engine.capture(msg),'cached')
        result=asyncio.run(plug.replyer_fact(items=[],item_schema_version=1,session_id=msg['session_id'],reply_message_id=msg['message_id']))
        return json.loads(result['modified_kwargs']['items'][0]['parts'][1]['text'])

    def test_empty_name_still_verifies_without_invented_title(self):
        payload=self.payload(self.plugin(),message())
        self.assertTrue(payload['creator_verified'])
        self.assertIsNone(payload['creator_name'])
        self.assertNotIn('旅者',json.dumps(payload,ensure_ascii=False))
        self.assertNotIn('旅者',p.POLICY+p.CONFIRMATION+json.dumps(p.Config.model_json_schema(),ensure_ascii=False))

    def test_custom_creator_name_only_for_verified_sender(self):
        plug=self.plugin(config('主人'))
        self.assertEqual(self.payload(plug,message())['creator_name'],'主人')
        other=self.payload(plug,message('800000004','-43'))
        self.assertFalse(other['creator_verified'])
        self.assertIsNone(other['creator_name'])

    def test_each_focus_account_has_own_name_without_qq(self):
        plug=self.plugin()
        for uid,name in [('800000002','小星'),('800000003','阿月')]:
            payload=self.payload(plug,message(uid,uid))
            self.assertTrue(payload['focus_verified'])
            self.assertEqual(payload['focus_name'],name)
            self.assertNotIn(uid,json.dumps(payload))
            self.assertIsNone(payload['creator_name'])

    def test_private_chat_not_special_focus(self):
        payload=self.payload(self.plugin(),message('800000002',group=False))
        self.assertFalse(payload['focus_verified'])
        self.assertIsNone(payload['focus_name'])

    def test_disabled_focus_and_unknown_account_have_no_name(self):
        cfg=config();cfg.attention.enabled=False
        self.assertIsNone(self.payload(self.plugin(cfg),message('800000002'))['focus_name'])
        self.assertIsNone(self.payload(self.plugin(),message('800000004'))['focus_name'])

    def test_legacy_list_migrates_without_mutation_or_names(self):
        raw={'enabled':True,'qq_numbers':['800000002','800000002','800000003']}
        original=copy.deepcopy(raw)
        cfg=p.AttentionSection.model_validate(raw)
        self.assertEqual([(x.qq,x.name) for x in cfg.users],[('800000002',''),('800000003','')])
        self.assertEqual(raw,original)
        self.assertNotIn('qq_numbers',cfg.model_dump())
        plugcfg=config();plugcfg.attention=cfg
        payload=self.payload(self.plugin(plugcfg),message('800000002'))
        self.assertTrue(payload['focus_verified'])
        self.assertIsNone(payload['focus_name'])

    def test_sdk_normalization_preserves_legacy_attention(self):
        cfg=config().model_dump()
        cfg['attention']={'enabled':True,'qq_numbers':['800000002']}
        cfg['plugin']['config_version']='1.2.0'
        original=copy.deepcopy(cfg)
        plug=p.create_plugin()
        normalized,changed=plug.normalize_plugin_config(cfg)
        self.assertTrue(changed)
        self.assertEqual(normalized['attention']['users'],[{'qq':'800000002','name':''}])
        self.assertEqual(normalized['plugin']['config_version'],'1.2.0')
        self.assertEqual(cfg,original)
        plug.set_plugin_config(cfg)
        self.assertTrue(self.payload(plug,message('800000002'))['focus_verified'])

    def test_explicit_empty_new_list_overrides_legacy(self):
        cfg=p.AttentionSection.model_validate({'users':[],'qq_numbers':['800000002']})
        self.assertEqual(cfg.users,[])

    def test_invalid_qq_duplicate_and_limits_rejected(self):
        for users in [[{'qq':'oops'}],[{'qq':'800000002'},{'qq':'800000002','name':'other'}],[{'qq':str(810000000+i)} for i in range(51)]]:
            with self.subTest(users=len(users)),self.assertRaises(ValidationError):
                p.AttentionSection(users=users)

    def test_name_validation(self):
        for name in ['a\nb','\tbad','a'*33,123,'a\u2028b','a\x00b']:
            with self.subTest(name=repr(name)),self.assertRaises(ValidationError):
                p.QQBindingSection(creator_name=name)
            with self.assertRaises(ValidationError):p.AttentionEntry(qq='800000002',name=name)
        self.assertEqual(p.QQBindingSection(creator_name='  小星  ').creator_name,'小星')

    def test_configuration_reload_clears_old_target_and_name(self):
        plug=self.plugin(config('旧称呼'));msg=message()
        self.assertEqual(self.payload(plug,msg)['creator_name'],'旧称呼')
        plug.set_plugin_config(config('新称呼').model_dump())
        self.assertEqual(plug.engine.verify(msg['session_id'],msg['message_id']).reason,'cache_miss')
        self.assertEqual(self.payload(plug,msg)['creator_name'],'新称呼')

    def test_missing_target_has_no_configured_names(self):
        plug=self.plugin(config('主人'))
        data=plug.engine.verify('absent','absent').payload()
        self.assertIsNone(data['creator_name']);self.assertIsNone(data['focus_name'])

    def test_planner_does_not_receive_private_names(self):
        plug=self.plugin(config('主人'))
        result=asyncio.run(plug.planner_policy(items=[],item_schema_version=1))
        text=json.dumps(result,ensure_ascii=False)
        for name in ['主人','小星','阿月','800000002']:self.assertNotIn(name,text)

    def test_both_roles_keep_distinct_fields(self):
        cfg=config('绑定称呼')
        cfg.attention.users.append(p.AttentionEntry(qq='800000001',name='关注称呼'))
        data=self.payload(self.plugin(cfg),message())
        self.assertEqual((data['creator_name'],data['focus_name']),('绑定称呼','关注称呼'))

    def test_schema_exposes_per_user_name(self):
        schema=p.Config.model_json_schema()
        entry=schema['$defs']['AttentionEntry']['properties']
        self.assertIn('qq',entry);self.assertIn('name',entry)


if __name__=='__main__':unittest.main(verbosity=2)
