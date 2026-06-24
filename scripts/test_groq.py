import os, json, sys
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
load_dotenv()
import groq as groq_lib

client = groq_lib.Groq(api_key=os.getenv("GROQ_API_KEY"))

SYSTEM = (
    "Tu es l'IA redactrice de Factuel, journal francais. "
    "Reponds UNIQUEMENT en JSON strict, sans texte autour, sans bloc ```json. "
    'Format : {"titre":"...","slug":"...","resume":["p1","p2","p3"],'
    '"corps":{"faits":"...","contexte":"...","nuances":"..."},'
    '"sources":[{"institution":"...","titre":"...","date":"...","url":"..."}],'
    '"categorie":"economie","nb_sources":3}. '
    "Titre : factuel, max 15 mots. Aucun avis personnel. Minimum 3 sources officielles."
)

USER = (
    "Redige un article Factuel sur ce sujet :\n"
    "Selon l'INSEE (juin 2026), le taux de chomage en France s'etablit a 7,3 % "
    "au premier trimestre 2026, stable par rapport au trimestre precedent. "
    "Le taux d'emploi des 15-64 ans atteint 68,2 %. "
    "Le chomage des jeunes (15-24 ans) est a 17,4 %. "
    "Eurostat confirme et indique que la moyenne europeenne est a 5,9 %. "
    "La Dares note une legere hausse des offres d'emploi non pourvues (+3,2 %)."
)

print("Appel Groq (llama-3.3-70b)...")
r = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    max_tokens=2048,
    messages=[
        {"role": "system", "content": SYSTEM},
        {"role": "user",   "content": USER},
    ],
    temperature=0.2,
)

raw = r.choices[0].message.content.strip()
print("\n--- REPONSE BRUTE ---")
print(raw[:800])

try:
    data = json.loads(raw)
    print("\n--- JSON PARSE : OK ---")
    print(f"Titre   : {data['titre']}")
    print(f"Slug    : {data['slug']}")
    print(f"Cat     : {data['categorie']}")
    print(f"Sources : {data['nb_sources']}")
    print(f"Resume  : {data['resume'][0][:80]}...")
except json.JSONDecodeError as e:
    print(f"\n[ERREUR JSON] {e}")
