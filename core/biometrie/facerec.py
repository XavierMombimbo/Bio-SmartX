import numpy as np
import cv2
from PIL import Image
from core.models import Detenu
from insightface.app import FaceAnalysis
import logging

# Configuration du logger
logger = logging.getLogger(__name__)

# ⚙️ Initialisation unique du modèle (meilleure performance)
try:
    FACE_APP = FaceAnalysis(name="buffalo_l", providers=['CPUExecutionProvider'])
    FACE_APP.prepare(ctx_id=0)
except Exception as e:
    logger.error(f"Erreur d'initialisation du modèle FaceAnalysis: {str(e)}")
    raise

# 🔁 Conversion optimisée fichier -> image NumPy
def image_to_np(file):
    """Convertit un fichier image en tableau numpy RGB"""
    try:
        if hasattr(file, 'read'):  # Si c'est un fichier uploadé
            image = Image.open(file)
        else:  # Si c'est un chemin
            image = Image.open(file)
        
        # Conversion en RGB et rotation si nécessaire
        image = image.convert('RGB')
        
        # Vérification orientation EXIF
        if hasattr(image, '_getexif'):
            exif = image._getexif()
            if exif:
                orientation = exif.get(0x0112)
                if orientation == 3:
                    image = image.rotate(180, expand=True)
                elif orientation == 6:
                    image = image.rotate(270, expand=True)
                elif orientation == 8:
                    image = image.rotate(90, expand=True)
        
        return np.array(image)
    except Exception as e:
        logger.error(f"Erreur conversion image: {str(e)}")
        return None

# 📸 Détection de visage avec contrôle qualité
def detecter_visage(file, min_quality=30, min_size=112):
    """
    Détecte un seul visage de qualité suffisante
    Retourne: (success, image, face_object)
    """
    try:
        image = image_to_np(file)
        if image is None:
            return False, None, None

        faces = FACE_APP.get(image)
        if not faces:
            logger.debug("Aucun visage détecté")
            return False, None, None

        # Trouver le visage avec le meilleur score
        best_face = max(faces, key=lambda x: x.det_score)

        # Vérifications qualité
        if best_face.det_score < 0.9:  # Seuil de confiance
            logger.debug(f"Score de détection trop faible: {best_face.det_score}")
            return False, None, None

        # Vérifier la taille du visage
        bbox = best_face.bbox.astype(int)
        face_width = bbox[2] - bbox[0]
        face_height = bbox[3] - bbox[1]
        if face_width < min_size or face_height < min_size:
            logger.debug(f"Visage trop petit: {face_width}x{face_height}")
            return False, None, None

        # Vérifier la pose (angles)
        if abs(best_face.pose[0]) > 30 or abs(best_face.pose[1]) > 30:
            logger.debug(f"Pose inacceptable: {best_face.pose}")
            return False, None, None

        return True, image, best_face
    except Exception as e:
        logger.error(f"Erreur détection visage: {str(e)}")
        return False, None, None

# 🔍 Vérification qualité d'image améliorée
def verifier_qualite_image(image, min_sharpness=100, min_brightness=50):
    """
    Vérifie plusieurs critères de qualité:
    - Netteté (Laplacian)
    - Luminosité moyenne
    - Contraste
    """
    try:
        gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        
        # Netteté
        sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
        if sharpness < min_sharpness:
            logger.debug(f"Netteté insuffisante: {sharpness}")
            return False
        
        # Luminosité
        brightness = np.mean(gray)
        if brightness < min_brightness or brightness > 220:
            logger.debug(f"Luminosité inadaptée: {brightness}")
            return False
        
        # Contraste
        contrast = gray.std()
        if contrast < 40:
            logger.debug(f"Contraste insuffisant: {contrast}")
            return False
            
        return True
    except Exception as e:
        logger.error(f"Erreur vérification qualité: {str(e)}")
        return False

# 🔑 Extraction d'embedding avec normalisation
def extraire_embedding(face_object):
    """Extrait et normalise l'embedding facial"""
    if not face_object:
        return None
    
    embedding = face_object.embedding
    return embedding / np.linalg.norm(embedding)  # Normalisation L2

# 🧠 Vérification visage existant optimisée
def verifier_visage_existant(image_np, seuil=0.6, max_results=1):
    """
    Compare avec la base de données et retourne:
    - (True, [détections]) si correspondance
    - (False, None) sinon
    """
    try:
        # Détection et extraction embedding
        success, _, face = detecter_visage(image_np)
        if not success:
            return False, None
        
        embedding = extraire_embedding(face)
        if embedding is None:
            return False, None

        # Recherche dans la base de données
        matches = []
        for detenu in Detenu.objects.exclude(embedding=None).only('id', 'nom', 'postnom', 'embedding'):
            try:
                emb_db = np.frombuffer(detenu.embedding, dtype=np.float32)
                emb_db = emb_db / np.linalg.norm(emb_db)  # Normalisation
                
                # Similarité cosinus (1 - distance cosinus)
                similarity = np.dot(embedding, emb_db)
                
                if similarity > seuil:
                    matches.append({
                        'detenu': detenu,
                        'score': float(similarity),
                        'distance': float(1 - similarity)
                    })
            except Exception as e:
                logger.warning(f"Erreur traitement détenu {detenu.id}: {str(e)}")
                continue

        # Trier par score décroissant
        matches.sort(key=lambda x: x['score'], reverse=True)
        
        if matches:
            return True, matches[:max_results]
        return False, None

    except Exception as e:
        logger.error(f"Erreur vérification visage existant: {str(e)}")
        return False, None