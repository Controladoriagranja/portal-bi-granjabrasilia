"""Permissão explícita do Comercial, independente do perfil do portal."""
import re

def normalize_commercial_access(value):
    if not isinstance(value, dict):
        raise ValueError('Informe a permissão de acesso ao Comercial.')
    mode = value.get('mode')
    if not isinstance(mode,str) or mode not in {'none', 'general', 'supervisor', 'seller'}:
        raise ValueError('Acesso ao Comercial inválido.')
    result = {'mode': mode}
    if mode in {'supervisor', 'seller'}:
        code = str(value.get('code') or '').strip()
        if not re.fullmatch(r'[1-9][0-9]{0,11}', code):
            raise ValueError('Selecione um código válido de supervisor ou vendedor.')
        result['code'] = code
    return result
