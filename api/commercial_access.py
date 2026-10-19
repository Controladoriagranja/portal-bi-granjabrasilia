"""PermissÃ£o explÃ­cita do Comercial, independente do perfil do portal."""
import re

def normalize_commercial_access(value):
    if not isinstance(value, dict):
        raise ValueError('Informe a permissÃ£o de acesso ao Comercial.')
    mode = value.get('mode')
    if not isinstance(mode,str) or mode not in {'none', 'general', 'supervisor', 'seller'}:
        raise ValueError('Acesso ao Comercial invÃ¡lido.')
    result = {'mode': mode}
    if mode in {'supervisor', 'seller'}:
        code = str(value.get('code') or '').strip()
        if not re.fullmatch(r'[1-9][0-9]{0,11}', code):
            raise ValueError('Selecione um cÃ³digo vÃ¡lido de supervisor ou vendedor.')
        result['code'] = code
    return result


def effective_commercial_access(user):
    """Diretor sempre tem visão geral; demais perfis dependem da permissão explícita."""
    if str(user.get('role') or '').strip().lower()=='director' or str(user.get('perfil') or '').strip().lower() in {'diretor','director'}:
        return {'mode':'general'}
    return user.get('commercial_access') or {'mode':'none'}
