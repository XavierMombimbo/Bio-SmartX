import subprocess
import os

def extraire_minutiae(image_path, output_base_path):
    try:
        subprocess.run(['mindtct', image_path, output_base_path], check=True)
        return output_base_path + '.xyt'
    except subprocess.CalledProcessError as e:
        print(f"Erreur mindtct : {e}")
        return None

def comparer_empreintes(xyt1_path, xyt2_path):
    try:
        result = subprocess.run(
            ['bozorth3', '-T', '40', '-p', xyt1_path, xyt2_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        score = int(result.stdout.strip())
        return score
    except Exception as e:
        print(f"Erreur bozorth3 : {e}")
        return -1
