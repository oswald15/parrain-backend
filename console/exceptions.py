class ErreurLicence(Exception):
    """Base des 4 raisons d'echec possibles a la consommation d'un code (voir
    CONSOLE-SYSTEME.md section 4 : 'un echec dit lequel de ces quatre points a echoue, en
    clair'). .message_fr est le texte a renvoyer tel quel a l'utilisateur."""
    message_fr = "Erreur de licence."

    def __init__(self, message_fr=None):
        if message_fr:
            self.message_fr = message_fr
        super().__init__(self.message_fr)


class SignatureInvalide(ErreurLicence):
    message_fr = "Ce code n'est pas reconnu."


class OrganisationNonCorrespondante(ErreurLicence):
    message_fr = "Ce code ne correspond pas à cette organisation."


class CodeDejaUtilise(ErreurLicence):
    message_fr = "Ce code a déjà été utilisé."


class CodePerime(ErreurLicence):
    message_fr = "Ce code a expiré."


class HorlogeIncoherente(ErreurLicence):
    message_fr = "Date du système incohérente."
