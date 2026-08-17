#!/usr/bin/env python3
"""Trouve la taille de requête RÉELLEMENT acceptée par un modèle Groq.

Le 17/08, `groq/compound` a refusé 40 requêtes sur 40 avec « 413 Request
Entity Too Large » alors que l'API annonce pour lui une fenêtre de 131 072
tokens et un débit de 70 000/minute — nos requêtes faisaient ~17 000. Les
deux chiffres publiés disent donc que ça devrait passer, et ça ne passe pas.

Plutôt que de supposer, on mesure : on envoie des requêtes de taille
croissante et on relève celle où le refus apparaît. Coût dérisoire
(max_tokens=1, et compound n'a pas de plafond journalier).
"""
import json
import os
import sys
import urllib.error
import urllib.request

MODELE = os.getenv("MODELE", "groq/compound")
CLE = os.getenv("K1", "")
TAILLES = [1_000, 2_000, 4_000, 6_000, 8_000, 12_000, 16_000, 24_000, 32_000]

if not CLE:
    print("GROQ_API_KEY absente")
    sys.exit(1)

print(f"=== {MODELE} — taille de requête réellement acceptée ===")
print(f"  {'tokens ~':>9}  {'car.':>8}  résultat")
dernier_ok = 0
for n in TAILLES:
    corps = json.dumps({
        "model": MODELE,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "a " * int(n * 3.3 / 2)}],
    }).encode()
    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions", data=corps,
        headers={"Authorization": f"Bearer {CLE}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            print(f"  {n:>9}  {len(corps):>8}  OK ({r.status})")
            dernier_ok = n
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:180]
        print(f"  {n:>9}  {len(corps):>8}  REFUS {e.code} — {detail}")
        break
    except Exception as e:  # noqa: BLE001
        print(f"  {n:>9}  {len(corps):>8}  {type(e).__name__}: {e}")
        break

print()
print(f"  Dernière taille acceptée : ~{dernier_ok} tokens.")
print(f"  Pour mémoire, notre prompt de génération nominal fait ~13 400 tokens,")
print(f"  et le prompt système seul en fait 6 893.")
