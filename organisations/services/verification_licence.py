"""Verification de signature Ed25519 - isole du reste de la console : ce fichier n'importe
JAMAIS la cle privee (settings.EDITEUR_ED25519_PRIVATE_KEY_B64), uniquement la cle publique.
Utilise par console.services.licence.ServiceLicence pour reverifier qu'une ligne
CodeActivation n'a pas ete falsifiee hors du flux d'emission normal - defense en profondeur,
voir la note d'architecture du plan d'implementation (le code imprime n'est pas un blob signe
auto-suffisant, la signature protege la ligne en base, pas le papier)."""
import base64

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from django.conf import settings


def construire_payload(organisation_id, duree_jours, emis_le, numero_serie):
    """Payload canonique signe a l'emission (console.services.licence) et reverifie ici a la
    consommation - doit produire des octets strictement identiques des deux cotes."""
    return "|".join([
        str(organisation_id),
        str(duree_jours),
        emis_le.isoformat(),
        numero_serie,
    ]).encode('utf-8')


def verifier_signature(payload_bytes, signature_b64):
    if not settings.EDITEUR_ED25519_PUBLIC_KEY_B64 or not signature_b64:
        return False
    try:
        clef_publique = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(settings.EDITEUR_ED25519_PUBLIC_KEY_B64)
        )
        clef_publique.verify(base64.b64decode(signature_b64), payload_bytes)
        return True
    except (InvalidSignature, ValueError):
        return False
