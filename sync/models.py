import secrets
import uuid

from django.db import models

from organisations.models import Organisation


class IdempotencyRecord(models.Model):
    """Trace d'une action deja traitee, identifiee par la cle d'idempotence envoyee par le
    client dans l'entete HTTP `Idempotency-Key`.

    Sert au mode hors-ligne : quand le reseau revient, l'app caissier/serveuse rejoue les
    actions empilees dans sa file d'attente locale. Sans cette trace, rejouer une requete
    dupliquerait la vente (voir ClientTabAddItemsView, qui cumule les quantites) ou renverrait
    une erreur 400 trompeuse sur une action pourtant deja reussie ("cet onglet n'est plus
    ouvert"). Ici, un rejeu renvoie simplement la reponse d'origine, telle quelle.

    La contrainte d'unicite (organisation, key) fait aussi office de verrou distribue : c'est
    l'INSERT qui echoue qui signale qu'une autre requete porte deja la meme cle (voir
    sync/mixins.py::IdempotencyMixin)."""

    STATE_IN_PROGRESS = 'in_progress'
    STATE_COMPLETED = 'completed'
    STATE_CHOICES = [
        (STATE_IN_PROGRESS, 'En cours de traitement'),
        (STATE_COMPLETED, 'Traitee'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name='idempotency_records'
    )
    user = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='idempotency_records'
    )
    key = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    # Empreinte du corps de la requete : une meme cle rejouee avec un contenu different
    # revele un bug client (cle reutilisee pour une autre action) qu'il vaut mieux signaler
    # que masquer en renvoyant la reponse d'une action sans rapport.
    request_fingerprint = models.CharField(max_length=64)
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default=STATE_IN_PROGRESS)
    response_status = models.IntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['organisation', 'key'], name='unique_idempotency_key_per_organisation'
            )
        ]
        indexes = [
            # Purge par anciennete (voir la commande purge_idempotency).
            models.Index(fields=['created_at'], name='idempotency_created_at_idx'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.method} {self.path} [{self.key}] - {self.state}"


class PendingUpstreamRequest(models.Model):
    """Une operation faite au bar, en attente d'etre remontee vers le serveur central.

    Ce qui est memorise n'est pas l'objet metier mais **la requete HTTP elle-meme**. Remonter une
    vente revient alors a rejouer exactement l'appel que l'instance locale a deja traite, ce qui
    evite d'ecrire - et de maintenir - une serialisation par modele. Le cloud applique la meme
    logique metier que le bar : decrement de stock, ecritures au journal, rattachement a la
    session de caisse, tout decoule du rejeu.

    Cela rend aussi inoffensifs les identifiants entiers de OrderItem et BonItem : c'est le cloud
    qui les cree de son cote, sans collision possible entre deux bars.

    La cle d'idempotence capturee est celle que le poste ou la tablette avait deja generee : le
    cloud reconnaitra donc un rejeu, y compris si la remontee est tentee plusieurs fois.

    La clef primaire est volontairement un entier auto-incremente, et non un UUID comme ailleurs :
    cette table ne quitte jamais l'instance locale, et l'ordre de capture doit etre strictement
    croissant - une commande doit exister dans le cloud avant les articles qu'on y ajoute, sans
    quoi le rejeu echouerait en 404.
    """

    STATUS_PENDING = 'pending'
    STATUS_QUARANTINED = 'quarantined'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'En attente de remontee'),
        (STATUS_QUARANTINED, 'En echec definitif'),
    ]

    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name='pending_upstream_requests'
    )
    # L'auteur de l'action au bar : le cloud doit l'imputer a lui, pas a l'instance.
    user = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pending_upstream_requests'
    )
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    query_string = models.CharField(max_length=500, blank=True)
    body = models.JSONField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=255, blank=True)
    client_created_at = models.CharField(max_length=64, blank=True)
    cashier_session = models.CharField(max_length=64, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['pk']
        indexes = [
            models.Index(fields=['organisation', 'status', 'id'], name='upstream_pending_idx'),
        ]

    def __str__(self):
        return f"{self.method} {self.path} [{self.status}]"


class PendingDownstreamRequest(models.Model):
    """Une correction faite par l'admin dans le serveur central, a redescendre vers le bar.

    Miroir exact de PendingUpstreamRequest, dans l'autre sens - et pour la meme raison : c'est la
    requete HTTP qui est memorisee, pas l'objet metier, si bien que le bar applique la correction
    en rejouant l'appel que le cloud a deja traite.

    Sans cela, une vente annulee par l'admin continue d'exister au bar : le stock finit par
    converger a la descente du referentiel, mais le resume de caisse du poste compte toujours
    cette vente, et le caissier remet en fin de service un montant qui ne correspond a rien.

    Les lignes ne sont pas supprimees a la livraison : un etablissement peut avoir plusieurs
    postes, chacun avancant a son rythme (voir SyncInstance.last_downstream_id). La purge se fait
    a l'anciennete, une fois tout le monde servi.
    """

    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name='pending_downstream_requests'
    )
    # L'admin qui a fait la correction : le bar doit l'imputer a lui, pas au caissier present.
    user = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='pending_downstream_requests'
    )
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    query_string = models.CharField(max_length=500, blank=True)
    body = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Entier auto-incremente, comme pour la remontee : l'ordre de capture doit etre
        # strictement croissant, une suppression d'article ne pouvant precer l'annulation
        # de la commande qui la porte.
        ordering = ['pk']
        indexes = [
            models.Index(fields=['organisation', 'id'], name='downstream_pending_idx'),
        ]

    def __str__(self):
        return f"{self.method} {self.path}"


