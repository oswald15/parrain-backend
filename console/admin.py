from django import forms
from django.contrib import admin

from .models import Abonnement, CodeActivation, Editeur, EditeurToken, Formule, Journal, Paiement


class EditeurAdminForm(forms.ModelForm):
    """Le champ 'password' du modele n'est jamais affiche/edite directement (c'est un hash) -
    ce formulaire ajoute un champ de saisie en clair distinct, hache par EditeurAdmin.save_model
    avant tout enregistrement. Sans ca, creer/modifier un Editeur depuis /admin/ ne permettait
    pas de definir un mot de passe utilisable."""
    password = forms.CharField(
        label='Mot de passe', widget=forms.PasswordInput, required=False,
        help_text="Laisser vide pour ne pas changer le mot de passe d'un compte existant. "
                   "Obligatoire pour qu'un nouveau compte soit utilisable.",
    )

    class Meta:
        model = Editeur
        fields = ('email', 'nom', 'is_active', 'password')


@admin.register(Editeur)
class EditeurAdmin(admin.ModelAdmin):
    form = EditeurAdminForm
    list_display = ('email', 'nom', 'is_active', 'cree_le')
    search_fields = ('email', 'nom')
    readonly_fields = ('cree_le',)

    def save_model(self, request, obj, form, change):
        raw_password = form.cleaned_data.get('password')
        if raw_password:
            obj.set_password(raw_password)
        elif not change:
            # Nouveau compte cree sans mot de passe fourni : marque comme inutilisable plutot
            # que de sauvegarder un hash vide silencieusement exploitable.
            obj.set_unusable_password()
        obj.save()


@admin.register(EditeurToken)
class EditeurTokenAdmin(admin.ModelAdmin):
    list_display = ('key', 'editeur', 'created')
    readonly_fields = ('key', 'created')


@admin.register(Formule)
class FormuleAdmin(admin.ModelAdmin):
    list_display = ('libelle', 'duree_jours', 'montant_xaf', 'active')
    list_filter = ('active',)


@admin.register(CodeActivation)
class CodeActivationAdmin(admin.ModelAdmin):
    list_display = ('numero_serie', 'organisation', 'statut', 'emis_le', 'expire_le', 'utilise_le')
    list_filter = ('statut', 'organisation')
    search_fields = ('numero_serie',)
    readonly_fields = ('empreinte', 'signature', 'emis_le')


@admin.register(Abonnement)
class AbonnementAdmin(admin.ModelAdmin):
    list_display = ('organisation', 'formule', 'statut', 'date_debut', 'date_expiration')
    list_filter = ('statut', 'organisation')


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = ('organisation', 'montant_xaf', 'operateur', 'recu_le', 'saisi_par')
    list_filter = ('operateur', 'organisation')


@admin.register(Journal)
class JournalAdmin(admin.ModelAdmin):
    list_display = ('fait_le', 'action', 'acteur', 'organisation')
    list_filter = ('action', 'organisation')
    readonly_fields = ('id', 'acteur', 'action', 'organisation', 'details', 'fait_le')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
