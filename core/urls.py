from django.urls import path
from . import views
from .views import (
    demande_changement_mot_de_passe,
    confirmer_changement_mdp,
    modifier_photo_profil,
    liberer,
    publier_message,
)

urlpatterns = [
    # Authentification
    path('', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Tableaux de bord
    path('dashboards_admin/', views.dashboard_admin, name='dashboard_admin'),
    path('dashboard_user/', views.dashboard_user, name='dashboard_user'),
    
    # Gestion utilisateurs
    path('utilisateurs/', views.utilisateurs_view, name='utilisateurs_view'),
    path('utilisateur/toggle/<int:id>/', views.toggle_utilisateur, name='toggle_utilisateur'),
    path('utilisateur/supprimer/<int:id>/', views.supprimer_utilisateur, name='supprimer_utilisateur'),
    
    # Profil et messages
    path('profil/', views.profil, name='profil'),
    path('profil/photo/', modifier_photo_profil, name='modifier_photo'),
    path('messages/', views.messages_admin, name='messages_admin'),
    path('publier-message/', publier_message, name='publier_message'),
    
    # Détention
    path('ajouter-detenu/', views.ajouter_detenu, name='ajouter_detenu'),
    path('ajouter-detention/<int:detenu_id>/', views.ajouter_detention, name='ajouter_detention'),
    path('liberer/<int:detention_id>/', liberer, name='liberer'),
    path('dernier-detenu/', views.dernier_detenu, name='dernier_detenu'),
    path('liste-detenu/', views.liste_detenu, name='liste_detenu'),
    path('detenu/<int:id>/', views.detail_detenu, name='detail_detenu'),
    path('profil-detenu/<int:detenu_id>/', views.profil_detenu, name='profil_detenu'),
    path('detenu/<int:detenu_id>/pdf/', views.generer_pdf_detenu, name='generer_pdf_detenu'),
    
    # Vérification biométrique
    path('verifier/', views.verifier_visage, name='verifier_visage'),
    path('verifier/empreinte/', views.verifier_empreinte, name='verifier_empreinte'),
    
    # API (AJAX)
    path('api/verifier-visage/', views.api_verifier_visage, name='api_verifier_visage'),
    path('api/verifier-empreinte/', views.api_verifier_empreinte, name='api_verifier_empreinte'),
    
    # Logs et sécurité
    path('logs/', views.logs_view, name='logs'),
    path('logs/brute-force/', views.brute_force_logs_view, name='brute_force_logs'),
    path('logs/telecharger/', views.telecharger_journal, name='telecharger_journal'),
    
    # Gestion mot de passe
    path('changer-mot-de-passe/', demande_changement_mot_de_passe, name='changer_mot_de_passe'),
    path('confirmer-mot-de-passe/<str:token>/', confirmer_changement_mdp, name='confirmer_changement_mot_de_passe'),
]