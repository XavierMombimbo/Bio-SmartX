from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.decorators import login_required
from django.contrib.auth import update_session_auth_hash
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.forms import UserCreationForm
from django import forms
from django.urls import reverse_lazy
from .models import PieceIdentite
from django.utils.dateparse import parse_date
from django.contrib.auth.models import User
from django.shortcuts import redirect, get_object_or_404
import io
from django.core.files.base import ContentFile
from django.utils import timezone
from .models import Detenu, Detention, Prison, MessageAdmin, TentativeConnexion, Visage, Empreinte, ResultatMatching
from .biometrie.facerec import detecter_visage, verifier_qualite_image, verifier_visage_existant
import base64
from django.core.signing import BadSignature
from django.core.paginator import Paginator
from datetime import timedelta
import tempfile
import subprocess
from django.utils.dateparse import parse_date
from django.core.exceptions import ValidationError
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors
from django.core.mail import send_mail
from django.urls import reverse
from django.conf import settings
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.http import HttpResponse
from django.core.signing import Signer
from django.core.mail import EmailMultiAlternatives
from .models import PasswordChangeRequest
from django.http import FileResponse, JsonResponse
from .models import Log
from django.contrib.auth import get_user_model
from django.views.decorators.http import require_POST
from django.contrib.auth.password_validation import validate_password
User = get_user_model()
from core.models import Detenu, Log, Visage, Empreinte
from core.biometrie.empreintever import identifier_empreinte
from django.core.signing import TimestampSigner
from .models import Detenu, Detention, Prison
from io import BytesIO
from django.template.loader import render_to_string
import uuid
from django.core.files.base import ContentFile
from django.views.decorators.csrf import csrf_exempt
import numpy as np
import cv2
import os
from django.db.models import Count
import logging
import shutil
import re

logger = logging.getLogger(__name__)
signer = TimestampSigner()

# ============================================================
# PRÉTRAITEMENT POUR EMPREINTES (conservé pour l'ajout)
# ============================================================

def pretraiter_empreinte(image_np):
    """
    Prétraite une image d'empreinte digitale pour mindtct.
    Utilisé uniquement lors de l'ajout d'un détenu.
    """
    if image_np is None:
        return None

    if len(image_np.shape) == 3:
        gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_np

    h, w = gray.shape
    if w > 1000:
        scale = 1000.0 / w
        new_w = 1000
        new_h = int(h * scale)
        gray = cv2.resize(gray, (new_w, new_h))

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 15, 2)

    kernel = np.ones((2, 2), np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)

    binary = cv2.bitwise_not(binary)
    return binary.astype(np.uint8)

# ============================================================
# API
# ============================================================

@csrf_exempt
@require_POST
def api_verifier_visage(request):
    image_base64 = request.POST.get('image_base64')
    if not image_base64:
        return JsonResponse({'success': False, 'message': 'Image manquante'})
    return JsonResponse({'success': True, 'score': 0.89, 'match': 'Jean Mwamba'})