class OperationAbandonnee(models.Model):
    """Une consommation servie au client, que rien n'a jamais pu enregistrer.

    Elle arrive ici par un seul chemin : le poste du caissier est mort avec des bons encore dans
    la tablette d'une serveuse, et ces bons ne peuvent pas etre rejoues ailleurs - ils
    referencent des onglets que l'instance du bar etait seule a connaitre.

    Sans cette table, l'archive resterait dans le SQLite d'un telephone. Tablette perdue,
    reinstallee, ou serveuse partie, et ces ventes disparaitraient sans que personne cote admin
    n'ait jamais su qu'elles avaient existe. C'est le seul endroit ou elles deviennent visibles.

    **Rien n'est jamais supprime ici.** Une fois la vente ressaisie a la main, elle est marquee
    traitee, pas effacee : c'est la seule trace d'un ecart entre ce qui a ete bu et ce qui a ete
    comptabilise.
    """

    # L'identifiant vient de la tablette : c'est la cle d'idempotence du bon d'origine. Il rend
    # le signalement repetable sans creer de doublon, la tablette pouvant reessayer.
    id = models.UUIDField(primary_key=True, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name='operations_abandonnees'
    )
    user = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='operations_abandonnees'
    )
    libelle = models.CharField(max_length=255)
    detail = models.TextField(blank=True)
    # Nul quand la tablette n'avait pas le catalogue en cache : un montant approxime sur une
    # consommation servie serait pire qu'un montant absent.
    montant = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    client_created_at = models.CharField(max_length=64, blank=True)
    # La requete d'origine, telle que la tablette l'avait enfilee. Un resume suffit pour
    # ressaisir, pas pour trancher un desaccord trois jours plus tard.
    raw = models.JSONField(null=True, blank=True)

    signalee_le = models.DateTimeField(auto_now_add=True)
    traitee_le = models.DateTimeField(null=True, blank=True)
    traitee_par = models.ForeignKey(
        'users.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='operations_abandonnees_traitees'
    )

    class Meta:
        ordering = ['-signalee_le']
        indexes = [
            models.Index(fields=['organisation', 'traitee_le'], name='abandon_org_traitee_idx'),
        ]

    def __str__(self):
        return f"{self.libelle} ({self.organisation.name})"


def generate_instance_token():
    """Jeton long et imprevisible : il vaut pour toutes les operations d'un etablissement."""
    return secrets.token_urlsafe(48)


class SyncInstance(models.Model):
    """Identifiant d'une instance installee dans un bar, pour remonter ses operations.

    Chaque etablissement recoit son propre jeton a l'installation. L'instance s'en sert pour
    pousser vers le serveur central les operations faites sur place, en declarant quel employe
    les a effectuees (entete `X-Acting-User`, voir sync/authentication.py).

    Frontiere de confiance, assumee : ce jeton permet d'agir au nom de n'importe quel employe de
    CET etablissement - et d'aucun autre. Ce n'est pas un affaiblissement, car l'instance locale
    fait deja autorite sur les operations de son bar : qui la compromet peut de toute facon y
    creer les operations qu'il veut, qui remonteront ensuite. Le jeton apporte en revanche ce que
    des jetons d'employes n'offriraient pas : une revocation immediate et ciblee si un poste est
    vole, sans toucher aux comptes du personnel.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organisation = models.ForeignKey(
        Organisation, on_delete=models.CASCADE, related_name='sync_instances'
    )
    name = models.CharField(max_length=150)
    token = models.CharField(max_length=128, unique=True, default=generate_instance_token)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Derniere remontee recue : permet a l'admin de savoir si les chiffres qu'il consulte sont
    # a jour, ou si le bar travaille hors-ligne depuis un moment.
    last_seen_at = models.DateTimeField(null=True, blank=True)
    # Nombre d'operations que le bar n'a pas encore remontees, tel qu'il l'a declare a son
    # dernier contact. Le serveur central ne peut pas le deviner : sans cette information, un
    # admin pourrait valider un inventaire alors que des ventes sont encore en route, et les
    # effacer du stock (voir products/views.py::InventoryValidateView).
    pending_operations = models.IntegerField(default=0)
    # Jusqu'ou ce poste a applique les corrections venues du serveur central. Le curseur vit sur
    # l'instance parce que deux postes d'un meme etablissement n'avancent pas ensemble : l'un
    # peut etre eteint pendant que l'autre travaille.
    last_downstream_id = models.IntegerField(default=0)

    class Meta:
        ordering = ['organisation__name', 'name']

    def __str__(self):
        return f"{self.name} ({self.organisation.name})"
