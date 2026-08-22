import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Genere une paire de cles Ed25519 pour la signature des codes d'activation. "
        "La cle privee ne doit JAMAIS etre commitee - collez-la dans .env "
        "(EDITEUR_ED25519_PRIVATE_KEY_B64). La cle publique est sans danger a diffuser "
        "(EDITEUR_ED25519_PUBLIC_KEY_B64, deja consommee par organisations/services/verification_licence.py)."
    )

    def handle(self, *args, **options):
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key()

        private_bytes = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        public_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

        private_b64 = base64.b64encode(private_bytes).decode()
        public_b64 = base64.b64encode(public_bytes).decode()

        self.stdout.write(self.style.WARNING(
            "Ne commitez jamais la cle privee. Collez ces deux lignes dans le .env du backend :"
        ))
        self.stdout.write("")
        self.stdout.write(f"EDITEUR_ED25519_PRIVATE_KEY_B64={private_b64}")
        self.stdout.write(f"EDITEUR_ED25519_PUBLIC_KEY_B64={public_b64}")
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            "La cle publique peut aussi etre commitee telle quelle dans settings.py si besoin "
            "(elle n'est pas un secret)."
        ))
