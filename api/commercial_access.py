"""Alcance de dados dos relatórios do portal; aliases legados preservados."""
import re

def normalize_data_access(value):
    if not isinstance(value, dict):
        raise ValueError('Informe a permissão de acesso aos dados dos relatórios.')
    mode = value.get('mode')
    if not isinstance(mode, str) or mode not in {'none', 'general', 'supervisor', 'seller'}:
        raise ValueError('Acesso aos dados inválido.')
    result = {'mode': mode}
    if mode in {'supervisor', 'seller'}:
        code = str(value.get('code') or '').strip()
        if not re.fullmatch(r'[1-9][0-9]{0,11}', code):
            raise ValueError('Selecione um código válido de supervisor ou vendedor.')
        result['code'] = code
    return result

def effective_data_access(user):
    """Admin e Diretor sempre têm visão geral; demais perfis usam o cadastro."""
    if str(user.get('role') or '').strip().lower() in {'admin', 'director'} or str(user.get('perfil') or '').strip().lower() in {'admin', 'diretor', 'director'}:
        return {'mode': 'general'}
    # Coluna existente mantém as permissões salvas sem criar uma segunda fonte.
    return user.get('commercial_access') or {'mode': 'none'}

normalize_commercial_access = normalize_data_access
effective_commercial_access = effective_data_access