@csrf_exempt
@require_POST
def api_verifier_empreinte(request):
    if 'empreinte' not in request.FILES:
        return JsonResponse({"success": False, "message": "Empreinte manquante"})

    uploaded_file = request.FILES['empreinte']
    ext = os.path.splitext(uploaded_file.name)[-1].lower()
    if ext not in ['.bmp', '.png', '.jpg', '.jpeg']:
        return JsonResponse({"success": False, "message": "Format non supporté"})

    temp_dir = tempfile.mkdtemp()
    temp_input_path = os.path.join(temp_dir, f"input{ext}")
    temp_prefix = os.path.join(temp_dir, "input")

    with open(temp_input_path, 'wb') as f:
        for chunk in uploaded_file.chunks():
            f.write(chunk)

    # Pas de prétraitement pour l'API non plus
    try:
        subprocess.run(['mindtct', temp_input_path, temp_prefix], check=True)
    except subprocess.CalledProcessError:
        shutil.rmtree(temp_dir, ignore_errors=True)
        return JsonResponse({"success": False, "message": "Erreur extraction minuties"})

    temp_xyt = temp_prefix + '.xyt'
    if not os.path.exists(temp_xyt):
        shutil.rmtree(temp_dir, ignore_errors=True)
        return JsonResponse({"success": False, "message": "Fichier XYT non généré"})

    meilleur_score = 0
    meilleur_detenu = None

    for empreinte in Empreinte.objects.exclude(fichier_xyt__isnull=True).exclude(fichier_xyt=''):
        ref_xyt = os.path.join(settings.MEDIA_ROOT, empreinte.fichier_xyt.name)
        if not os.path.exists(ref_xyt):
            continue
        result = subprocess.run(
            ['bozorth3', temp_xyt, ref_xyt],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        match = re.search(r'\d+', result.stdout)
        score = int(match.group()) if match else 0
        if score > meilleur_score:
            meilleur_score = score
            meilleur_detenu = empreinte.detenu

    shutil.rmtree(temp_dir, ignore_errors=True)

    if meilleur_score >= 60 and meilleur_detenu:
        return JsonResponse({
            "success": True,
            "score": meilleur_score,
            "detenu_id": meilleur_detenu.id,
            "nom": meilleur_detenu.nom,
            "postnom": meilleur_detenu.postnom
        })
    return JsonResponse({"success": False, "score": meilleur_score, "message": "Aucune correspondance"})

# ============================================================
# DÉTENTION
# ============================================================

def ajouter_detention(request, detenu_id):
    detenu = get_object_or_404(Detenu, id=detenu_id)
    prisons = Prison.objects.all()
    
    if request.method == 'POST':
        try:
            prison_id = request.POST['prison']
            date_debut = parse_date(request.POST['date_debut'])
            date_fin = parse_date(request.POST.get('date_fin', '')) or None
            cause = request.POST['cause']
            
            if not all([prison_id, date_debut, cause]):
                Log.objects.create(
                    user=request.user,
                    action="Erreur validation ajout détention",
                    additional_data="Champs manquants: prison, date_debut ou cause"
                )
                raise ValidationError("Tous les champs obligatoires doivent être remplis")
                
            if date_fin and date_fin < date_debut:
                Log.objects.create(
                    user=request.user,
                    action="Erreur validation dates détention",
                    additional_data=f"Date fin {date_fin} antérieure à date début {date_debut}"
                )
                raise ValidationError("La date de fin ne peut pas être antérieure à la date de début")
            
            detention = Detention.objects.create(
                detenu=detenu,
                prison_id=prison_id,
                date_debut=date_debut,
                date_fin=date_fin,
                cause=cause
            )
            
            Log.objects.create(
                user=request.user,
                action=f"Détention ajoutée - {detenu.nom}",
                additional_data=(
                    f"Prison: {detention.prison.nom}, "
                    f"Du {date_debut} au {date_fin or '...'}, "
                    f"Cause: {cause}"
                ),
                ip_address=get_client_ip(request)
            )
            messages.success(request, "Détention enregistrée avec succès")
            return redirect('detail_detenu', detenu.id)
            
        except KeyError as e:
            Log.objects.create(
                user=request.user,
                action="Erreur ajout détention - champ manquant",
                additional_data=str(e),
                ip_address=get_client_ip(request)
            )
            messages.error(request, f"Champ manquant: {str(e)}")
        except ValidationError as e:
            Log.objects.create(
                user=request.user,
                action="Erreur validation ajout détention",
                additional_data=str(e),
                ip_address=get_client_ip(request)
            )
            messages.error(request, str(e))
        except Exception as e:
            Log.objects.create(
                user=request.user,
                action="Erreur inattendue ajout détention",
                additional_data=str(e),
                ip_address=get_client_ip(request),
                lue=False
            )
            messages.error(request, f"Erreur inattendue: {str(e)}")
    
    return render(request, 'core/ajouter_detention.html', {
        'detenu': detenu,
        'prisons': prisons
    })

@login_required
def liberer(request, detention_id):
    detention = get_object_or_404(Detention, id=detention_id)
    ip_address = get_client_ip(request)
    
    if detention.date_fin:
        Log.objects.create(
            user=request.user,
            action="Tentative de libération d'une détention déjà libérée",
            additional_data=f"Détenu: {detention.detenu.nom} (ID: {detention.detenu.id})",
            ip_address=ip_address,
            lue=False
        )
        messages.warning(request, "Cette détention est déjà libérée")
    else:
        detention.date_fin = timezone.now().date()
        detention.save()
        Log.objects.create(
            user=request.user,
            action=f"Libération d'une détention pour : {detention.detenu.nom} {detention.detenu.postnom}",
            additional_data=(
                f"Détenu: {detention.detenu.nom} (ID: {detention.detenu.id}) | "
                f"Prison: {detention.prison.nom} | "
                f"Date libération: {detention.date_fin}"
            ),
            ip_address=ip_address
        )
        messages.success(request, f"Détenu {detention.detenu.nom} libéré avec succès")
    
    return redirect('detail_detenu', id=detention.detenu.id)

# ============================================================
# AJOUT DÉTENU (sans prétraitement visage, seulement face pour biométrie)
# ============================================================

@login_required
def ajouter_detenu(request):
    ip_address = get_client_ip(request)
    from insightface.app import FaceAnalysis
    face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    face_app.prepare(ctx_id=0)

    if request.method == 'POST':
        try:
            # ---------- Récupération des champs texte ----------
            nom = request.POST.get('nom')
            postnom = request.POST.get('postnom')
            prenom = request.POST.get('prenom')
            sexe = request.POST.get('sexe')
            date_naissance = request.POST.get('date_naissance')
            adresse = request.POST.get('adresse')
            nationalite = request.POST.get('nationalite')
            cause = request.POST.get('cause')
            prison_id = request.POST.get('prison')

            if not all([nom, postnom, prenom, sexe, date_naissance, adresse, nationalite, cause, prison_id]):
                messages.error(request, "Tous les champs d'identité et de détention sont obligatoires.")
                return redirect('ajouter_detenu')

            prison = Prison.objects.get(id=prison_id) if prison_id else None

            # ---------- Vérification présence d'au moins une donnée biométrique ----------
            visage_face = request.POST.get('photo_visage_face')
            visage_gauche = request.POST.get('photo_visage_gauche')
            visage_droite = request.POST.get('photo_visage_droite')
            has_visage = any([visage_face, visage_gauche, visage_droite])

            doigts_codes = ['TL', 'IL', 'ML', 'RL', 'LL', 'TR', 'IR', 'MR', 'RR', 'LR']
            empreintes_data = {code: request.POST.get(f'empreinte_{code}') for code in doigts_codes}
            has_empreinte = any(empreintes_data.values())

            if not has_visage and not has_empreinte:
                messages.error(request, "Vous devez fournir au moins une photo de visage ou une empreinte digitale.")
                return redirect('ajouter_detenu')

            # ---------- VALIDATION DES VISAGES ----------
            visage_face_data = None
            visages_profil_data = []

            # Visage FACE
            if visage_face and visage_face.startswith('data:image'):
                try:
                    format, imgstr = visage_face.split(';base64,')
                    ext = format.split('/')[-1]
                    file_name = f"visage_FACE_{uuid.uuid4().hex}.{ext}"
                    photo_content = ContentFile(base64.b64decode(imgstr), name=file_name)

                    img_array = np.frombuffer(photo_content.read(), np.uint8)
                    image_np = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                    if image_np is None:
                        raise ValueError("Image FACE illisible")

                    faces = face_app.get(image_np)
                    if not faces:
                        raise ValueError("Aucun visage détecté dans l'image FACE")
                    face = faces[0]
                    embedding = face.embedding
                    norm = np.linalg.norm(embedding)
                    if norm > 0:
                        embedding = embedding / norm
                    embedding_bytes = embedding.astype(np.float32).tobytes()

                    # Vérifier existence
                    detenu_existant, _ = verifier_embedding_direct_face(embedding, seuil=0.4)
                    if detenu_existant:
                        messages.warning(request, f"Ce visage correspond au détenu : {detenu_existant.nom}")
                        return redirect('profil_detenu', detenu_id=detenu_existant.id)

                    visage_face_data = {
                        'type': 'FACE',
                        'image': photo_content,
                        'embedding': embedding_bytes,
                        'qualite': float(face.det_score),
                        'modele': 'insightface'
                    }
                except Exception as e:
                    messages.error(request, f"Erreur sur le visage FACE : {str(e)}")
                    return redirect('ajouter_detenu')

            # Visages de profil (GAUCHE, DROITE)
            for angle_type, raw_data in [('GAUCHE', visage_gauche), ('DROITE', visage_droite)]:
                if raw_data and raw_data.startswith('data:image'):
                    try:
                        format, imgstr = raw_data.split(';base64,')
                        ext = format.split('/')[-1]
                        file_name = f"visage_{angle_type}_{uuid.uuid4().hex}.{ext}"
                        photo_content = ContentFile(base64.b64decode(imgstr), name=file_name)

                        img_array = np.frombuffer(photo_content.read(), np.uint8)
                        image_np = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                        if image_np is None:
                            raise ValueError(f"Image {angle_type} illisible")

                        faces = face_app.get(image_np)
                        if not faces:
                            raise ValueError(f"Aucun visage détecté dans l'image {angle_type}")
                        visages_profil_data.append({
                            'type': angle_type,
                            'image': photo_content
                        })
                    except Exception as e:
                        messages.error(request, f"Erreur sur le visage {angle_type} : {str(e)}")
                        return redirect('ajouter_detenu')

            # ---------- VALIDATION DES EMPREINTES (rigueur identique à verifier_empreinte) ----------
            empreintes_valides = []
            for doigt_code in doigts_codes:
                raw_data = empreintes_data.get(doigt_code)
                if not raw_data or not raw_data.startswith('data:image'):
                    continue
                try:
                    format, imgstr = raw_data.split(';base64,')
                    ext = format.split('/')[-1]
                    file_name = f"empreinte_{doigt_code}_{uuid.uuid4().hex}.{ext}"
                    empreinte_file = ContentFile(base64.b64decode(imgstr), name=file_name)

                    # Création d'un répertoire temporaire
                    temp_dir = tempfile.mkdtemp()
                    temp_input_path = os.path.join(temp_dir, f"input{ext}")
                    with open(temp_input_path, 'wb') as f:
                        f.write(empreinte_file.read())

                    # Vérification de l'image
                    img = cv2.imread(temp_input_path)
                    if img is None:
                        raise ValueError("Image empreinte illisible ou corrompue")

                    # Extraction des minuties (sans prétraitement)
                    temp_prefix = os.path.join(temp_dir, "input")
                    try:
                        subprocess.run(['mindtct', temp_input_path, temp_prefix], check=True, timeout=10)
                    except subprocess.CalledProcessError:
                        raise ValueError("Échec de l'extraction des minuties. L'image n'est pas une empreinte valide.")
                    except subprocess.TimeoutExpired:
                        raise ValueError("Temps d'extraction dépassé. Image trop complexe ou invalide.")

                    temp_xyt = temp_prefix + '.xyt'
                    if not os.path.exists(temp_xyt):
                        raise ValueError("Fichier de minuties non généré. L'image ne contient pas d'empreinte exploitable.")

                    # Compter les minuties extraites
                    minutiae_count = 0
                    with open(temp_xyt, 'r') as f:
                        lines = f.readlines()
                        minutiae_count = sum(1 for line in lines if line.strip() and not line.startswith('#'))
                    if minutiae_count < 12:
                        raise ValueError(f"Image d'empreinte invalide : seulement {minutiae_count} minuties extraites (minimum 12 requis).")

                    # Vérifier existence (comparaison avec la base)
                    liste_tpl_existants = []
                    for e in Empreinte.objects.exclude(fichier_xyt__isnull=True).exclude(fichier_xyt=''):
                        path = os.path.join(settings.MEDIA_ROOT, e.fichier_xyt.name)
                        if os.path.exists(path):
                            liste_tpl_existants.append(path)

                    detenu_exist, score = identifier_empreinte(temp_input_path, liste_tpl_existants, seuil=40)
                    if detenu_exist:
                        raise ValueError(f"L'empreinte du {dict(Empreinte.DOIGT_CHOICES).get(doigt_code, doigt_code)} correspond déjà à {detenu_exist.nom} (score {score})")

                    # Stocker les informations pour création ultérieure
                    empreintes_valides.append({
                        'doigt': doigt_code,
                        'image_content': empreinte_file,
                        'xyt_path': temp_xyt,
                        'temp_dir': temp_dir
                    })
                except Exception as e:
                    messages.error(request, f"Erreur empreinte {doigt_code} : {str(e)}")
                    # Nettoyer les éventuels fichiers déjà créés
                    for ev in empreintes_valides:
                        shutil.rmtree(ev['temp_dir'], ignore_errors=True)
                    return redirect('ajouter_detenu')

            # ---------- PIÈCE D'IDENTITÉ ----------
            type_piece = request.POST.get('type_piece')
            numero_piece = request.POST.get('numero_piece')
            pays_emission = request.POST.get('pays_emission')
            date_expiration_str = request.POST.get('date_expiration')
            piece_image = request.FILES.get('piece_image')
            piece_data = None
            if type_piece and numero_piece:
                date_expiration = None
                if date_expiration_str:
                    try:
                        date_expiration = parse_date(date_expiration_str)
                    except:
                        pass
                piece_data = {
                    'type_piece': type_piece,
                    'numero': numero_piece,
                    'pays_emission': pays_emission if pays_emission else None,
                    'date_expiration': date_expiration,
                    'image': piece_image
                }

            # ---------- CRÉATION DU DÉTENU (après toutes les validations) ----------
            detenu = Detenu.objects.create(
                nom=nom, postnom=postnom, prenom=prenom, sexe=sexe,
                date_naissance=date_naissance, adresse=adresse, nationalite=nationalite,
                prison=prison, agent=request.user, is_active=True
            )

            # Enregistrement du visage face
            if visage_face_data:
                Visage.objects.create(
                    detenu=detenu,
                    type_image=visage_face_data['type'],
                    image=visage_face_data['image'],
                    embedding=visage_face_data['embedding'],
                    qualite=visage_face_data['qualite'],
                    modele=visage_face_data['modele']
                )

            # Enregistrement des visages de profil
            for profil in visages_profil_data:
                Visage.objects.create(
                    detenu=detenu,
                    type_image=profil['type'],
                    image=profil['image'],
                    embedding=None,
                    qualite=None,
                    modele='insightface'
                )

            # Enregistrement des empreintes
            for ev in empreintes_valides:
                empreinte_obj = Empreinte.objects.create(
                    detenu=detenu,
                    doigt=ev['doigt'],
                    image=ev['image_content'],
                    qualite=None
                )
                with open(ev['xyt_path'], 'rb') as f:
                    empreinte_obj.fichier_xyt.save(f"{detenu.id}_{ev['doigt']}.xyt", ContentFile(f.read()), save=True)
                # Nettoyer le répertoire temporaire
                shutil.rmtree(ev['temp_dir'], ignore_errors=True)

            # Enregistrement de la pièce d'identité
            if piece_data:
                PieceIdentite.objects.create(
                    detenu=detenu,
                    type_piece=piece_data['type_piece'],
                    numero=piece_data['numero'],
                    pays_emission=piece_data['pays_emission'],
                    date_expiration=piece_data['date_expiration'],
                    image=piece_data['image']
                )

            # Création de la détention
            Detention.objects.create(detenu=detenu, prison=prison, cause=cause, date_debut=timezone.now().date())
            Log.objects.create(user=request.user, action="Nouveau détenu enregistré",
                               additional_data=f"Nom: {nom} {postnom} {prenom} | ID: {detenu.id}", ip_address=ip_address)
            messages.success(request, "Détenu ajouté avec succès.")
            return redirect('profil_detenu', detenu_id=detenu.id)

        except Exception as e:
            Log.objects.create(user=request.user, action="Erreur lors de l'ajout d'un détenu",
                               additional_data=str(e), ip_address=ip_address, lue=False)
            messages.error(request, f"Erreur inattendue : {str(e)}")
            return redirect('ajouter_detenu')

    prisons = Prison.objects.all()
    return render(request, 'core/ajouter_detenu.html', {'prisons': prisons})

# ============================================================
# VÉRIFICATION FACIALE (uniquement avec les visages de type 'FACE')
# ============================================================

def verifier_embedding_direct_face(embedding, seuil=0.62):
    """
    Compare un embedding uniquement avec les visages de type 'FACE' dans la base.
    Retourne (detenu, score).
    """
    meilleur_score = 0.0
    meilleur_detenu = None
    for visage in Visage.objects.filter(type_image='FACE').exclude(embedding__isnull=True).exclude(embedding=b''):
        try:
            emb_ref = np.frombuffer(visage.embedding, dtype=np.float32)
            norm = np.linalg.norm(emb_ref)
            if norm > 0:
                emb_ref = emb_ref / norm
            score = np.dot(embedding, emb_ref)
            if score > meilleur_score and score > seuil:
                meilleur_score = score
                meilleur_detenu = visage.detenu
        except Exception:
            continue
    return meilleur_detenu, meilleur_score

@login_required
def verifier_visage(request):
    ip_address = get_client_ip(request)
    from insightface.app import FaceAnalysis
    face_app = FaceAnalysis(name='buffalo_l', providers=['CPUExecutionProvider'])
    face_app.prepare(ctx_id=0)

    if request.method == 'POST':
        image_np = None
        if 'image_file' in request.FILES:
            Log.objects.create(user=request.user, action="Vérification visage - image uploadée", ip_address=ip_address)
            file_data = request.FILES['image_file'].read()
            img_array = np.frombuffer(file_data, np.uint8)
            image_np = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        elif request.POST.get('captured_image'):
            try:
                Log.objects.create(user=request.user, action="Vérification visage - image capturée", ip_address=ip_address)
                base64_data = request.POST['captured_image'].split(',')[1]
                image_bytes = base64.b64decode(base64_data)
                image_np = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
            except Exception:
                Log.objects.create(user=request.user, action="Erreur décodage image capturée", ip_address=ip_address, lue=False)
                messages.error(request, "Erreur de décodage de l'image capturée.")
                return redirect('verifier_visage')

        if image_np is None:
            Log.objects.create(user=request.user, action="Aucune image valide reçue", ip_address=ip_address, lue=False)
            messages.error(request, "Aucune image valide reçue.")
            return redirect('verifier_visage')

        # Détection du visage (image brute, sans prétraitement)
        faces = face_app.get(image_np)
        if not faces:
            messages.error(request, "Aucun visage détecté dans l'image.")
            return redirect('verifier_visage')

        face = faces[0]
        embedding = face.embedding
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm

        # Comparaison uniquement avec les visages de type 'FACE'
        detenu, score = verifier_embedding_direct_face(embedding, seuil=0.62)

        if detenu:
            score_percent = min(score * 100, 100)
            Log.objects.create(user=request.user, action=f"Visage reconnu - {detenu.nom} {detenu.postnom}",
                               additional_data=f"Score: {score_percent:.2f}% | ID: {detenu.id}", ip_address=ip_address)
            messages.success(request, f"Visage reconnu : {detenu.nom} {detenu.postnom}")
        else:
            score_percent = 0
            Log.objects.create(user=request.user, action="Aucune correspondance visage trouvée",
                               additional_data=f"Meilleur score: {score:.4f}", ip_address=ip_address, lue=False)
            messages.error(request, "Aucune correspondance trouvée.")

        return render(request, 'core/verifier.html', {
            'detenu_reconnu': detenu,
            'score_reconnaissance': score_percent,
            'dashoffset_reconnaissance': 339.292 * (1 - score_percent / 100)
        })

    Log.objects.create(user=request.user, action="Accès page vérification visage", ip_address=ip_address)
    return render(request, 'core/verifier.html')

# ============================================================
# VÉRIFICATION EMPREINTE (sans prétraitement, validation stricte)
# ============================================================

@login_required
def verifier_empreinte(request):
    ip_address = get_client_ip(request)
    context = {}  # Contexte par défaut pour le template

    if request.method == 'POST' and 'empreinte' in request.FILES:
        uploaded_file = request.FILES['empreinte']
        ext = os.path.splitext(uploaded_file.name)[-1].lower()
        if ext not in ['.bmp', '.png', '.jpg', '.jpeg']:
            messages.error(request, "Format non supporté (JPG, PNG, BMP uniquement).")
            return render(request, "core/verifier.html", context)

        temp_dir = tempfile.mkdtemp()
        temp_input_path = os.path.join(temp_dir, f"input{ext}")
        temp_prefix = os.path.join(temp_dir, "input")

        with open(temp_input_path, 'wb') as f:
            for chunk in uploaded_file.chunks():
                f.write(chunk)

        # Vérification rapide : l'image est-elle lisible ?
        img = cv2.imread(temp_input_path)
        if img is None:
            messages.error(request, "Image empreinte illisible ou corrompue.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return render(request, "core/verifier.html", context)

        # Extraction des minuties (mindtct) sans prétraitement
        try:
            subprocess.run(['mindtct', temp_input_path, temp_prefix], check=True, timeout=10)
        except subprocess.CalledProcessError:
            messages.error(request, "Échec de l'extraction des minuties. L'image ne semble pas être une empreinte digitale valide.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return render(request, "core/verifier.html", context)
        except subprocess.TimeoutExpired:
            messages.error(request, "Temps d'extraction dépassé. Image trop complexe ou invalide.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return render(request, "core/verifier.html", context)

        temp_xyt = temp_prefix + '.xyt'
        if not os.path.exists(temp_xyt):
            messages.error(request, "Fichier de minuties non généré. L'image ne contient pas d'empreinte exploitable.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return render(request, "core/verifier.html", context)

        # Compter les minuties extraites
        minutiae_count = 0
        try:
            with open(temp_xyt, 'r') as f:
                lines = f.readlines()
                minutiae_count = sum(1 for line in lines if line.strip() and not line.startswith('#'))
            if minutiae_count < 12:
                messages.error(request, f"Image d'empreinte invalide : seulement {minutiae_count} minuties extraites (minimum 12 requis).")
                shutil.rmtree(temp_dir, ignore_errors=True)
                return render(request, "core/verifier.html", context)
        except Exception:
            messages.error(request, "Erreur lors de l'analyse du fichier de minuties.")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return render(request, "core/verifier.html", context)

        # Comparaison avec la base
        meilleur_score = 0
        meilleur_detenu = None

        for empreinte in Empreinte.objects.exclude(fichier_xyt__isnull=True).exclude(fichier_xyt=''):
            ref_xyt = os.path.join(settings.MEDIA_ROOT, empreinte.fichier_xyt.name)
            if not os.path.exists(ref_xyt):
                continue
            try:
                result = subprocess.run(
                    ['bozorth3', temp_xyt, ref_xyt],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    timeout=5
                )
                match = re.search(r'\d+', result.stdout)
                score = int(match.group()) if match else 0
                if score > meilleur_score:
                    meilleur_score = score
                    meilleur_detenu = empreinte.detenu
            except subprocess.TimeoutExpired:
                continue

        shutil.rmtree(temp_dir, ignore_errors=True)

        context = {
            'score_empreinte': min(100, meilleur_score),
            'dashoffset_empreinte': 339.292 * (1 - min(100, meilleur_score) / 100),
        }

        if meilleur_score >= 60 and meilleur_detenu:
            messages.success(request, f"Empreinte reconnue : {meilleur_detenu.nom} {meilleur_detenu.postnom} (Score {meilleur_score})")
            context['detenu_reconnu'] = meilleur_detenu
        else:
            if meilleur_score < 10:
                messages.error(request, "Aucune empreinte correspondante trouvée.")
            else:
                messages.error(request, f"Aucune correspondance fiable trouvée (meilleur score: {meilleur_score}). Vérifiez l'empreinte ou sa qualité.")

    return render(request, "core/verifier.html", context)


# ============================================================
# FONCTIONS UTILITAIRES ET AUTRES VUES (inchangées)
# ============================================================

def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

DUREE_BLOCAGE_MINUTES = 60
NOMBRE_MAX_TENTATIVES = 5

def est_bloque(email, ip):
    maintenant = timezone.now()
    limite = maintenant - timedelta(minutes=DUREE_BLOCAGE_MINUTES)
    tentatives = TentativeConnexion.objects.filter(email=email, ip_address=ip, timestamp__gte=limite)
    return tentatives.count() >= NOMBRE_MAX_TENTATIVES

def login_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        ip = get_client_ip(request)

        if est_bloque(email, ip):
            messages.error(request, "Trop de tentatives échouées. Réessayez dans 60 minutes.")
            return render(request, 'core/login.html')

        user = authenticate(request, username=email, password=password)
        if user is not None:
            login(request, user)
            Log.objects.create(user=user, action="Connexion", ip_address=ip)
            TentativeConnexion.objects.filter(email=email, ip_address=ip).delete()
            if user.is_staff:
                return redirect('dashboard_admin')
            else:
                return redirect('dashboard_user')
        else:
            TentativeConnexion.objects.create(email=email, ip_address=ip)
            Log.objects.create(user=None, action="Tentative échouée de connexion", ip_address=ip, additional_data=f"Email saisi : {email}")
            messages.error(request, "Adresse email ou mot de passe incorrect.")
    return render(request, 'core/login.html')

@login_required
def dashboard(request):
    if request.user.is_staff:
        Log.objects.create(user=request.user, action="Accès tableau de bord admin")
        return redirect('dashboard_admin')
    else:
        Log.objects.create(user=request.user, action="Accès tableau de bord user")
        return redirect('dashboard_user')

@login_required
def dashboard_admin(request):
    if not request.user.is_staff:
        return redirect('dashboard_user')
    today = timezone.now().date()
    messages_admin = MessageAdmin.objects.order_by('-date_publication')[:3]
    logs_recents = Log.objects.filter(timestamp__date=today).count()
    utilisateurs_actifs = User.objects.filter(is_active=True).count()
    total_detenu = Detenu.objects.count()
    total_messages_admin = MessageAdmin.objects.count()
    brute_force_alerts = Log.objects.filter(
        action__icontains='Tentative échouée',
        timestamp__date=today
    ).values('ip_address').annotate(total=Count('id')).filter(total__gte=5).order_by('-total')
    Log.objects.create(user=request.user, action="Accès dashboard admin")
    return render(request, 'core/dashboard_admin.html', {
        'messages_admin': messages_admin,
        'logs_recents': logs_recents,
        'utilisateurs_actifs': utilisateurs_actifs,
        'total_detenu': total_detenu,
        'total_activites': logs_recents,
        'total_utilisateurs': utilisateurs_actifs,
        'alertes_securite': total_messages_admin,
        'brute_force_alerts': brute_force_alerts,
    })

@staff_member_required
def brute_force_logs_view(request):
    logs = Log.objects.filter(action__icontains='Tentative échouée', timestamp__date=timezone.now().date()).order_by('-timestamp')
    return render(request, 'core/brute_force_logs.html', {'logs': logs})

@login_required
def dashboard_user(request):
    if request.user.is_staff:
        Log.objects.create(user=request.user, action="Redirection vers dashboard admin")
        return redirect('dashboard_admin')
    Log.objects.create(user=request.user, action="Accès dashboard user")
    nb_messages_non_lus = MessageAdmin.objects.exclude(lus=request.user).count()
    return render(request, 'core/dashboard_user.html', {'nb_messages_non_lus': nb_messages_non_lus})

@login_required
def logout_view(request):
    Log.objects.create(user=request.user, action="Déconnexion")
    logout(request)
    return redirect('login')

@login_required
def publier_message(request):
    ip_address = get_client_ip(request)
    if not request.user.is_staff:
        Log.objects.create(user=request.user, action="Accès non autorisé à publier_message", ip_address=ip_address, lue=False)
        return redirect('dashboard_user')
    if request.method == 'POST':
        contenu = request.POST.get('contenu')
        if contenu:
            message = MessageAdmin.objects.create(auteur=request.user, contenu=contenu, date_publication=timezone.now())
            Log.objects.create(user=request.user, action="Message admin publié", additional_data=f"ID: {message.id}", ip_address=ip_address)
            messages.success(request, "Message publié")
        else:
            Log.objects.create(user=request.user, action="Tentative message vide", ip_address=ip_address, lue=False)
            messages.error(request, "Message vide")
        return redirect('dashboard_admin')
    Log.objects.create(user=request.user, action="Accès page publication", ip_address=ip_address)
    return render(request, 'core/publier_message.html')

@login_required
def utilisateurs(request):
    return render(request, 'core/utilisateurs.html')

@login_required
def demande_changement_mot_de_passe(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password1 = request.POST.get('new_password1')
        new_password2 = request.POST.get('new_password2')
        if not request.user.check_password(old_password):
            messages.error(request, "Mot de passe actuel incorrect.")
            return redirect('changer_mot_de_passe')
        if new_password1 != new_password2:
            messages.error(request, "Les mots de passe ne correspondent pas.")
            return redirect('changer_mot_de_passe')
        try:
            validate_password(new_password1, user=request.user)
        except ValidationError as e:
            for error in e.messages:
                messages.error(request, error)
            return redirect('changer_mot_de_passe')
        request.user.set_password(new_password1)
        request.user.save()
        update_session_auth_hash(request, request.user)
        Log.objects.create(user=request.user, action="Changement de mot de passe")
        messages.success(request, "Mot de passe changé.")
        return redirect('dashboard_admin')
    return render(request, 'core/changer_mot_de_passe.html')

def confirmer_changement_mdp(request, token):
    try:
        token_decoded = base64.urlsafe_b64decode(token.encode()).decode()
        data = signer.unsign(token_decoded)
        user_id, hashed_password = data.split(":", 1)
        user = User.objects.get(pk=user_id)
        user.password = hashed_password
        user.save()
        Log.objects.create(user=user, action="Changement de mot de passe confirmé")
        messages.success(request, "Mot de passe modifié.")
        return redirect('login')
    except (BadSignature, ValueError, User.DoesNotExist, base64.binascii.Error):
        messages.error(request, "Lien invalide ou expiré.")
        return redirect('login')

def envoyer_email_confirmation(user, lien):
    sujet = "Confirmation de changement de mot de passe"
    texte = f"Bonjour {user.get_full_name()}, cliquez ici : {lien}"
    html = render_to_string("core/emails/email_changement_mdp.html", {"user": user, "lien_confirmation": lien})
    email = EmailMultiAlternatives(sujet, texte, to=[user.email])
    email.attach_alternative(html, "text/html")
    email.send()

@staff_member_required
def logs_view(request):
    logs = Log.objects.select_related('user').order_by('-timestamp')
    if request.GET.get('filter') == 'brute_force':
        logs = logs.filter(action__icontains='Tentative échouée')
    return render(request, 'core/logs.html', {'logs': logs})

class AjoutUtilisateurForm(UserCreationForm):
    email = forms.EmailField(required=True)
    is_staff = forms.BooleanField(label='Est administrateur ?', required=False)
    class Meta:
        model = get_user_model()
        fields = ('username', 'email', 'is_staff', 'password1', 'password2')

@staff_member_required
def utilisateurs_view(request):
    utilisateurs = User.objects.all()
    form = AjoutUtilisateurForm()
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')
        is_admin = request.POST.get('is_admin') == 'on'
        if password1 != password2:
            messages.error(request, "Les mots de passe ne correspondent pas.")
        elif User.objects.filter(username=username).exists():
            messages.error(request, "Ce nom d'utilisateur existe déjà.")
        elif User.objects.filter(email=email).exists():
            messages.error(request, "Cette adresse e-mail est déjà utilisée.")
        else:
            utilisateur = User.objects.create_user(username=username, email=email, password=password1, is_staff=is_admin, is_active=True)
            Log.objects.create(user=request.user, action=f"Ajout de l'utilisateur {utilisateur.username}")
            messages.success(request, "Nouvel utilisateur ajouté.")
            return redirect('utilisateurs_view')
    return render(request, 'core/utilisateurs.html', {'utilisateurs': utilisateurs, 'form': form})

@staff_member_required
def telecharger_journal(request):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer)
    data = [['Date', 'Utilisateur', 'Action']]
    for log in Log.objects.select_related('user').order_by('-timestamp'):
        data.append([log.timestamp.strftime('%d/%m/%Y %H:%M'), f"{log.user.username} {log.user.email}" if log.user else '—', log.action])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#bfdbfe')), ('GRID', (0, 0), (-1, -1), 0.25, colors.grey)]))
    doc.build([table])
    buffer.seek(0)
    return FileResponse(buffer, as_attachment=True, filename='journal_activite.pdf')

@user_passes_test(lambda u: u.is_staff)
def toggle_utilisateur(request, id):
    utilisateur = get_object_or_404(User, pk=id)
    if request.method == 'POST':
        utilisateur.is_active = not utilisateur.is_active
        utilisateur.save()
        statut = "activé" if utilisateur.is_active else "désactivé"
        Log.objects.create(user=request.user, action=f"{statut.capitalize()} l'utilisateur {utilisateur.username}")
        messages.success(request, f"Utilisateur {utilisateur.username} a été {statut}.")
    return redirect('utilisateurs_view')

@login_required
def messages_admin(request):
    messages_list = MessageAdmin.objects.order_by('-date_publication')
    for msg in messages_list:
        msg.lus.add(request.user)
    return render(request, 'core/messages_admin.html', {'messages': messages_list})

@user_passes_test(lambda u: u.is_staff)
def supprimer_utilisateur(request, id):
    utilisateur = get_object_or_404(User, pk=id)
    if request.method == 'POST':
        messages.warning(request, f"Utilisateur {utilisateur.username} supprimé.")
        Log.objects.create(user=request.user, action=f"Suppression de l'utilisateur {utilisateur.email}")
        utilisateur.delete()
    return redirect('utilisateurs_view')

@login_required
def profil_detenu(request, detenu_id):
    detenu = get_object_or_404(Detenu, id=detenu_id)
    return render(request, 'core/profil_detenu.html', {'detenu': detenu})

@login_required
def profil(request):
    return render(request, 'core/profil.html')

@login_required
def modifier_photo_profil(request):
    if request.method == 'POST' and request.FILES.get('photo'):
        user = request.user
        user.photo = request.FILES['photo']
        user.save()
        Log.objects.create(user=user, action="Photo de profil modifiée.")
        return redirect('profil')
    return render(request, 'core/modifier_photo.html')

@login_required
def dernier_detenu(request):
    if request.user.is_staff:
        return redirect('dashboard_admin')
    derniers = Detenu.objects.filter(agent=request.user).order_by('-date_enregistrement')[:10]
    return render(request, 'core/dernier_detenu.html', {'detenus': derniers})

@login_required
def detail_detenu(request, id):
    ip_address = get_client_ip(request)
    detenu = get_object_or_404(Detenu, id=id)
    est_detenu = Detention.objects.filter(detenu=detenu, date_fin__isnull=True).exists()
    Log.objects.create(user=request.user, action=f"Consultation profil détenu - {detenu.nom} {detenu.postnom}",
                       additional_data=f"ID: {id} | Statut: {'Détenu' if est_detenu else 'Libéré'}",
                       ip_address=ip_address)
    detentions = Detention.objects.filter(detenu=detenu).order_by('-date_debut')
    derniere_detention = detentions.filter(date_fin__isnull=True).first()
    return render(request, 'core/detail_detenu.html', {
        'detenu': detenu,
        'detentions': detentions,
        'derniere_detention': derniere_detention,
    })

@login_required
def liste_detenu(request):
    ip_address = get_client_ip(request)
    Log.objects.create(user=request.user, action="Consultation liste détenus", additional_data="Liste paginée", ip_address=ip_address)
    detenus_list = Detenu.objects.all().order_by('-date_enregistrement')
    paginator = Paginator(detenus_list, 40)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'core/liste_detenus.html', {'page_obj': page_obj})

def generer_pdf_detenu(request, detenu_id):
    detenu = get_object_or_404(Detenu, id=detenu_id)
    template_path = 'pdf/profil_detenu.html'
    context = {'detenu': detenu}
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="profil_{detenu.nom}.pdf"'
    template = get_template(template_path)
    html = template.render(context)
    pisa.CreatePDF(html, dest=response)
    return response