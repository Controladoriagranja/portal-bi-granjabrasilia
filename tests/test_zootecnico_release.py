"""Pacote/SQL de implantação: teste local em fixture, nunca nos arquivos oficiais."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from preparar_entrega_zootecnico import ARCHIVE,API,DELIVERY,API_FILES,PACKAGE_NAME,CONFIRMED_BASE_SHA256,integration_patch,original_docker_with_new_module


class ReleaseTests(unittest.TestCase):
    def test_patch_preserves_recent_additions_and_matches_prepared_integration(self):
        git=shutil.which('git')
        if not git:self.skipTest('Git local indisponível; não instalar automaticamente.')
        with tempfile.TemporaryDirectory(prefix='zootecnico-release-') as folder,ZipFile(ARCHIVE) as source:
            directory=Path(folder);target=directory/'API/api_zootecnico';target.mkdir(parents=True)
            names=('servico_zootecnico.py','portal_router.py','Dockerfile.zootecnico')
            for name in names:
                old=source.read('api_zootecnico/'+name).decode('utf-8-sig').replace('\r\r\n','\n').replace('\r\n','\n')
                # Uma alteração posterior fora dos trechos não pode desaparecer.
                (target/name).write_text(old+'\n# ALTERACAO_RECENTE_PRESERVADA\n',encoding='utf-8')
            patch=directory/'seguranca.patch';patch.write_text(integration_patch(),encoding='utf-8')
            for arguments in (['--check'],[]):
                result=subprocess.run([git,'-C',str(directory),'apply',*arguments,str(patch)],capture_output=True,text=True,timeout=10)
                self.assertEqual(result.returncode,0,result.stderr)
            for name in names:
                text=(target/name).read_text(encoding='utf-8')
                expected=(API/name).read_text(encoding='utf-8')+'\n# ALTERACAO_RECENTE_PRESERVADA\n'
                self.assertEqual(text,expected)

    def test_seed_requires_real_identity_and_exact_aliases_before_writes(self):
        seed=(ROOT/'api/migrations/20261103_zootecnico_tecnico_teste.sql').read_text(encoding='utf-8')
        cfg=json.loads(re.search(r'\$config\$(.*?)\$config\$',seed,re.S)[1])
        self.assertIsNone(cfg['nome']);self.assertIsNone(cfg['email_portal'])
        self.assertEqual(len(cfg['aliases']),6)
        self.assertTrue(all(values==[] for values in cfg['aliases'].values()))
        self.assertLess(seed.index('Preencha nome e email_portal'),seed.index('INSERT INTO'))
        self.assertNotRegex(seed,r'(?i)(?:INSERT\s+INTO|UPDATE)\s+public\.usuarios\b')
        self.assertNotIn('commercial_access',seed)
        self.assertIn('conta.role',seed);self.assertIn("'admin','director'",seed)
        self.assertIn('dono_alias<>v_tecnico_id',seed)
        self.assertIn("ON CONFLICT (recurso,fonte,valor)",seed)

    def test_full_original_layout_and_only_required_changes(self):
        package=DELIVERY/PACKAGE_NAME
        with ZipFile(ARCHIVE) as original,ZipFile(package) as zipped:
            new='api_zootecnico/zootecnico_acesso.py'
            self.assertEqual(set(zipped.namelist()),set(original.namelist())|{new})
            self.assertEqual(len(zipped.namelist()),len(original.namelist())+1)
            changed=[]
            for name in original.namelist():
                if original.read(name)!=zipped.read(name):changed.append(name)
            self.assertEqual(set(changed),{'api_zootecnico/'+name for name in API_FILES[:3]})
            self.assertEqual(zipped.read(new),(API/'zootecnico_acesso.py').read_bytes())
            for name in ('servico_zootecnico.py','portal_router.py'):
                self.assertEqual(zipped.read('api_zootecnico/'+name),(API/name).read_bytes())
            # O Dockerfile principal e todos os outros arquivos foram preservados.
            self.assertEqual(zipped.read('api_zootecnico/Dockerfile'),original.read('api_zootecnico/Dockerfile'))
            old_docker=original.read('api_zootecnico/Dockerfile.zootecnico')
            self.assertEqual(zipped.read('api_zootecnico/Dockerfile.zootecnico'),original_docker_with_new_module(old_docker))
            manifest=json.loads((DELIVERY/'referencia.json').read_text(encoding='utf-8'))
            self.assertFalse(manifest['publicado']);self.assertFalse(manifest['candidatos_tecnico_obrigatorio'])
            self.assertTrue(manifest['versao_oficial_confirmada'])
            self.assertFalse(manifest['servidor_inspecionado'])
            self.assertEqual(manifest['base_sha256'],CONFIRMED_BASE_SHA256)
        self.assertEqual(package.read_bytes(),(DELIVERY/'Acesso_Tecnico_Zootecnico_Anderson.zip').read_bytes())


if __name__=='__main__':unittest.main()
