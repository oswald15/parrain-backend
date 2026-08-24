import re


def normalize_phone(phone: str) -> str:
    """Miroir exact de AuthService.normalizePhone() cote frontend
    (le_parrain_front-main/src/app/core/services/auth.service.ts) - les deux DOIVENT rester
    strictement synchronises. USERNAME_FIELD='phone' fait une correspondance exacte en base ;
    un numero stocke dans un format et envoye dans un autre au login ne matchera jamais, meme
    avec le bon mot de passe (bug reel rencontre : un compte cree via 'Creer le superadmin'
    avec '674510170' saisi sans indicatif ne pouvait jamais se connecter, le frontend envoyant
    toujours '+237674510170')."""
    if not phone:
        return phone
    p = phone.strip()
    if p.startswith('+'):
        return p
    p = re.sub(r'[^0-9]', '', p)
    if p.startswith('0'):
        p = p[1:]
    if len(p) in (8, 9):
        return f'+237{p}'
    return f'+{p}'
