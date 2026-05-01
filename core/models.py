from django.db import models
from django.conf import settings
import uuid
from datetime import timedelta
from django.utils import timezone
from django.contrib.auth.models import AbstractUser, BaseUserManager

# =========================
# USER (inchangé, mais vérifie que tout est là)
# =========================

class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('L\'utilisateur doit avoir une adresse email')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Administrateur'),
        ('agent', 'Agent'),
    ]

    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)

    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='agent')
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    photo = models.ImageField(upload_to='photos_profil/', blank=True, null=True)

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    objects = UserManager()

    def __str__(self):
        return self.email


# =========================
# PRISON (inchangé)
# =========================

class Prison(models.Model):
    nom = models.CharField(max_length=100, unique=True)
    localisation = models.CharField(max_length=150)
    capacite = models.PositiveIntegerField(null=True, blank=True)

    def __str__(self):
        return f"{self.nom} ({self.localisation})"


# =========================
# DETENU (REFONDU)
# =========================

class Detenu(models.Model):
    NATIONALITE_CHOICES = [
        ('CONGOLAISE', 'Congolaise'),
        ('ETRANGERE', 'Étrangère'),
    ]

    nom = models.CharField(max_length=100)
    postnom = models.CharField(max_length=100, blank=True)
    prenom = models.CharField(max_length=100)

    nationalite = models.CharField(max_length=20, choices=NATIONALITE_CHOICES, default='CONGOLAISE')
    sexe = models.CharField(max_length=10, choices=[('M', 'Masculin'), ('F', 'Féminin')])
    date_naissance = models.DateField()
    adresse = models.CharField(max_length=255, blank=True)
    cause = models.TextField(blank=True)

    # ⚠️ Supprimer les anciens champs photo_visage / empreinte_digitale / empreinte_xyt
    # Ils sont remplacés par les tables Visage et Empreinte

    is_active = models.BooleanField(default=True)  # Désactiver un profil sans supprimer

    date_enregistrement = models.DateTimeField(auto_now_add=True)

    prison = models.ForeignKey("Prison", on_delete=models.SET_NULL, null=True, blank=True)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.nom} {self.postnom} {self.prenom}"

    @property
    def is_recent(self):
        return self.date_enregistrement >= (timezone.now() - timedelta(days=7))


# =========================
# VISAGE (MULTI-ANGLES + IA)
# =========================

class Visage(models.Model):
    TYPE_CHOICES = [
        ('FACE', 'Face'),
        ('GAUCHE', 'Gauche'),
        ('DROITE', 'Droite'),
    ]

    detenu = models.ForeignKey(Detenu, on_delete=models.CASCADE, related_name='visages')
    type_image = models.CharField(max_length=10, choices=TYPE_CHOICES)

    image = models.ImageField(upload_to='visages/')
    embedding = models.BinaryField(null=True, blank=True)

    qualite = models.FloatField(null=True, blank=True)
    modele = models.CharField(max_length=50, default='insightface')

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('detenu', 'type_image')


# =========================
# EMPREINTE (10 DOIGTS + NBIS)
# =========================

class Empreinte(models.Model):
    DOIGT_CHOICES = [
        ('TL', 'Pouce gauche'),
        ('IL', 'Index gauche'),
        ('ML', 'Majeur gauche'),
        ('RL', 'Annulaire gauche'),
        ('LL', 'Auriculaire gauche'),
        ('TR', 'Pouce droit'),
        ('IR', 'Index droit'),
        ('MR', 'Majeur droit'),
        ('RR', 'Annulaire droit'),
        ('LR', 'Auriculaire droit'),
    ]

    detenu = models.ForeignKey(Detenu, on_delete=models.CASCADE, related_name='empreintes')
    doigt = models.CharField(max_length=2, choices=DOIGT_CHOICES)

    image = models.ImageField(upload_to='empreintes/')
    fichier_xyt = models.FileField(upload_to='empreintes_xyt/', null=True, blank=True)

    qualite = models.FloatField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('detenu', 'doigt')
        indexes = [
            models.Index(fields=['detenu', 'doigt']),
        ]


# =========================
# PIECES IDENTITE (avec scan)
# =========================

class PieceIdentite(models.Model):
    TYPE_CHOICES = [
        ('CNI', 'Carte nationale'),
        ('PASS', 'Passeport'),
        ('PERMIS', 'Permis'),
        ('ELECTEUR', 'Carte électeur'),
        ('ETUDIANT', 'Carte étudiant'),
        ('ELEVE', 'Carte élève'),
        ('AUTRE', 'Autre'),
    ]

    detenu = models.ForeignKey(Detenu, on_delete=models.CASCADE, related_name='pieces')
    type_piece = models.CharField(max_length=20, choices=TYPE_CHOICES)
    numero = models.CharField(max_length=100)
    pays_emission = models.CharField(max_length=100, null=True, blank=True)
    date_expiration = models.DateField(null=True, blank=True)
    image = models.ImageField(upload_to='pieces/', null=True, blank=True)

    class Meta:
        unique_together = ('type_piece', 'numero')
        indexes = [models.Index(fields=['numero'])]


# =========================
# DETENTION (inchangé)
# =========================

class Detention(models.Model):
    detenu = models.ForeignKey(Detenu, on_delete=models.CASCADE)
    prison = models.ForeignKey(Prison, on_delete=models.PROTECT)
    cause = models.TextField()
    date_debut = models.DateField()
    date_fin = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.detenu.nom} - {self.prison.nom}"


# =========================
# LOG (amélioré)
# =========================

class Log(models.Model):
    timestamp = models.DateTimeField(auto_now_add=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    action = models.CharField(max_length=255)
    additional_data = models.TextField(null=True, blank=True)
    lue = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    is_used = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    metadata = models.JSONField(null=True, blank=True)  # 🔥 stockage avancé

    def __str__(self):
        return f"{self.timestamp} - {self.user} - {self.action}"


# =========================
# RESULTAT MATCHING (BONUS)
# =========================

class ResultatMatching(models.Model):
    TYPE_CHOICES = [
        ('FACE', 'Visage'),
        ('FINGERPRINT', 'Empreinte'),
    ]

    detenu = models.ForeignKey(Detenu, on_delete=models.CASCADE)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    score = models.FloatField()
    seuil = models.FloatField()
    resultat = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.detenu} - {self.type} - {self.resultat}"


# =========================
# TES AUTRES MODÈLES (inchangés)
# =========================

class PasswordChangeRequest(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    new_password = models.CharField(max_length=128)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now)
    is_used = models.BooleanField(default=False)


class AlerteSecurite(models.Model):
    message = models.TextField()
    date = models.DateTimeField(auto_now_add=True)
    lue = models.BooleanField(default=False)

    def __str__(self):
        return f"Alerte du {self.date.strftime('%d/%m/%Y %H:%M')}"


class MessageAdmin(models.Model):
    titre = models.CharField(max_length=255, default="Message du système")
    contenu = models.TextField()
    auteur = models.ForeignKey(User, on_delete=models.CASCADE, default=1)
    date_publication = models.DateTimeField(auto_now_add=True)
    destinataires = models.ManyToManyField(User, blank=True, related_name='messages_reçus')
    lus = models.ManyToManyField(User, blank=True, related_name='messages_lus')

    def __str__(self):
        return self.titre


class TentativeConnexion(models.Model):
    email = models.CharField(max_length=150)
    ip_address = models.GenericIPAddressField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.email} - {self.ip_address} - {self.timestamp}"