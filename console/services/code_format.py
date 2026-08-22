import secrets

# 32 symboles, sans O/0/I/1 (voir CONSOLE-SYSTEME.md section 4 - format lisible/dictable au telephone).
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
GROUPES = 4
TAILLE_GROUPE = 4
PREFIXE = "LP"


def generer_code_clair():
    """Jeton aleatoire a haute entropie (16 symboles * 5 bits = 80 bits), formate pour etre
    dictable au telephone. Ne contient aucun payload structure - contrairement a la lecture
    litterale du document, une signature Ed25519 (64 octets) ne peut pas tenir dans 16
    caracteres alphanumeriques. Le code est donc une cle d'acces opaque, verifiee par
    recherche de son empreinte en base (voir ServiceLicence.consommer_code) - la signature
    Ed25519 protege la ligne CodeActivation en base contre une falsification directe, pas le
    bout de papier lui-meme (voir plan d'implementation, note d'architecture)."""
    symboles = ''.join(secrets.choice(ALPHABET) for _ in range(GROUPES * TAILLE_GROUPE))
    groupes = [symboles[i:i + TAILLE_GROUPE] for i in range(0, len(symboles), TAILLE_GROUPE)]
    return f"{PREFIXE}-" + "-".join(groupes)


def generer_numero_serie():
    """Reference publique (non secrete), independante du code lui-meme - pour l'affichage
    console/journal uniquement, ne permet jamais de reconstituer ou deviner le code."""
    return "AC-" + ''.join(secrets.choice(ALPHABET) for _ in range(8))


class CodeMalforme(ValueError):
    pass


def normaliser(code_saisi):
    """Nettoie une saisie utilisateur (espaces, tirets, casse, prefixe optionnel) et la reduit
    a la forme canonique LP-XXXX-XXXX-XXXX-XXXX - c'est cette forme canonique qui est hachee,
    a l'emission comme a la consommation, donc les deux cotes doivent toujours passer par ici."""
    if not code_saisi:
        raise CodeMalforme("Code vide.")
    brut = code_saisi.strip().upper().replace('-', '').replace(' ', '')
    if brut.startswith(PREFIXE):
        brut = brut[len(PREFIXE):]
    if len(brut) != GROUPES * TAILLE_GROUPE:
        raise CodeMalforme("Longueur de code invalide.")
    for ch in brut:
        if ch not in ALPHABET:
            raise CodeMalforme(f"Caractère invalide dans le code : {ch}")
    groupes = [brut[i:i + TAILLE_GROUPE] for i in range(0, len(brut), TAILLE_GROUPE)]
    return f"{PREFIXE}-" + "-".join(groupes)
