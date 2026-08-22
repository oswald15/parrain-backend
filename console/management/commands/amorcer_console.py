import secrets

from decouple import config
from django.core.management.base import BaseCommand

from console.models import Editeur, Formule

FORMULES_EXEMPLE = [
    {'libelle': 'Mensuel', 'duree_jours': 30, 'montant_xaf': 15000},
    {'libelle': 'Trimestriel', 'duree_jours': 90, 'montant_xaf': 40000},
    {'libelle': 'Annuel', 'duree_jours': 365, 'montant_xaf': 150000},
]


class Command(BaseCommand):
    help = (
        "Amorce la console systeme : cree les formules d'abonnement d'exemple et le premier "
        "compte editeur (email/mot de passe lus depuis .env : EDITEUR_BOOTSTRAP_EMAIL / "
        "EDITEUR_BOOTSTRAP_PASSWORD - un mot de passe est genere et affiche si absent)."
    )

    def handle(self, *args, **options):
        created_count = 0
        for data in FORMULES_EXEMPLE:
            _, created = Formule.objects.get_or_create(libelle=data['libelle'], defaults=data)
            created_count += int(created)
        self.stdout.write(self.style.SUCCESS(
            f"{created_count} formule(s) creee(s) ({Formule.objects.count()} au total)."
        ))

        email = config('EDITEUR_BOOTSTRAP_EMAIL', default='editeur@le-parrain.local')
        if Editeur.objects.filter(email=email).exists():
            self.stdout.write(f"Editeur '{email}' existe deja - aucune modification.")
            return

        password = config('EDITEUR_BOOTSTRAP_PASSWORD', default=None)
        password_genere = password is None
        if password_genere:
            password = secrets.token_urlsafe(12)

        Editeur.objects.create_editeur(email=email, password=password, nom='Editeur')
        self.stdout.write(self.style.SUCCESS(f"Compte editeur cree : {email}"))
        if password_genere:
            self.stdout.write(self.style.WARNING(
                f"Aucun EDITEUR_BOOTSTRAP_PASSWORD dans .env - mot de passe genere : {password}"
            ))
