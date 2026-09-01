import os
import re
import discord
import httpx
import math
import json
import base64
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from discord import app_commands
from discord.ext import tasks
from datetime import datetime, time
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

load_dotenv()

# Intents minimaux : commandes slash + envoi d'embeds
intents = discord.Intents.default()

# ==========================================
# GESTION DE LA CONFIGURATION ARBORESCENTE
# ==========================================
CONFIG_PATH = "config.json"
_config_cache: dict | None = None


def charger_config() -> dict:
    """Charge la configuration globale (depuis le cache mémoire si possible)."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    if not os.path.exists(CONFIG_PATH):
        _config_cache = {}
        sauvegarder_config(_config_cache)
        return _config_cache

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        try:
            _config_cache = json.load(f)
        except json.JSONDecodeError:
            _config_cache = {}
    return _config_cache


def sauvegarder_config(config_data: dict) -> None:
    """Sauvegarde la configuration globale et met à jour le cache mémoire."""
    global _config_cache
    _config_cache = config_data
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)


# ==========================================
# GESTION DU FICHIER WEBHOOK.JSON
# ==========================================
WEBHOOK_PATH = "webhook.json"
_webhook_cache: dict | None = None


def charger_webhooks() -> dict:
    """Charge le dictionnaire {code: [{nom, url}, ...]} (depuis le cache si possible)."""
    global _webhook_cache
    if _webhook_cache is not None:
        return _webhook_cache

    if not os.path.exists(WEBHOOK_PATH):
        _webhook_cache = {}
        sauvegarder_webhooks(_webhook_cache)
        return _webhook_cache

    with open(WEBHOOK_PATH, "r", encoding="utf-8") as f:
        try:
            _webhook_cache = json.load(f)
        except json.JSONDecodeError:
            _webhook_cache = {}
    return _webhook_cache


def sauvegarder_webhooks(webhook_data: dict) -> None:
    """Sauvegarde le dictionnaire de webhooks et met à jour le cache mémoire."""
    global _webhook_cache
    _webhook_cache = webhook_data
    with open(WEBHOOK_PATH, "w", encoding="utf-8") as f:
        json.dump(webhook_data, f, indent=4, ensure_ascii=False)


# ==========================================
# GESTION DU FICHIER RAPPEL.JSON ET DES JOURS
# ==========================================
RAPPEL_PATH = "rappel.json"
_rappel_cache: dict | None = None

JOURS_MAP = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3,
    "vendredi": 4, "samedi": 5, "dimanche": 6
}

JOURS_NOMS = {
    0: "Lundi", 1: "Mardi", 2: "Mercredi", 3: "Jeudi",
    4: "Vendredi", 5: "Samedi", 6: "Dimanche"
}


def parser_jours(texte: str) -> tuple[list[int], str]:
    """Analyse une chaîne pour extraire la liste des jours (0 à 6) et formater un nom propre."""
    txt = texte.strip().lower()

    if txt in ("tous", "tous les jours", "touslesjours", "*", "chaque jour"):
        return list(range(7)), "Tous les jours"
    if txt in ("semaine", "du lundi au vendredi"):
        return [0, 1, 2, 3, 4], "Lundi au Vendredi"
    if txt in ("weekend", "week-end", "we"):
        return [5, 6], "Week-end (Samedi, Dimanche)"

    elements = [e.strip() for e in txt.replace("+", ",").replace("/", ",").split(",") if e.strip()]
    indices = []

    for el in elements:
        sous_els = [s.strip() for s in el.split() if s.strip()]
        for sub in sous_els:
            if sub in JOURS_MAP and JOURS_MAP[sub] not in indices:
                indices.append(JOURS_MAP[sub])

    indices.sort()
    if not indices:
        raise ValueError("Aucun jour valide n'a été reconnu.")

    if len(indices) == 7:
        nom_affichage = "Tous les jours"
    else:
        nom_affichage = ", ".join(JOURS_NOMS[i] for i in indices)

    return indices, nom_affichage


def charger_rappels() -> dict:
    """Charge le dictionnaire des rappels (depuis le cache si possible)."""
    global _rappel_cache
    if _rappel_cache is not None:
        return _rappel_cache

    if not os.path.exists(RAPPEL_PATH):
        _rappel_cache = {}
        sauvegarder_rappels(_rappel_cache)
        return _rappel_cache

    with open(RAPPEL_PATH, "r", encoding="utf-8") as f:
        try:
            _rappel_cache = json.load(f)
        except json.JSONDecodeError:
            _rappel_cache = {}
    return _rappel_cache


def sauvegarder_rappels(rappel_data: dict) -> None:
    """Sauvegarde les rappels et met à jour le cache mémoire."""
    global _rappel_cache
    _rappel_cache = rappel_data
    with open(RAPPEL_PATH, "w", encoding="utf-8") as f:
        json.dump(rappel_data, f, indent=4, ensure_ascii=False)


# ==========================================
# GESTION DU FICHIER CHOIXPROMO.JSON
# ==========================================
CHOIXPROMO_PATH = "choixpromo.json"
_choixpromo_cache: dict | None = None


def charger_choixpromo() -> dict:
    """Charge le dictionnaire {guild_id: {salon_liste, salon_destination, role_id, actif}}."""
    global _choixpromo_cache
    if _choixpromo_cache is not None:
        return _choixpromo_cache

    if not os.path.exists(CHOIXPROMO_PATH):
        _choixpromo_cache = {}
        sauvegarder_choixpromo(_choixpromo_cache)
        return _choixpromo_cache

    with open(CHOIXPROMO_PATH, "r", encoding="utf-8") as f:
        try:
            _choixpromo_cache = json.load(f)
        except json.JSONDecodeError:
            _choixpromo_cache = {}
    return _choixpromo_cache


def sauvegarder_choixpromo(data: dict) -> None:
    """Sauvegarde la configuration /choixpromo et met à jour le cache mémoire."""
    global _choixpromo_cache
    _choixpromo_cache = data
    with open(CHOIXPROMO_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


# ==========================================
# GESTION DU FICHIER FILIALE.JSON (SUIVI DES FILIALES)
# ==========================================
# Structure, bien rangée par serveur pour rester lisible :
# {
#   "<guild_id>": {
#       "nom_serveur": "Nom du serveur",
#       "parametres": {"actif": false, "heure": "23:30"},
#       "referent": {"salon_id": None, "joueur_id": None},
#       "filiales": {
#           "<salon_id>": {"joueur_id": "...", "nom_salon": "..."}
#       }
#   }
# }
FILIALE_PATH = "filiale.json"
_filiale_cache: dict | None = None


def charger_filiales() -> dict:
    """Charge le dictionnaire des filiales, rangé par serveur (depuis le cache si possible)."""
    global _filiale_cache
    if _filiale_cache is not None:
        return _filiale_cache

    if not os.path.exists(FILIALE_PATH):
        _filiale_cache = {}
        sauvegarder_filiales(_filiale_cache)
        return _filiale_cache

    with open(FILIALE_PATH, "r", encoding="utf-8") as f:
        try:
            _filiale_cache = json.load(f)
        except json.JSONDecodeError:
            _filiale_cache = {}
    return _filiale_cache


def sauvegarder_filiales(data: dict) -> None:
    """Sauvegarde filiale.json (rangé par serveur) et met à jour le cache mémoire."""
    global _filiale_cache
    _filiale_cache = data
    with open(FILIALE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def obtenir_ou_creer_serveur_filiale(data: dict, guild_id_str: str, nom_serveur: str = None) -> dict:
    """Renvoie (en la créant si besoin) l'entrée d'un serveur dans filiale.json, avec sa structure complète."""
    parametres_defaut = {
        "actif": False, "heure": None, "derniere_execution": None,
        "bouton_actif": False, "heure_rappel": None, "heure_recap": None,
        "derniere_execution_rappel": None, "derniere_execution_recap": None,
        "bouton_message": None,
        "tableau_actif": False, "salon_tableau_id": None, "heure_tableau": None,
        "tableau_message_id": None, "tableau_derniere_date": None,
        "relance_actif": False, "heure_relance": None, "derniere_execution_relance": None
    }
    referent_defaut = {"salon_id": None, "joueur_id": None, "role_id": None}
    injection_programmee_defaut = {
        "actif": False, "heure": None, "salon_id": None,
        "role_id": None, "joueur_id": None, "derniere_execution": None
    }

    if guild_id_str not in data:
        data[guild_id_str] = {
            "nom_serveur": nom_serveur or f"ID {guild_id_str}",
            "parametres": dict(parametres_defaut),
            "referent": dict(referent_defaut),
            "injection_programmee": dict(injection_programmee_defaut),
            "filiales": {}
        }
    else:
        data[guild_id_str].setdefault("parametres", dict(parametres_defaut))
        for cle, valeur in parametres_defaut.items():
            data[guild_id_str]["parametres"].setdefault(cle, valeur)
        data[guild_id_str].setdefault("referent", dict(referent_defaut))
        for cle, valeur in referent_defaut.items():
            data[guild_id_str]["referent"].setdefault(cle, valeur)
        data[guild_id_str].setdefault("injection_programmee", dict(injection_programmee_defaut))
        for cle, valeur in injection_programmee_defaut.items():
            data[guild_id_str]["injection_programmee"].setdefault(cle, valeur)
        data[guild_id_str].setdefault("filiales", {})
        if nom_serveur:
            data[guild_id_str]["nom_serveur"] = nom_serveur

    return data[guild_id_str]


def obtenir_mention_ping_filiale(info: dict) -> str | None:
    """
    Renvoie le texte de ping (utilisé dans `content=`) à utiliser pour une filiale donnée :
    - normalement, le joueur responsable ;
    - mais si ce joueur est marqué absent (/vacance), le ou les rôle(s) remplaçant(s)
      configurés sont ping à sa place (et le joueur n'est alors plus du tout notifié).
    Renvoie None si aucun ping n'est pertinent (absent sans rôle remplaçant configuré, ou
    aucun joueur assigné).
    """
    if info.get("absent"):
        roles_ids = info.get("role_remplacant_ids") or []
        if roles_ids:
            return " ".join(f"<@&{rid}>" for rid in roles_ids)
        return None

    joueur_id = info.get("joueur_id")
    return f"<@{joueur_id}>" if joueur_id else None


def obtenir_texte_affichage_responsable(info: dict) -> str:
    """
    Texte d'affichage (dans les embeds — jamais un ping réel) du responsable d'une filiale,
    en indiquant clairement si le joueur est en vacances et quel(s) rôle(s) le remplacent.
    """
    joueur_id = info.get("joueur_id")
    base = f"<@{joueur_id}>" if joueur_id else "*Aucun joueur assigné*"

    if info.get("absent"):
        roles_ids = info.get("role_remplacant_ids") or []
        roles_texte = ", ".join(f"<@&{rid}>" for rid in roles_ids) if roles_ids else "*aucun rôle configuré*"
        return f"{base} 🌴 *(en vacances → remplacé par {roles_texte})*"

    return base


def resoudre_salon_depuis_texte(guild: discord.Guild, texte: str):
    """Retrouve un salon textuel à partir d'une mention (#salon / <#id>), d'un ID brut ou d'un nom."""
    texte = (texte or "").strip()
    if not texte:
        return None

    correspondance_id = re.search(r"\d+", texte)
    if correspondance_id:
        salon = guild.get_channel(int(correspondance_id.group()))
        if isinstance(salon, discord.TextChannel):
            return salon

    nom_recherche = texte.lower().lstrip("#").strip()
    for salon in guild.text_channels:
        if salon.name.lower() == nom_recherche:
            return salon

    return None


def resoudre_role_depuis_texte(guild: discord.Guild, texte: str):
    """Retrouve un rôle à partir d'une mention (<@&id>), d'un ID brut ou d'un nom."""
    texte = (texte or "").strip()
    if not texte:
        return None

    correspondance_id = re.search(r"\d+", texte)
    if correspondance_id:
        role = guild.get_role(int(correspondance_id.group()))
        if role:
            return role

    nom_recherche = texte.lower().strip()
    for role in guild.roles:
        if role.name.lower() == nom_recherche:
            return role

    return None


def obtenir_config_salon(global_config: dict, guild_id: str, salon_id: str) -> dict:
    """Renvoie la configuration d'un salon à partir d'une config déjà chargée."""
    server_config = global_config.get(guild_id, {})
    salons_config = server_config.get("salons", {})

    return salons_config.get(salon_id, {
        "promo_min": 7,
        "positions_affichage": [1, 2, 3],
        "opportunite_position": 1,
        "auto_actif": False,
        "information": None
    })


# ==========================================
# UNITÉS MONÉTAIRES (G, T, P, E, Z, Y, R, Q, U, S, X, N, D)
# ==========================================
SUFFIXES_MONTANT = {
    "G": 10 ** 9,
    "T": 10 ** 12,
    "P": 10 ** 15,
    "E": 10 ** 18,
    "Z": 10 ** 21,
    "Y": 10 ** 24,
    "R": 10 ** 27,
    "Q": 10 ** 30,
    "U": 10 ** 33,
    "S": 10 ** 36,
    "X": 10 ** 39,
    "N": 10 ** 42,
    "D": 10 ** 45,
}

_UNITES_MONTANT_TRIEES = sorted(SUFFIXES_MONTANT.items(), key=lambda kv: kv[1], reverse=True)


def parser_montant(texte: str) -> int:
    """Convertit un montant saisi par l'utilisateur en entier brut."""
    if texte is None:
        raise ValueError("Montant vide.")

    brut = texte.strip().replace(" ", "").replace("\u202f", "")
    if not brut:
        raise ValueError("Montant vide.")

    suffixe = brut[-1].upper()
    multiplicateur = SUFFIXES_MONTANT.get(suffixe)

    if multiplicateur is not None:
        partie_numerique = brut[:-1]
    else:
        partie_numerique = brut
        multiplicateur = 1

    partie_numerique = partie_numerique.replace(",", ".")
    if not partie_numerique:
        raise ValueError(f"Montant invalide : {texte}")

    try:
        valeur = Decimal(partie_numerique)
    except InvalidOperation:
        raise ValueError(f"Montant invalide : {texte}")

    return int((valeur * multiplicateur).to_integral_value(rounding=ROUND_HALF_UP))


def formater_prix(valeur) -> str:
    """Formate un montant avec le suffixe le plus adapté."""
    try:
        valeur_dec = Decimal(valeur)
    except (TypeError, ValueError, InvalidOperation):
        return str(valeur)

    signe = "-" if valeur_dec < 0 else ""
    valeur_abs = abs(valeur_dec)

    for suffixe, seuil in _UNITES_MONTANT_TRIEES:
        if valeur_abs >= seuil:
            resultat = (valeur_abs / seuil).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            texte_nombre = f"{resultat:f}".rstrip("0").rstrip(".")
            return f"{signe}{texte_nombre}{suffixe}"

    return f"{signe}{int(valeur_abs):,}".replace(",", " ")


# ==========================================
# CLIENT HTTP PARTAGÉ
# ==========================================
http_client: httpx.AsyncClient | None = None


# ==========================================
# ENVOI DE WEBHOOK.JSON VERS GITHUB
# ==========================================
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_REPO = os.environ.get("GITHUB_REPO")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")
GITHUB_FILE_PATH = os.environ.get("GITHUB_FILE_PATH", "webhook.json")


async def pousser_webhook_vers_github(donnees: dict) -> tuple[bool, str]:
    """Envoie le contenu de webhook.json sur GitHub."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False, "Variables GITHUB_TOKEN / GITHUB_REPO manquantes sur Katabump."

    url_api = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    entetes = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json"
    }

    sha_existant = None
    try:
        reponse_get = await http_client.get(url_api, headers=entetes, params={"ref": GITHUB_BRANCH})
        if reponse_get.status_code == 200:
            sha_existant = reponse_get.json().get("sha")
        elif reponse_get.status_code not in (404,):
            return False, f"Erreur GitHub (lecture) : statut {reponse_get.status_code}"
    except Exception as e:
        return False, f"Erreur réseau vers GitHub (lecture) : {e}"

    contenu_json = json.dumps(donnees, indent=4, ensure_ascii=False)
    contenu_base64 = base64.b64encode(contenu_json.encode("utf-8")).decode("utf-8")

    corps_requete = {
        "message": "🔄 Mise à jour de webhook.json via /webhook",
        "content": contenu_base64,
        "branch": GITHUB_BRANCH
    }
    if sha_existant:
        corps_requete["sha"] = sha_existant

    try:
        reponse_put = await http_client.put(url_api, headers=entetes, json=corps_requete)
        if reponse_put.status_code in (200, 201):
            return True, "OK"
        return False, f"Erreur GitHub (écriture) : statut {reponse_put.status_code} — {reponse_put.text[:200]}"
    except Exception as e:
        return False, f"Erreur réseau vers GitHub (écriture) : {e}"


# ==========================================
# STRUCTURE DU BOT & TÂCHES AUTOMATIQUES
# ==========================================
class MonBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        global http_client
        http_client = httpx.AsyncClient(timeout=15.0)
        # Vue persistante : le bouton "✅ Filiale gérée" doit continuer à fonctionner
        # même après un redémarrage du bot (les messages de rappel restent cliquables).
        self.add_view(VueBoutonFilialeGeree())
        # Vue persistante : le bouton "Remplir l'injection du jour" doit rester cliquable
        # même après un redémarrage du bot.
        self.add_view(VueDemandeInjectionProgrammee())

    async def on_ready(self):
        print(f"🤖 Connecté en tant que: {self.user.name}")
        try:
            synced = await self.tree.sync()
            print(f"🔗 {len(synced)} commande(s) synchronisée(s)")
        except Exception as e:
            print(f"❌ Erreur lors de la synchronisation : {e}")

        if not auto_promo_task.is_running():
            auto_promo_task.start(self)
        if not rappel_task.is_running():
            rappel_task.start(self)
        if not choixpromo_task.is_running():
            choixpromo_task.start(self)
        if not filiale_task.is_running():
            filiale_task.start(self)
        if not filiale_rappel_bouton_task.is_running():
            filiale_rappel_bouton_task.start(self)
        if not filiale_recap_bouton_task.is_running():
            filiale_recap_bouton_task.start(self)
        if not filiale_tableau_task.is_running():
            filiale_tableau_task.start(self)
        if not filiale_relance_task.is_running():
            filiale_relance_task.start(self)
        if not filiale_injection_programmee_task.is_running():
            filiale_injection_programmee_task.start(self)
        if not api_refresh_task.is_running():
            api_refresh_task.start(self)

    async def close(self):
        if http_client is not None:
            await http_client.aclose()
        await super().close()


heure_cible = time(hour=4, minute=5, tzinfo=ZoneInfo("Europe/Paris"))
heure_maj_api = time(hour=4, minute=2, tzinfo=ZoneInfo("Europe/Paris"))


@tasks.loop(time=heure_maj_api)
async def api_refresh_task(bot_client):
    """Force chaque jour à 04h02 le renouvellement du fichier api_cache.json."""
    print("⏰ [04h02] Renouvellement automatique du cache API...")
    await recuperer_donnees_api(forcer=True)


@tasks.loop(time=heure_cible)
async def auto_promo_task(bot_client):
    print("⏰ Déclenchement automatique multi-serveurs et multi-salons (04h05 Paris)...")
    global_config = charger_config()

    for guild_id_str, server_data in global_config.items():
        salons = server_data.get("salons", {})
        guild_obj = bot_client.get_guild(int(guild_id_str))
        nom_serveur = server_data.get("nom_serveur") or (guild_obj.name if guild_obj else None) or f"ID {guild_id_str}"

        for salon_id_str, config_salon in salons.items():
            if not config_salon.get("auto_actif", False):
                continue

            salon = bot_client.get_channel(int(salon_id_str))
            if salon:
                nom_salon = f"#{salon.name}"
                try:
                    await salon.send("📢 **bien à acheter**")
                    await generer_et_envoyer_promos(salon, guild_id_str, salon_id_str)

                    information = config_salon.get("information")
                    if information:
                        await salon.send(f"ℹ️ **[Rappel]**\n{information}")
                except Exception as e:
                    print(f"❌ Impossible d'envoyer dans le serveur « {nom_serveur} » (salon {nom_salon}, ID {salon_id_str}) : {e}")
            else:
                print(f"❌ Salon introuvable dans le serveur « {nom_serveur} » (salon ID {salon_id_str}).")


@tasks.loop(minutes=1)
async def rappel_task(bot_client):
    """Vérifie chaque minute s'il y a des rappels automatiques à envoyer."""
    now = datetime.now(ZoneInfo("Europe/Paris"))
    jour_actuel_idx = now.weekday()  # 0 = Lundi, ..., 6 = Dimanche
    heure_actuelle_str = now.strftime("%H:%M")

    rappels = charger_rappels()
    if not rappels:
        return

    for rappel_id, item in list(rappels.items()):
        try:
            jours_indices = item.get("jours_indices")
            if jours_indices is None and "jour_index" in item:
                jours_indices = [item["jour_index"]]

            heure_str = item.get("heure")

            if jours_indices and jour_actuel_idx in jours_indices and heure_str == heure_actuelle_str:
                salon_id = int(item.get("salon_id"))
                salon = bot_client.get_channel(salon_id)
                if salon:
                    msg = item.get("message", "")
                    await salon.send(f"⏰ **[Rappel Automatique]**\n{msg}")
                else:
                    print(f"❌ Salon introuvable pour le rappel ID {rappel_id} (salon ID {salon_id})")
        except Exception as e:
            print(f"❌ Erreur lors de l'envoi du rappel ID {rappel_id} : {e}")


heure_choixpromo = time(hour=4, minute=30, tzinfo=ZoneInfo("Europe/Paris"))


@tasks.loop(time=heure_choixpromo)
async def choixpromo_task(bot_client):
    """Envoie chaque jour à 04h30 la demande de sélection des promos pour chaque serveur configuré."""
    print("⏰ Déclenchement automatique du système /choixpromo (04h30 Paris)...")
    donnees_choixpromo = charger_choixpromo()

    for guild_id_str, config_choix in donnees_choixpromo.items():
        if not config_choix.get("actif", False):
            continue
        try:
            succes, message = await envoyer_demande_choixpromo(bot_client, guild_id_str, config_choix)
            if not succes:
                print(f"❌ [choixpromo] Serveur {guild_id_str} : {message}")
        except Exception as e:
            print(f"❌ [choixpromo] Erreur inattendue pour le serveur {guild_id_str} : {e}")


@tasks.loop(minutes=1)
async def filiale_task(bot_client):
    """
    Vérifie chaque minute si l'heure configurée (/param) correspond à l'heure actuelle
    (Europe/Paris) pour un serveur, et envoie dans ce cas le formulaire quotidien
    de suivi des filiales au gestionnaire (référent) de ce serveur.
    """
    now = datetime.now(ZoneInfo("Europe/Paris"))
    heure_actuelle_str = now.strftime("%H:%M")

    donnees_filiales = charger_filiales()
    if not donnees_filiales:
        return

    aujourdhui = _date_paris_aujourdhui()

    for guild_id_str, server_data in list(donnees_filiales.items()):
        parametres = server_data.get("parametres", {})
        if not parametres.get("actif", False):
            continue
        if parametres.get("heure") != heure_actuelle_str:
            continue
        if parametres.get("derniere_execution") == aujourdhui:
            # Déjà envoyé aujourd'hui (automatiquement ou via /verif filiale) : on ne renvoie pas 2 fois.
            continue

        try:
            succes, message = await envoyer_formulaire_filiales(bot_client, guild_id_str, server_data)
            if succes:
                donnees_filiales[guild_id_str]["parametres"]["derniere_execution"] = aujourdhui
                sauvegarder_filiales(donnees_filiales)
            else:
                print(f"❌ [filiale] Serveur {guild_id_str} : {message}")
        except Exception as e:
            print(f"❌ [filiale] Erreur inattendue pour le serveur {guild_id_str} : {e}")


@tasks.loop(minutes=1)
async def filiale_rappel_bouton_task(bot_client):
    """
    Système « bouton » : chaque minute, vérifie si l'heure de rappel configurée
    (/param bouton) correspond à l'heure actuelle (Europe/Paris). Si oui, envoie dans
    CHAQUE salon de filiale enregistré un message de rappel avec un bouton « ✅ Filiale gérée ».
    """
    now = datetime.now(ZoneInfo("Europe/Paris"))
    heure_actuelle_str = now.strftime("%H:%M")
    aujourdhui = _date_paris_aujourdhui()

    donnees_filiales = charger_filiales()
    if not donnees_filiales:
        return

    for guild_id_str, server_data in list(donnees_filiales.items()):
        parametres = server_data.get("parametres", {})
        if not parametres.get("bouton_actif", False):
            continue
        if parametres.get("heure_rappel") != heure_actuelle_str:
            continue
        if parametres.get("derniere_execution_rappel") == aujourdhui:
            continue

        try:
            nb_envoyes, nb_erreurs = await envoyer_rappels_bouton_filiales(bot_client, server_data)
            print(f"⏰ [filiale] Rappels bouton envoyés pour le serveur {guild_id_str} : {nb_envoyes} ok, {nb_erreurs} erreur(s).")
            donnees_filiales[guild_id_str]["parametres"]["derniere_execution_rappel"] = aujourdhui
            sauvegarder_filiales(donnees_filiales)
        except Exception as e:
            print(f"❌ [filiale] Erreur inattendue (rappel bouton) pour le serveur {guild_id_str} : {e}")


@tasks.loop(minutes=1)
async def filiale_recap_bouton_task(bot_client):
    """
    Système « bouton » : chaque minute, vérifie si l'heure de récapitulatif configurée
    (/param bouton) correspond à l'heure actuelle (Europe/Paris). Si oui, envoie dans le
    salon référent le récapitulatif des filiales gérées / non gérées aujourd'hui.
    """
    now = datetime.now(ZoneInfo("Europe/Paris"))
    heure_actuelle_str = now.strftime("%H:%M")
    aujourdhui = _date_paris_aujourdhui()

    donnees_filiales = charger_filiales()
    if not donnees_filiales:
        return

    for guild_id_str, server_data in list(donnees_filiales.items()):
        parametres = server_data.get("parametres", {})
        if not parametres.get("bouton_actif", False):
            continue
        if parametres.get("heure_recap") != heure_actuelle_str:
            continue
        if parametres.get("derniere_execution_recap") == aujourdhui:
            continue

        try:
            succes, message = await envoyer_recap_bouton_filiales(bot_client, server_data)
            if succes:
                donnees_filiales[guild_id_str]["parametres"]["derniere_execution_recap"] = aujourdhui
                sauvegarder_filiales(donnees_filiales)
            else:
                print(f"❌ [filiale] Serveur {guild_id_str} (récap bouton) : {message}")
        except Exception as e:
            print(f"❌ [filiale] Erreur inattendue (récap bouton) pour le serveur {guild_id_str} : {e}")


@tasks.loop(minutes=1)
async def filiale_tableau_task(bot_client):
    """
    Chaque minute, vérifie si l'heure de création configurée (/param tableau) correspond
    à l'heure actuelle (Europe/Paris). Si oui, (re)crée le message quotidien "tableau" listant
    l'état (fait/pas fait) de chaque filiale, dans le salon configuré. Ce message sera ensuite
    mis à jour en direct à chaque clic sur le bouton « Filiale gérée ✅ » d'une filiale.
    """
    now = datetime.now(ZoneInfo("Europe/Paris"))
    heure_actuelle_str = now.strftime("%H:%M")
    aujourdhui = _date_paris_aujourdhui()

    donnees_filiales = charger_filiales()
    if not donnees_filiales:
        return

    for guild_id_str, server_data in list(donnees_filiales.items()):
        parametres = server_data.get("parametres", {})
        if not parametres.get("tableau_actif", False):
            continue
        if parametres.get("heure_tableau") != heure_actuelle_str:
            continue
        if parametres.get("tableau_derniere_date") == aujourdhui:
            continue

        try:
            succes, message = await actualiser_tableau_filiales(bot_client, guild_id_str, forcer_nouveau=True)
            if not succes:
                print(f"❌ [filiale] Serveur {guild_id_str} (tableau) : {message}")
        except Exception as e:
            print(f"❌ [filiale] Erreur inattendue (tableau) pour le serveur {guild_id_str} : {e}")


@tasks.loop(minutes=1)
async def filiale_relance_task(bot_client):
    """
    Chaque minute, vérifie si l'heure de relance configurée (/param relance) correspond à
    l'heure actuelle (Europe/Paris). Si oui, envoie une relance UNIQUEMENT dans les salons
    des filiales pas encore marquées comme gérées aujourd'hui.
    """
    now = datetime.now(ZoneInfo("Europe/Paris"))
    heure_actuelle_str = now.strftime("%H:%M")
    aujourdhui = _date_paris_aujourdhui()

    donnees_filiales = charger_filiales()
    if not donnees_filiales:
        return

    for guild_id_str, server_data in list(donnees_filiales.items()):
        parametres = server_data.get("parametres", {})
        if not parametres.get("relance_actif", False):
            continue
        if parametres.get("heure_relance") != heure_actuelle_str:
            continue
        if parametres.get("derniere_execution_relance") == aujourdhui:
            continue

        try:
            nb_envoyes, nb_erreurs = await envoyer_relances_filiales_non_faites(bot_client, server_data)
            print(f"⏰ [filiale] Relances envoyées pour le serveur {guild_id_str} : {nb_envoyes} ok, {nb_erreurs} erreur(s).")
            donnees_filiales[guild_id_str]["parametres"]["derniere_execution_relance"] = aujourdhui
            sauvegarder_filiales(donnees_filiales)
        except Exception as e:
            print(f"❌ [filiale] Erreur inattendue (relance) pour le serveur {guild_id_str} : {e}")


bot = MonBot()


@bot.tree.error
async def gestion_erreur_commandes(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """
    Gestionnaire global d'erreurs pour toutes les commandes slash : évite que l'interaction
    échoue silencieusement côté Discord et affiche un message clair à l'utilisateur.
    """
    if isinstance(error, app_commands.TransformerError) and error.type is discord.Member:
        message = (
            "❌ Le joueur indiqué est introuvable. Quand tu remplis le champ `joueur`, "
            "attends que Discord te propose la liste des membres et **clique sur le bon membre "
            "dans la liste** (ou utilise un `@mention`) — n'appuie pas sur Entrée après avoir "
            "juste tapé du texte libre."
        )
    elif isinstance(error, app_commands.TransformerError) and error.type is discord.TextChannel:
        message = (
            "❌ Le salon indiqué est introuvable. Sélectionne-le dans la liste proposée par Discord "
            "au lieu de taper son nom en texte libre."
        )
    elif isinstance(error, app_commands.MissingPermissions):
        message = "❌ Tu n'as pas la permission nécessaire (« Gérer le serveur ») pour utiliser cette commande."
    elif isinstance(error, app_commands.CommandOnCooldown):
        message = f"⏳ Cette commande est en cooldown, réessaie dans {error.retry_after:.1f}s."
    else:
        print(f"❌ [commande] Erreur non gérée dans '{interaction.command.name if interaction.command else '?'}' : {error}")
        message = "❌ Une erreur inattendue est survenue lors de l'exécution de cette commande."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass


# ==========================================
# NOMS ORDINAUX PARTAGÉS (utilisés pour /promo et /choixpromo)
# ==========================================
NOMS_ORDINAUX = {
    1: "Première promo", 2: "Seconde promo", 3: "Troisième promo",
    4: "Quatrième promo", 5: "Cinquième promo", 6: "Sixième promo",
    7: "Septième promo", 8: "Huitième promo", 9: "Neuvième promo", 10: "Dixième promo"
}


# ==========================================
# BOUTON "COPIER LE PRIX DE REVENTE"
# ==========================================
class VueCopierPrix(discord.ui.View):
    def __init__(self, prix_revente: int):
        super().__init__(timeout=None)
        self.prix_revente = prix_revente

    @discord.ui.button(label="📋 Copier le prix", style=discord.ButtonStyle.secondary)
    async def copier_prix(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(f"`{self.prix_revente}`", ephemeral=True)


# ==========================================
# FONCTIONS LOGIQUES ET APPELS API
# ==========================================
# ==========================================
# CACHE JOURNALIER DES DONNÉES API (api_cache.json)
# ==========================================
API_CACHE_PATH = "api_cache.json"
_api_cache_memoire: dict | None = None  # {"date": "YYYY-MM-DD", "data": {...}}


def _date_paris_aujourdhui() -> str:
    return datetime.now(ZoneInfo("Europe/Paris")).strftime("%Y-%m-%d")


async def recuperer_donnees_api(forcer: bool = False) -> dict:
    """
    Récupère les données de l'API des bâtiments avec authentification EmpireImmo.

    Pour ne pas dépasser les limites de requêtes, le résultat est mis en cache
    une fois par jour (heure de Paris) : le fichier api_cache.json est écrit à
    la racine dès le premier appel de la journée, puis relu depuis le disque
    (ou la mémoire) pour tous les appels suivants de la même journée.
    Utiliser forcer=True pour ignorer le cache et forcer un nouveau téléchargement.
    
    ✅ CORRIGÉ: Utilise le paramètre 'key' comme requis par l'API EmpireImmo
    Format: https://monde8.empireimmo.com/api/buildings.json?key=YOUR_API_KEY
    """
    global _api_cache_memoire
    aujourdhui = _date_paris_aujourdhui()

    # 1) Cache mémoire encore valide pour aujourd'hui
    if not forcer and _api_cache_memoire is not None and _api_cache_memoire.get("date") == aujourdhui:
        return _api_cache_memoire.get("data", {})

    # 2) Cache disque encore valide pour aujourd'hui
    if not forcer and os.path.exists(API_CACHE_PATH):
        try:
            with open(API_CACHE_PATH, "r", encoding="utf-8") as f:
                cache_disque = json.load(f)
            if cache_disque.get("date") == aujourdhui and "data" in cache_disque:
                _api_cache_memoire = cache_disque
                return cache_disque.get("data", {})
        except (json.JSONDecodeError, OSError):
            pass

    # 3) Récupération des données avec authentification API Key
    base_url = os.environ.get("API_URL", "https://monde8.empireimmo.com/api/buildings.json")
    api_key = os.environ.get("API_KEY", "")
    
    # ✅ CORRECTION: Ajouter le paramètre 'key' à l'URL
    if api_key and api_key != "secret":
        url = f"{base_url}?key={api_key}"
    else:
        url = base_url
        print("⚠️ [API] ATTENTION: API_KEY non configurée ou toujours à 'secret' dans .env")
        print(f"⚠️ [API] Format attendu: eiK8_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
    
    print(f"🌐 [API] Requête envoyée vers {base_url}...")
    
    try:
        reponse = await http_client.get(url, timeout=15.0)
        reponse.raise_for_status()
        donnees_fraiches = reponse.json()
        print(f"✅ [API] Réponse reçue avec succès (statut {reponse.status_code}).")
    except httpx.HTTPStatusError as e:
        # Gestion des erreurs HTTP
        if e.response.status_code == 401:
            print(f"❌ [API] Erreur 401 Unauthorized")
            print(f"   → Votre clé API est invalide, expirée ou manquante")
            print(f"   → Vérifiez: Options > API sur https://monde8.empireimmo.com/misc/options.php#api")
            print(f"   → La clé doit commencer par: eiK8_")
        elif e.response.status_code == 403:
            print(f"❌ [API] Erreur 403 Forbidden - Accès refusé (permissions insuffisantes)")
        elif e.response.status_code == 429:
            print(f"❌ [API] Erreur 429 Too Many Requests - Trop d'appels API")
        else:
            print(f"❌ [API] Erreur HTTP {e.response.status_code}")
            
        # Fallback au cache s'il existe
        if _api_cache_memoire is not None:
            print(f"⚠️ [API] Utilisation du cache précédent comme secours")
            return _api_cache_memoire.get("data", {})
        return {}
        
    except httpx.ConnectError:
        print(f"❌ [API] Impossible de se connecter à {base_url}")
        print(f"   → Vérifiez votre connexion internet")
        if _api_cache_memoire is not None:
            return _api_cache_memoire.get("data", {})
        return {}
        
    except httpx.TimeoutException:
        print(f"❌ [API] Délai d'attente dépassé (timeout)")
        if _api_cache_memoire is not None:
            return _api_cache_memoire.get("data", {})
        return {}
        
    except Exception as e:
        print(f"❌ [API] Erreur inattendue: {e}")
        if _api_cache_memoire is not None:
            return _api_cache_memoire.get("data", {})
        return {}

    _api_cache_memoire = {"date": aujourdhui, "data": donnees_fraiches}
    try:
        with open(API_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_api_cache_memoire, f, indent=4, ensure_ascii=False)
        print(f"💾 [API] api_cache.json mis à jour avec succès pour la journée du {aujourdhui}.")
    except OSError as e:
        print(f"⚠️ [API] Impossible d'écrire le cache API sur disque : {e}")

    return donnees_fraiches


async def generer_et_envoyer_promos(destination, guild_id_str, salon_id_str, interaction=None):
    global_config = charger_config()
    config_salon = obtenir_config_salon(global_config, guild_id_str, salon_id_str)
    promo_min = config_salon.get("promo_min", 7)
    positions_demandees = config_salon.get("positions_affichage", [1, 2, 3])
    pos_opportunite = config_salon.get("opportunite_position", 1)
    filtres_noms = config_salon.get("filtres_noms")  # Liste de mots-clés ou None
    message_aucune_promo = config_salon.get("message_aucune_promo")  # Message custom ou None

    donnees = await recuperer_donnees_api()
    liste_entreprises = donnees.get("batiments_entreprise", [])

    if not liste_entreprises:
        msg = "⚠️ Aucun bâtiment d'entreprise trouvé ou l'API n'a pas répondu."
        if interaction:
            await interaction.followup.send(msg)
        else:
            await destination.send(msg)
        return

    # Filtre 1: Promotion minimum
    en_promotion = [b for b in liste_entreprises if int(b.get("promotion", 0)) >= promo_min]
    
    # Filtre 2: Mots-clés dans le nom (si des filtres sont configurés)
    if filtres_noms:
        en_promotion = [
            b for b in en_promotion 
            if any(filtre in b.get("nom", "").lower() for filtre in filtres_noms)
        ]
    
    # Si aucune promo valide n'a été trouvée
    if not en_promotion:
        # Déterminer le message à envoyer
        if message_aucune_promo:
            msg = message_aucune_promo
        else:
            msg = f"📉 Aucune promotion d'au moins {promo_min}% actuellement."
        
        if interaction:
            await interaction.followup.send(msg)
        else:
            await destination.send(msg)
        return

    entreprises_triees = sorted(en_promotion, key=lambda x: int(x.get("valeur", 0)), reverse=True)

    liste_embeds = []
    liste_prix_revente = []

    for index, batiment in enumerate(entreprises_triees, start=1):
        if index not in positions_demandees:
            continue

        nom = batiment.get("nom", "Sans nom")
        valeur_api = int(batiment.get("valeur", 0))
        promo_val = int(batiment.get("promotion", 0))

        pourcentage_restant = (100 - promo_val) / 100
        if pourcentage_restant <= 0:
            continue

        prix_initial = valeur_api / pourcentage_restant
        prix_revente = math.floor(prix_initial * 1.15)

        if index == pos_opportunite:
            couleur = discord.Color.gold()
            titre_boite = "⭐ [OPPORTUNITÉ TOP 1]"
        else:
            couleur = discord.Color.green()
            nom_promo = NOMS_ORDINAUX.get(index, f"{index}e promo")
            titre_boite = f"🏢 [{nom_promo}]"

        embed_batiment = discord.Embed(title=titre_boite, description=f"### {nom}", color=couleur)
        embed_batiment.add_field(name="🏷️ Réduction", value=f"-{promo_val}%", inline=True)
        embed_batiment.add_field(name="📈 Prix de Revente", value=f"**{formater_prix(prix_revente)}** 💰", inline=True)

        liste_embeds.append(embed_batiment)
        liste_prix_revente.append(prix_revente)

    if not liste_embeds:
        msg = f"🔍 Les positions demandées {positions_demandees} ne sont pas disponibles."
        if interaction:
            await interaction.followup.send(msg)
        else:
            await destination.send(msg)
        return

    for i, (embed_batiment, prix_revente) in enumerate(zip(liste_embeds, liste_prix_revente)):
        vue = VueCopierPrix(prix_revente)
        if interaction and i == 0:
            await interaction.followup.send(embed=embed_batiment, view=vue)
        else:
            await destination.send(embed=embed_batiment, view=vue)


# ==========================================
# SYSTÈME /choixpromo : SÉLECTION MANUELLE DES PROMOS DU JOUR
# ==========================================
def construire_liste_promos_du_jour(donnees: dict, promo_min: int = 1) -> list[dict]:
    """
    Construit la liste triée (par prix de revente décroissant) de tous les bâtiments
    d'entreprise actuellement en promotion, avec leur prix de revente calculé.
    """
    liste_entreprises = donnees.get("batiments_entreprise", [])
    resultats = []

    for batiment in liste_entreprises:
        promo_val = int(batiment.get("promotion", 0))
        if promo_val < promo_min:
            continue

        valeur_api = int(batiment.get("valeur", 0))
        pourcentage_restant = (100 - promo_val) / 100
        if pourcentage_restant <= 0:
            continue

        prix_initial = valeur_api / pourcentage_restant
        prix_revente = math.floor(prix_initial * 1.15)

        resultats.append({
            "nom": batiment.get("nom", "Sans nom"),
            "promotion": promo_val,
            "prix_revente": prix_revente
        })

    resultats.sort(key=lambda x: x["prix_revente"], reverse=True)
    return resultats


class ModalOrdrePromo(discord.ui.Modal, title="Ordre de priorité d'achat"):
    """Modal permettant de saisir l'ordre d'achat prioritaire parmi les promos sélectionnées."""

    def __init__(self, vue_parent: "VueChoixPromo"):
        super().__init__()
        self.vue_parent = vue_parent

        valeurs_defaut = ", ".join(str(i + 1) for i in sorted(vue_parent.selection_courante))
        self.ordre_input = discord.ui.TextInput(
            label="Ordre (numéros séparés par virgule)",
            placeholder="Ex: 3, 1, 2 → le N°3 sera acheté en priorité (opportunité du jour)",
            default=valeurs_defaut,
            required=True,
            style=discord.TextStyle.short,
            max_length=200
        )
        self.add_item(self.ordre_input)

    async def on_submit(self, interaction: discord.Interaction):
        texte = self.ordre_input.value
        try:
            numeros = [int(x.strip()) for x in texte.replace(";", ",").split(",") if x.strip()]
        except ValueError:
            await interaction.response.send_message(
                "❌ Format invalide. Utilise uniquement des numéros séparés par des virgules (ex: 3, 1, 2).",
                ephemeral=True
            )
            return

        indices_demandes = [n - 1 for n in numeros]
        set_selection = set(self.vue_parent.selection_courante)
        set_demande = set(indices_demandes)

        if set_demande != set_selection or len(indices_demandes) != len(set_demande):
            numeros_attendus = ", ".join(str(i + 1) for i in sorted(set_selection))
            await interaction.response.send_message(
                f"❌ L'ordre doit contenir exactement les numéros de ta sélection actuelle, "
                f"chacun une seule fois. Numéros attendus : **{numeros_attendus}**.",
                ephemeral=True
            )
            return

        self.vue_parent.ordre_choisi = indices_demandes
        premier = self.vue_parent.promos[indices_demandes[0]]["nom"]
        await interaction.response.send_message(
            f"✅ Ordre de priorité enregistré ! **{premier}** sera affiché comme l'opportunité du jour. "
            f"Tu peux maintenant cliquer sur **Valider l'envoi**.",
            ephemeral=True
        )


class VueChoixPromo(discord.ui.View):
    """
    Vue affichée dans le salon de sélection : un menu déroulant (multi-sélection)
    listant les promos du jour, un bouton pour définir l'ordre de priorité d'achat,
    et un bouton pour valider et envoyer les promos choisies (dans cet ordre) dans
    le salon de destination.
    """

    def __init__(self, promos: list[dict], salon_destination_id: str):
        super().__init__(timeout=None)
        self.promos = promos
        self.salon_destination_id = salon_destination_id
        self.selection_courante: list[int] = []
        self.ordre_choisi: list[int] | None = None

        options = []
        for i, promo in enumerate(promos[:25]):
            description = f"-{promo['promotion']}% • {formater_prix(promo['prix_revente'])} 💰"
            options.append(discord.SelectOption(
                label=promo["nom"][:100],
                description=description[:100],
                value=str(i)
            ))

        self.select_menu = discord.ui.Select(
            placeholder="📋 Sélectionne les promos à envoyer...",
            min_values=1,
            max_values=len(options),
            options=options
        )
        self.select_menu.callback = self.on_select
        self.add_item(self.select_menu)

    async def on_select(self, interaction: discord.Interaction):
        self.selection_courante = [int(v) for v in self.select_menu.values]
        # La sélection a changé : un éventuel ordre défini précédemment n'est plus valable.
        self.ordre_choisi = None
        await interaction.response.send_message(
            f"✅ {len(self.selection_courante)} promo(s) sélectionnée(s).\n"
            f"👉 Clique sur **🔢 Définir l'ordre d'achat** pour choisir laquelle acheter en priorité "
            f"(sinon l'ordre par défaut sera utilisé), puis sur **✅ Valider l'envoi**.",
            ephemeral=True
        )

    @discord.ui.button(label="🔢 Définir l'ordre d'achat", style=discord.ButtonStyle.primary)
    async def definir_ordre(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selection_courante:
            await interaction.response.send_message(
                "❌ Sélectionne d'abord au moins une promo dans le menu ci-dessus.",
                ephemeral=True
            )
            return
        await interaction.response.send_modal(ModalOrdrePromo(self))

    @discord.ui.button(label="✅ Valider l'envoi", style=discord.ButtonStyle.success)
    async def valider(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selection_courante:
            await interaction.response.send_message(
                "❌ Sélectionne d'abord au moins une promo dans le menu ci-dessus.",
                ephemeral=True
            )
            return

        salon_destination = interaction.client.get_channel(int(self.salon_destination_id))
        if salon_destination is None:
            await interaction.response.send_message(
                "❌ Le salon de destination configuré est introuvable (il a peut-être été supprimé).",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        # Si aucun ordre personnalisé n'a été défini via la modal, on garde l'ordre par défaut
        # (numéros croissants tels qu'affichés dans la liste des promos du jour).
        ordre_final = self.ordre_choisi if self.ordre_choisi is not None else sorted(self.selection_courante)

        for rang, i in enumerate(ordre_final, start=1):
            promo = self.promos[i]

            if rang == 1:
                couleur = discord.Color.gold()
                titre_boite = "⭐ [OPPORTUNITÉ DU JOUR]"
            else:
                couleur = discord.Color.green()
                nom_promo = NOMS_ORDINAUX.get(rang, f"{rang}e promo")
                titre_boite = f"🏢 [{nom_promo}]"

            embed = discord.Embed(title=titre_boite, description=f"### {promo['nom']}", color=couleur)
            embed.add_field(name="🏷️ Réduction", value=f"-{promo['promotion']}%", inline=True)
            embed.add_field(name="📈 Prix de Revente", value=f"**{formater_prix(promo['prix_revente'])}** 💰", inline=True)
            vue_prix = VueCopierPrix(promo["prix_revente"])
            await salon_destination.send(embed=embed, view=vue_prix)

        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except discord.HTTPException:
            pass

        await interaction.followup.send(
            f"📤 {len(ordre_final)} promo(s) envoyée(s) dans <#{self.salon_destination_id}> dans l'ordre de priorité choisi !",
            ephemeral=True
        )


async def envoyer_demande_choixpromo(bot_client, guild_id_str: str, config_choix: dict) -> tuple[bool, str]:
    """
    Envoie dans le salon de sélection la liste des promos du jour (avec ping du rôle)
    et le menu de sélection permettant de choisir quelles promos envoyer dans le
    salon de destination.
    """
    salon_liste_id = config_choix.get("salon_liste")
    salon_destination_id = config_choix.get("salon_destination")
    role_id = config_choix.get("role_id")

    if not salon_liste_id or not salon_destination_id or not role_id:
        return False, "Configuration incomplète (salon_liste / salon_destination / role manquant). Utilise `/choixpromo configurer`."

    salon_liste = bot_client.get_channel(int(salon_liste_id))
    if salon_liste is None:
        return False, f"Le salon de sélection est introuvable (ID {salon_liste_id})."

    if bot_client.get_channel(int(salon_destination_id)) is None:
        return False, f"Le salon de destination est introuvable (ID {salon_destination_id})."

    donnees = await recuperer_donnees_api()
    promos = construire_liste_promos_du_jour(donnees)

    if not promos:
        try:
            await salon_liste.send(f"<@&{role_id}>\n📉 Aucune promotion disponible aujourd'hui.")
        except discord.Forbidden:
            return False, (
                f"Permissions manquantes dans <#{salon_liste_id}> (le bot doit pouvoir voir ce salon "
                f"et y envoyer des messages)."
            )
        except discord.HTTPException as e:
            return False, f"Erreur Discord lors de l'envoi dans <#{salon_liste_id}> : {e}"
        return True, "Aucune promo disponible aujourd'hui : message envoyé sans sélection."

    lignes = [
        f"**{i + 1}.** {p['nom']} — `-{p['promotion']}%` — **{formater_prix(p['prix_revente'])}** 💰"
        for i, p in enumerate(promos[:25])
    ]
    texte_liste = "\n".join(lignes)
    if len(promos) > 25:
        texte_liste += (
            f"\n\n⚠️ Seules les 25 premières promos (sur {len(promos)} au total) sont affichées, "
            f"à cause de la limite de Discord sur les menus de sélection."
        )

    embed = discord.Embed(
        title="📢 Promotions du jour — Sélectionne celles à publier",
        description=texte_liste,
        color=discord.Color.blurple()
    )

    vue = VueChoixPromo(promos, salon_destination_id)
    try:
        await salon_liste.send(content=f"<@&{role_id}>", embed=embed, view=vue)
    except discord.Forbidden:
        return False, (
            f"Permissions manquantes dans <#{salon_liste_id}> : vérifie que le rôle du bot a bien "
            f"« Voir le salon », « Envoyer des messages » et « Intégrer des liens » sur ce salon, "
            f"et que le rôle <@&{role_id}> peut être mentionné par le bot."
        )
    except discord.HTTPException as e:
        return False, f"Erreur Discord lors de l'envoi dans <#{salon_liste_id}> : {e}"

    return True, f"Demande envoyée avec succès dans <#{salon_liste_id}> ({len(promos)} promo(s) trouvée(s))."


# ==========================================
# SYSTÈME /filiale : SUIVI QUOTIDIEN DES FILIALES
# ==========================================
class ModalNoteFiliale(discord.ui.Modal, title="Ajouter une note à une filiale"):
    """Modal permettant au gestionnaire d'écrire une remarque/note pour une filiale précise."""

    def __init__(self, vue_parent: "VueFormulaireFiliales", salon_id: str, nom_salon: str):
        super().__init__()
        self.vue_parent = vue_parent
        self.salon_id = salon_id

        self.note_input = discord.ui.TextInput(
            label=f"Note pour #{nom_salon}"[:45],
            placeholder="Ex: erreur sur le loyer, bien joué, à corriger...",
            default=vue_parent.notes.get(salon_id, ""),
            required=True,
            style=discord.TextStyle.paragraph,
            max_length=500
        )
        self.add_item(self.note_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.vue_parent.notes[self.salon_id] = self.note_input.value
        nom_salon = self.vue_parent.filiales.get(self.salon_id, {}).get("nom_salon", self.salon_id)
        await interaction.response.send_message(
            f"📝 Note enregistrée pour **#{nom_salon}**. Tu peux en ajouter une autre ou cliquer sur **Valider**.",
            ephemeral=True
        )


TAILLE_PAGE_FILIALES = 25  # limite Discord : 25 options max par menu déroulant


class VueFormulaireFiliales(discord.ui.View):
    """
    Formulaire interactif quotidien envoyé au gestionnaire (référent) :
    - un menu déroulant pour cocher les filiales NON faites,
    - un menu déroulant pour cocher les filiales MAL gérées,
    - un menu déroulant pour ajouter une note à une filiale précise,
    - des boutons ◀ Précédent / Suivant ▶ pour parcourir les filiales par pages de 25
      (la limite de Discord sur les menus déroulants) quand il y en a plus de 25,
    - un bouton pour valider et déclencher l'envoi du rapport + des notifications,
      qui prend en compte TOUTES les filiales, même celles des autres pages.

    Les 2 premiers menus sont pré-cochés automatiquement d'après ce qui est déjà connu via
    le système de bouton (`/param bouton`) au moment de la génération du formulaire : le
    gestionnaire n'a plus qu'à ajuster/compléter avant de valider.
    """

    def __init__(self, filiales: dict, guild_id_str: str, salon_referent_id: str):
        super().__init__(timeout=None)
        self.filiales = filiales  # {salon_id: {"joueur_id": ..., "nom_salon": ...}}
        self.guild_id_str = guild_id_str
        self.salon_referent_id = salon_referent_id
        self.notes: dict[str, str] = {}
        self.valide = False

        self.items_tries = list(filiales.items())
        self.nb_pages = max(1, math.ceil(len(self.items_tries) / TAILLE_PAGE_FILIALES))
        self.page = 0

        # Pré-cochage automatique d'après l'état déjà connu (clics sur le bouton du jour).
        self.filiales_non_faites: set[str] = set()
        self.filiales_mal_gerees: set[str] = set()
        aujourdhui = _date_paris_aujourdhui()
        for sid, info in self.items_tries:
            if info.get("derniere_validation") != aujourdhui:
                self.filiales_non_faites.add(sid)
            elif info.get("dernier_statut") == "mal_geree":
                self.filiales_mal_gerees.add(sid)

        self.select_realisation = discord.ui.Select(
            placeholder="❌ Coche les filiales NON faites aujourd'hui...",
            min_values=0,
            max_values=1,
            options=[discord.SelectOption(label="Chargement...", value="_placeholder")],
            row=0
        )
        self.select_realisation.callback = self.on_select_realisation
        self.add_item(self.select_realisation)

        self.select_mal_geree = discord.ui.Select(
            placeholder="⚠️ Coche les filiales MAL gérées...",
            min_values=0,
            max_values=1,
            options=[discord.SelectOption(label="Chargement...", value="_placeholder")],
            row=1
        )
        self.select_mal_geree.callback = self.on_select_mal_geree
        self.add_item(self.select_mal_geree)

        self.select_note = discord.ui.Select(
            placeholder="📝 Ajouter une note à une filiale...",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label="Chargement...", value="_placeholder")],
            row=2
        )
        self.select_note.callback = self.on_select_note
        self.add_item(self.select_note)

        self._rafraichir_page()

    def _items_page(self) -> list:
        debut = self.page * TAILLE_PAGE_FILIALES
        return self.items_tries[debut:debut + TAILLE_PAGE_FILIALES]

    def _rafraichir_page(self) -> None:
        """Reconstruit les menus déroulants et l'état des boutons pour la page courante."""
        items_page = self._items_page()

        self.select_realisation.options = [
            discord.SelectOption(
                label=f"#{info.get('nom_salon', sid)}"[:100],
                value=sid,
                default=(sid in self.filiales_non_faites)
            )
            for sid, info in items_page
        ]
        self.select_realisation.max_values = len(self.select_realisation.options)

        self.select_mal_geree.options = [
            discord.SelectOption(
                label=f"#{info.get('nom_salon', sid)}"[:100],
                value=sid,
                default=(sid in self.filiales_mal_gerees)
            )
            for sid, info in items_page
        ]
        self.select_mal_geree.max_values = len(self.select_mal_geree.options)

        self.select_note.options = [
            discord.SelectOption(label=f"#{info.get('nom_salon', sid)}"[:100], value=sid)
            for sid, info in items_page
        ]

        self.page_precedente.disabled = (self.page <= 0)
        self.page_suivante.disabled = (self.page >= self.nb_pages - 1)

    def construire_embed(self) -> discord.Embed:
        items_page = self._items_page()
        lignes = "\n".join(f"• <#{sid}> (#{info.get('nom_salon', sid)})" for sid, info in items_page)
        embed = discord.Embed(
            title="📋 Formulaire quotidien — Suivi des filiales",
            description=(
                f"Coche les filiales **NON faites** et/ou **MAL gérées** aujourd'hui (les autres seront "
                f"considérées comme bien faites), ajoute des notes si besoin, puis clique sur "
                f"**Valider le rapport**.\n"
                f"↩️ Pré-coché automatiquement d'après les clics déjà reçus aujourd'hui — ajuste si besoin.\n"
                f"⚠️ La validation prend en compte **toutes** les filiales, même celles des autres pages.\n\n"
                f"{lignes}"
            ),
            color=discord.Color.blurple()
        )
        nb_non_faites = len(self.filiales_non_faites)
        nb_mal_gerees = len(self.filiales_mal_gerees - self.filiales_non_faites)
        nb_faites = len(self.filiales) - nb_non_faites - nb_mal_gerees
        pied = (
            f"{len(self.filiales)} filiale(s) au total • ✅ {nb_faites} • ⚠️ {nb_mal_gerees} • "
            f"❌ {nb_non_faites} • {len(self.notes)} note(s)"
        )
        if self.nb_pages > 1:
            pied = f"Page {self.page + 1}/{self.nb_pages} • " + pied
        embed.set_footer(text=pied)
        return embed

    async def on_select_realisation(self, interaction: discord.Interaction):
        salon_ids_page = {sid for sid, _ in self._items_page()}
        selection = set(self.select_realisation.values)
        # On ne met à jour que les filiales de la page actuelle, pour ne pas
        # écraser l'état des filiales cochées sur les autres pages.
        self.filiales_non_faites -= salon_ids_page
        self.filiales_non_faites |= selection
        self._rafraichir_page()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def on_select_mal_geree(self, interaction: discord.Interaction):
        salon_ids_page = {sid for sid, _ in self._items_page()}
        selection = set(self.select_mal_geree.values)
        self.filiales_mal_gerees -= salon_ids_page
        self.filiales_mal_gerees |= selection
        self._rafraichir_page()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    async def on_select_note(self, interaction: discord.Interaction):
        salon_id = self.select_note.values[0]
        nom_salon = self.filiales.get(salon_id, {}).get("nom_salon", salon_id)
        await interaction.response.send_modal(ModalNoteFiliale(self, salon_id, nom_salon))

    @discord.ui.button(label="◀ Précédent", style=discord.ButtonStyle.secondary, row=3)
    async def page_precedente(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self._rafraichir_page()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    @discord.ui.button(label="Suivant ▶", style=discord.ButtonStyle.secondary, row=3)
    async def page_suivante(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.nb_pages - 1:
            self.page += 1
        self._rafraichir_page()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    @discord.ui.button(label="✅ Valider le rapport", style=discord.ButtonStyle.success, row=4)
    async def valider(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.valide:
            await interaction.response.send_message("⚠️ Ce rapport a déjà été validé.", ephemeral=True)
            return

        self.valide = True
        await interaction.response.defer(ephemeral=True)

        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self)
        except (discord.HTTPException, AttributeError):
            pass

        resultat = await traiter_validation_filiales(interaction.client, self)
        await interaction.followup.send(resultat, ephemeral=True)


async def traiter_validation_filiales(bot_client, vue: "VueFormulaireFiliales") -> str:
    """
    Traite la validation du formulaire quotidien :
    - détermine le statut final de chaque filiale (faite / mal gérée / non faite) et l'enregistre
      dans filiale.json comme source de vérité du jour (utilisé aussi par le tableau et le bouton),
    - envoie le récapitulatif (3 catégories) dans le salon référent,
    - notifie individuellement (dans leur propre salon, sous forme d'embed avec une barre latérale
      JAUNE) les filiales non faites ou mal gérées, et transmet les notes du gestionnaire,
    - met à jour le tableau de suivi en direct (`/param tableau`) s'il est actif.
    """
    aujourdhui = _date_paris_aujourdhui()

    # Détermine le statut final de chaque filiale (priorité : non faite > mal gérée > faite)
    statuts: dict[str, str] = {}
    for salon_id in vue.filiales:
        if salon_id in vue.filiales_non_faites:
            statuts[salon_id] = "non_faite"
        elif salon_id in vue.filiales_mal_gerees:
            statuts[salon_id] = "mal_geree"
        else:
            statuts[salon_id] = "faite"

    # Enregistre ce statut comme source de vérité du jour (repris par le tableau et le bouton).
    donnees = charger_filiales()
    serveur = donnees.get(vue.guild_id_str)
    if serveur:
        for salon_id, statut in statuts.items():
            info = serveur.get("filiales", {}).get(salon_id)
            if info is None:
                continue
            if statut == "non_faite":
                # Non faite : on efface toute validation du jour pour que le tableau/bouton
                # la considère bien comme non faite (et non comme "faite" par erreur).
                info["derniere_validation"] = None
                info["dernier_statut"] = None
            else:
                info["derniere_validation"] = aujourdhui
                info["dernier_statut"] = statut  # "faite" ou "mal_geree"
        sauvegarder_filiales(donnees)

    filiales_non_faites = {sid: info for sid, info in vue.filiales.items() if statuts[sid] == "non_faite"}
    filiales_mal_gerees = {sid: info for sid, info in vue.filiales.items() if statuts[sid] == "mal_geree"}

    # 1) Récapitulatif dans le salon référent
    salon_referent = bot_client.get_channel(int(vue.salon_referent_id)) if vue.salon_referent_id else None
    if salon_referent:
        def construire_ligne(salon_id, info, emoji):
            mention_joueur = obtenir_texte_affichage_responsable(info)
            nom_salon = info.get("nom_salon", salon_id)
            ligne = f"{emoji} <#{salon_id}> (#{nom_salon}) — {mention_joueur}"
            note = vue.notes.get(salon_id)
            if note:
                ligne += f"\n　└ 📝 *{note}*"
            return ligne

        lignes_non_faites = [construire_ligne(sid, info, "❌") for sid, info in filiales_non_faites.items()]
        lignes_mal_gerees = [construire_ligne(sid, info, "⚠️") for sid, info in filiales_mal_gerees.items()]

        if lignes_non_faites or lignes_mal_gerees:
            morceaux = []
            if lignes_non_faites:
                morceaux.append("**❌ Non faites**\n" + "\n".join(lignes_non_faites))
            if lignes_mal_gerees:
                morceaux.append("**⚠️ Mal gérées**\n" + "\n".join(lignes_mal_gerees))
            description = "\n\n".join(morceaux)
        else:
            description = "🎉 Toutes les filiales ont été bien gérées aujourd'hui !"

        couleur = discord.Color.green() if not filiales_non_faites and not filiales_mal_gerees else (
            discord.Color.red() if filiales_non_faites else discord.Color.gold()
        )

        embed = discord.Embed(
            title="📋 Récapitulatif quotidien des filiales",
            description=description[:4000],
            color=couleur
        )
        nb_faites = len(vue.filiales) - len(filiales_non_faites) - len(filiales_mal_gerees)
        embed.set_footer(
            text=f"{len(vue.filiales)} filiale(s) au total • ✅ {nb_faites} • ⚠️ {len(filiales_mal_gerees)} • ❌ {len(filiales_non_faites)}"
        )
        try:
            await salon_referent.send(embed=embed)
        except Exception as e:
            print(f"❌ [filiale] Impossible d'envoyer le récapitulatif dans le salon référent : {e}")
    else:
        print("❌ [filiale] Salon référent introuvable ou non configuré : récapitulatif non envoyé.")

    # 2) Notifications individuelles + notes, envoyées en embed (barre jaune) dans le salon de chaque filiale
    nb_relances = 0
    nb_mal_gerees_notif = 0
    nb_notes = 0
    for salon_id, info in vue.filiales.items():
        salon = bot_client.get_channel(int(salon_id))
        if not salon:
            continue

        mention_joueur = obtenir_mention_ping_filiale(info)
        note = vue.notes.get(salon_id)
        statut = statuts[salon_id]

        if statut == "faite" and not note:
            continue  # Rien à signaler pour cette filiale

        embed_notif = discord.Embed(
            title="📋 Suivi quotidien de la filiale",
            color=discord.Color.yellow()
        )
        if statut == "non_faite":
            embed_notif.add_field(
                name="❌ Filiale non réalisée",
                value="Cette filiale n'a pas été marquée comme réalisée aujourd'hui. Pense à t'en occuper dès que possible !",
                inline=False
            )
        elif statut == "mal_geree":
            embed_notif.add_field(
                name="⚠️ Filiale mal gérée",
                value="Cette filiale a été signalée comme **mal gérée** aujourd'hui par le référent. "
                      "Fais bien attention à correctement la gérer demain !",
                inline=False
            )
        else:  # statut == "faite" (avec une note) : message positif, sans ping
            embed_notif.add_field(
                name="✅ Filiale bien gérée",
                value="Cette filiale a été validée comme bien gérée aujourd'hui par le référent. Continue comme ça !",
                inline=False
            )
        if note:
            embed_notif.add_field(name="📝 Remarque du gestionnaire", value=note[:1024], inline=False)

        try:
            # Pas de ping quand la filiale a été validée comme bien gérée : on ne mentionne
            # le joueur que s'il y a réellement quelque chose à corriger (non faite / mal gérée).
            contenu_notif = mention_joueur if statut in ("non_faite", "mal_geree") else None
            await salon.send(content=contenu_notif, embed=embed_notif)
            if statut == "non_faite":
                nb_relances += 1
            elif statut == "mal_geree":
                nb_mal_gerees_notif += 1
            if note:
                nb_notes += 1
        except Exception as e:
            print(f"❌ [filiale] Impossible d'envoyer la notification dans <#{salon_id}> : {e}")

    # 3) Synchronise le tableau de suivi en direct, s'il est actif
    try:
        await actualiser_tableau_filiales(bot_client, vue.guild_id_str, forcer_nouveau=False)
    except Exception as e:
        print(f"❌ [filiale] Impossible de mettre à jour le tableau après validation du formulaire : {e}")

    return (
        f"✅ Rapport validé et envoyé !\n"
        f"📌 {len(filiales_non_faites)} non faite(s), {len(filiales_mal_gerees)} mal gérée(s) sur {len(vue.filiales)}.\n"
        f"📤 {nb_relances} relance(s), {nb_mal_gerees_notif} signalement(s) et {nb_notes} note(s) envoyé(s) dans les salons concernés."
    )


async def envoyer_formulaire_filiales(bot_client, guild_id_str: str, server_data: dict) -> tuple[bool, str]:
    """
    Envoie le formulaire quotidien interactif de suivi des filiales au gestionnaire :
    en message privé s'il est défini via /referant, sinon directement dans le salon référent.
    Gère nativement plus de 25 filiales grâce à la pagination intégrée à VueFormulaireFiliales.
    """
    filiales = server_data.get("filiales", {})
    if not filiales:
        return False, "Aucune filiale enregistrée (utilise `/filiale ajouter` dans les salons concernés)."

    referent = server_data.get("referent", {})
    salon_referent_id = referent.get("salon_id")
    joueur_referent_id = referent.get("joueur_id")

    if not salon_referent_id:
        return False, "Aucun salon référent configuré (utilise `/referant definir`)."

    vue = VueFormulaireFiliales(filiales, guild_id_str, salon_referent_id)
    embed = vue.construire_embed()

    if joueur_referent_id:
        guild_obj = bot_client.get_guild(int(guild_id_str))
        membre = guild_obj.get_member(int(joueur_referent_id)) if guild_obj else None
        if membre:
            try:
                await membre.send(embed=embed, view=vue)
                return True, f"Formulaire envoyé en message privé à {membre.display_name}."
            except discord.Forbidden:
                pass  # DM fermés : on retombe sur le salon référent ci-dessous
            except Exception as e:
                print(f"❌ [filiale] Erreur DM au référent : {e}")

    salon_referent = bot_client.get_channel(int(salon_referent_id))
    if not salon_referent:
        return False, f"Le salon référent (ID {salon_referent_id}) est introuvable."

    try:
        role_referent_id = referent.get("role_id")
        mentions = []
        if joueur_referent_id:
            mentions.append(f"<@{joueur_referent_id}>")
        if role_referent_id:
            mentions.append(f"<@&{role_referent_id}>")
        mention = (" ".join(mentions) + "\n") if mentions else ""
        await salon_referent.send(content=mention, embed=embed, view=vue)
        return True, f"Formulaire envoyé dans <#{salon_referent_id}>."
    except discord.Forbidden:
        return False, f"Permissions manquantes dans <#{salon_referent_id}>."
    except discord.HTTPException as e:
        return False, f"Erreur Discord lors de l'envoi dans <#{salon_referent_id}> : {e}"


# ==========================================
# SYSTÈME « BOUTON » : RAPPEL QUOTIDIEN + RÉCAP (extension du suivi des filiales)
# ==========================================
class VueBoutonFilialeGeree(discord.ui.View):
    """
    Vue PERSISTANTE (custom_id fixe, timeout=None) attachée au message de rappel quotidien
    envoyé dans chaque salon de filiale. Un seul bouton : la personne en charge clique dessus
    pour dire qu'elle a géré sa filiale aujourd'hui — elle ne juge PAS elle-même de la qualité
    du travail, c'est le rôle du référent (via le formulaire quotidien) de vérifier ensuite si
    c'était bien fait ou non. Le salon dans lequel on clique EST la filiale concernée, donc
    aucune donnée supplémentaire n'a besoin d'être stockée dans la vue elle-même -> le bouton
    reste fonctionnel même après un redémarrage du bot. Une fois cliqué, le bouton se désactive
    sur CE message (un nouveau rappel/relance renverra un bouton frais si besoin), et un message
    PUBLIC confirme que la filiale a été gérée.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Filiale gérée ✅",
        style=discord.ButtonStyle.success,
        custom_id="filiale:bouton_gere_v1",
        emoji="🗂️"
    )
    async def bouton_gere(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Ce bouton doit être utilisé dans un serveur.", ephemeral=True
            )
            return

        guild_id_str = str(interaction.guild.id)
        salon_id_str = str(interaction.channel.id)

        donnees = charger_filiales()
        serveur = donnees.get(guild_id_str)
        if not serveur or salon_id_str not in serveur.get("filiales", {}):
            await interaction.response.send_message(
                "⚠️ Ce salon n'est plus enregistré comme filiale (il a peut-être été retiré). "
                "Un responsable peut vérifier via `/filiale panneau`.",
                ephemeral=True
            )
            return

        aujourdhui = _date_paris_aujourdhui()
        info = serveur["filiales"][salon_id_str]
        info["derniere_validation"] = aujourdhui
        info["dernier_statut"] = "faite"
        info["valide_par"] = str(interaction.user.id)
        sauvegarder_filiales(donnees)

        # On désactive le bouton sur CE message précis (un nouveau rappel/relance en enverra un frais).
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            pass

        try:
            await actualiser_tableau_filiales(interaction.client, guild_id_str, forcer_nouveau=False)
        except Exception as e:
            print(f"❌ [filiale] Impossible de mettre à jour le tableau pour le serveur {guild_id_str} : {e}")

        embed = discord.Embed(
            description=f"✅ {interaction.user.mention} a géré sa filiale aujourd'hui !",
            color=discord.Color.green()
        )
        try:
            # Message PUBLIC (visible par tout le monde dans le salon), envoyé en followup
            # puisque l'interaction a déjà été utilisée pour désactiver le bouton ci-dessus.
            await interaction.followup.send(embed=embed)
        except discord.HTTPException as e:
            print(f"❌ [filiale] Impossible d'envoyer la confirmation publique dans <#{salon_id_str}> : {e}")


async def envoyer_rappels_bouton_filiales(bot_client, server_data: dict) -> tuple[int, int]:
    """
    Envoie, dans chaque salon de filiale enregistré, un message de rappel esthétique
    avec le bouton « Filiale gérée ✅ ». Ignore silencieusement (sans planter) les salons
    qui ont été supprimés sans être retirés du suivi — ils resteront visibles et gérables
    via `/filiale panneau`. Renvoie (nb_envoyés, nb_erreurs).
    """
    filiales = server_data.get("filiales", {})
    nb_envoyes = 0
    nb_erreurs = 0

    message_personnalise = server_data.get("parametres", {}).get("bouton_message")

    for salon_id, info in filiales.items():
        salon = bot_client.get_channel(int(salon_id))
        if not salon:
            nb_erreurs += 1
            continue

        joueur_id = info.get("joueur_id")
        mention = obtenir_mention_ping_filiale(info)
        nom_salon = info.get("nom_salon", salon_id)

        if message_personnalise:
            # Le placeholder {filiale} est remplacé par le nom du salon si présent dans le texte.
            corps = message_personnalise.replace("{filiale}", f"#{nom_salon}")
            description = f"### #{nom_salon}\n{corps}"
        else:
            description = (
                f"### #{nom_salon}\n"
                f"N'oublie pas de t'occuper de cette filiale aujourd'hui.\n"
                f"Une fois que c'est fait, clique sur le bouton ci-dessous 👇"
            )

        if info.get("absent"):
            description += (
                f"\n\n🌴 *<@{joueur_id}> est en vacances — merci de gérer cette filiale à sa place.*"
                if joueur_id else "\n\n🌴 *Le responsable habituel est en vacances.*"
            )

        embed = discord.Embed(
            title="🗂️ Filiale à gérer aujourd'hui",
            description=description,
            color=discord.Color.orange()
        )
        embed.set_footer(text="Suivi quotidien des filiales")

        try:
            await salon.send(content=mention, embed=embed, view=VueBoutonFilialeGeree())
            nb_envoyes += 1
        except Exception as e:
            nb_erreurs += 1
            print(f"❌ [filiale] Impossible d'envoyer le rappel bouton dans <#{salon_id}> : {e}")

    return nb_envoyes, nb_erreurs


async def envoyer_recap_bouton_filiales(bot_client, server_data: dict) -> tuple[bool, str]:
    """
    Envoie dans le salon référent un récapitulatif esthétique des filiales gérées / non gérées
    aujourd'hui, d'après les clics sur le bouton « Filiale gérée ✅ ». Signale distinctement les
    filiales dont le salon a été supprimé (sans avoir été retiré du suivi), pour repérage facile
    depuis `/filiale panneau`.
    """
    referent = server_data.get("referent", {})
    salon_referent_id = referent.get("salon_id")
    if not salon_referent_id:
        return False, "Aucun salon référent configuré (utilise `/referant definir`)."

    salon_referent = bot_client.get_channel(int(salon_referent_id))
    if not salon_referent:
        return False, f"Le salon référent (ID {salon_referent_id}) est introuvable."

    filiales = server_data.get("filiales", {})
    if not filiales:
        return False, "Aucune filiale enregistrée."

    aujourdhui = _date_paris_aujourdhui()

    lignes_faites = []
    lignes_mal_gerees = []
    lignes_non_faites = []

    for salon_id, info in filiales.items():
        mention_joueur = obtenir_texte_affichage_responsable(info)
        nom_salon = info.get("nom_salon", salon_id)
        existe = bot_client.get_channel(int(salon_id)) is not None
        salon_texte = f"<#{salon_id}>" if existe else f"⚠️ #{nom_salon} *(salon supprimé)*"

        fait_aujourdhui = info.get("derniere_validation") == aujourdhui
        statut = info.get("dernier_statut") if fait_aujourdhui else None

        if statut == "faite":
            lignes_faites.append(f"✅ {salon_texte} — {mention_joueur}")
        elif statut == "mal_geree":
            lignes_mal_gerees.append(f"⚠️ {salon_texte} — {mention_joueur}")
        else:
            lignes_non_faites.append(f"❌ {salon_texte} — {mention_joueur}")

    total = len(filiales)
    nb_faites = len(lignes_faites)
    pourcentage = round((nb_faites / total) * 100) if total else 0

    couleur = discord.Color.green() if nb_faites == total and total else (
        discord.Color.red() if (nb_faites == 0 and not lignes_mal_gerees) else discord.Color.gold()
    )

    embed = discord.Embed(
        title="📊 Récapitulatif quotidien des filiales",
        description=f"**{nb_faites}/{total}** filiale(s) gérée(s) aujourd'hui ({pourcentage}%)",
        color=couleur
    )
    embed.add_field(
        name=f"✅ Gérées ({len(lignes_faites)})",
        value="\n".join(lignes_faites)[:1024] if lignes_faites else "*Aucune*",
        inline=False
    )
    embed.add_field(
        name=f"⚠️ Mal gérées ({len(lignes_mal_gerees)})",
        value="\n".join(lignes_mal_gerees)[:1024] if lignes_mal_gerees else "*Aucune*",
        inline=False
    )
    embed.add_field(
        name=f"❌ Non gérées ({len(lignes_non_faites)})",
        value="\n".join(lignes_non_faites)[:1024] if lignes_non_faites else "*Aucune*",
        inline=False
    )

    guild_obj = getattr(salon_referent, "guild", None)
    if guild_obj is not None and guild_obj.icon is not None:
        embed.set_thumbnail(url=guild_obj.icon.url)
    embed.set_footer(text="Suivi quotidien des filiales")

    try:
        await salon_referent.send(embed=embed)
        return True, "Récapitulatif envoyé."
    except discord.Forbidden:
        return False, f"Permissions manquantes dans <#{salon_referent_id}>."
    except discord.HTTPException as e:
        return False, f"Erreur Discord lors de l'envoi dans <#{salon_referent_id}> : {e}"


# ==========================================
# TABLEAU DE SUIVI QUOTIDIEN (un message par jour, mis à jour en direct)
# ==========================================
def construire_embed_tableau_filiales(bot_client, server_data: dict) -> discord.Embed:
    """Construit l'embed du tableau listant l'état (faite / mal gérée / non faite) de chaque filiale aujourd'hui."""
    filiales = server_data.get("filiales", {})
    aujourdhui = _date_paris_aujourdhui()

    lignes = []
    nb_faites = 0
    nb_mal_gerees = 0
    for salon_id, info in filiales.items():
        mention_joueur = obtenir_texte_affichage_responsable(info)
        nom_salon = info.get("nom_salon", salon_id)
        existe = bot_client.get_channel(int(salon_id)) is not None
        salon_texte = f"<#{salon_id}>" if existe else f"⚠️ #{nom_salon} *(salon supprimé)*"

        fait_aujourdhui = info.get("derniere_validation") == aujourdhui
        statut = info.get("dernier_statut") if fait_aujourdhui else None

        if statut == "faite":
            emoji = "✅"
            nb_faites += 1
        elif statut == "mal_geree":
            emoji = "⚠️"
            nb_mal_gerees += 1
        else:
            emoji = "❌"

        lignes.append(f"{emoji} {salon_texte} — {mention_joueur}")

    total = len(filiales)
    pourcentage = round((nb_faites / total) * 100) if total else 0
    couleur = discord.Color.green() if total and nb_faites == total else (
        discord.Color.red() if nb_faites == 0 and nb_mal_gerees == 0 else discord.Color.gold()
    )

    now = datetime.now(ZoneInfo("Europe/Paris"))
    embed = discord.Embed(
        title="📅 Tableau de Suivi — Filiales du Jour",
        description=(
            f"**{nb_faites}/{total}** filiale(s) gérée(s) ({pourcentage}%)"
            + (f" • ⚠️ {nb_mal_gerees} mal gérée(s)" if nb_mal_gerees else "")
            + "\n\n"
            + ("\n".join(lignes) if lignes else "*Aucune filiale enregistrée.*")
        ),
        color=couleur
    )
    embed.set_footer(text=f"Mis à jour automatiquement • {now.strftime('%d/%m/%Y à %H:%M')}")
    return embed


async def actualiser_tableau_filiales(bot_client, guild_id_str: str, forcer_nouveau: bool = False) -> tuple[bool, str]:
    """
    Crée (si besoin) ou met à jour EN PLACE le message "tableau" quotidien listant l'état
    de chaque filiale, dans le salon configuré via `/param tableau`. Un seul message est
    utilisé par jour : il est édité en direct à chaque clic sur « Filiale gérée ✅ ».
    """
    donnees = charger_filiales()
    serveur = donnees.get(guild_id_str)
    if not serveur:
        return False, "Aucune configuration trouvée pour ce serveur."

    parametres = serveur["parametres"]
    salon_tableau_id = parametres.get("salon_tableau_id")
    if not salon_tableau_id:
        return False, "Aucun salon configuré pour le tableau (utilise `/param tableau`)."

    salon = bot_client.get_channel(int(salon_tableau_id))
    if not salon:
        return False, f"Le salon configuré pour le tableau (ID {salon_tableau_id}) est introuvable."

    aujourdhui = _date_paris_aujourdhui()
    embed = construire_embed_tableau_filiales(bot_client, serveur)

    message_existant_id = parametres.get("tableau_message_id")
    date_message = parametres.get("tableau_derniere_date")

    if not forcer_nouveau and message_existant_id and date_message == aujourdhui:
        try:
            message = await salon.fetch_message(int(message_existant_id))
            await message.edit(embed=embed)
            return True, "Tableau mis à jour."
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass  # message supprimé/inaccessible : on en renvoie un nouveau ci-dessous

    try:
        nouveau_message = await salon.send(embed=embed)
    except discord.Forbidden:
        return False, f"Permissions manquantes dans <#{salon_tableau_id}>."
    except discord.HTTPException as e:
        return False, f"Erreur Discord lors de l'envoi dans <#{salon_tableau_id}> : {e}"

    parametres["tableau_message_id"] = str(nouveau_message.id)
    parametres["tableau_derniere_date"] = aujourdhui
    sauvegarder_filiales(donnees)
    return True, f"Nouveau tableau envoyé dans <#{salon_tableau_id}>."


async def envoyer_relances_filiales_non_faites(bot_client, server_data: dict) -> tuple[int, int]:
    """
    Envoie une relance (embed rouge + bouton « Filiale gérée ✅ ») UNIQUEMENT dans les salons
    des filiales qui n'ont pas encore été marquées comme gérées aujourd'hui. Renvoie
    (nb_envoyées, nb_erreurs).
    """
    filiales = server_data.get("filiales", {})
    aujourdhui = _date_paris_aujourdhui()
    nb_envoyes = 0
    nb_erreurs = 0

    for salon_id, info in filiales.items():
        if info.get("derniere_validation") == aujourdhui:
            continue  # déjà gérée aujourd'hui : pas besoin de relance

        salon = bot_client.get_channel(int(salon_id))
        if not salon:
            nb_erreurs += 1
            continue

        joueur_id = info.get("joueur_id")
        mention = obtenir_mention_ping_filiale(info)
        nom_salon = info.get("nom_salon", salon_id)

        description_relance = (
            f"### #{nom_salon}\n"
            f"Cette filiale n'a toujours pas été marquée comme gérée aujourd'hui.\n"
            f"Clique sur le bouton ci-dessous une fois que c'est fait 👇"
        )
        if info.get("absent"):
            description_relance += (
                f"\n\n🌴 *<@{joueur_id}> est en vacances — merci de gérer cette filiale à sa place.*"
                if joueur_id else "\n\n🌴 *Le responsable habituel est en vacances.*"
            )

        embed = discord.Embed(
            title="⏰ Relance — Filiale toujours pas gérée",
            description=description_relance,
            color=discord.Color.red()
        )
        embed.set_footer(text="Relance automatique — Suivi quotidien des filiales")

        try:
            await salon.send(content=mention, embed=embed, view=VueBoutonFilialeGeree())
            nb_envoyes += 1
        except Exception as e:
            nb_erreurs += 1
            print(f"❌ [filiale] Impossible d'envoyer la relance dans <#{salon_id}> : {e}")

    return nb_envoyes, nb_erreurs


# ==========================================
# PANNEAU DE GESTION CENTRALISÉ DES FILIALES (utilisable depuis N'IMPORTE QUEL salon)
# ==========================================
class VuePanneauFiliales(discord.ui.View):
    """
    Tableau de bord centralisé pour gérer TOUTES les filiales d'un serveur depuis un seul
    et même salon (pas besoin d'être dans le salon de chaque filiale). Permet notamment de
    repérer et nettoyer les filiales dont le salon Discord a été supprimé sans passer par
    `/filiale supprimer` (ce qui laisse une entrée fantôme dans filiale.json), et d'ajouter
    ou réassigner une filiale à un nouveau salon en un clic.
    """

    def __init__(self, guild_id_str: str):
        super().__init__(timeout=600)
        self.guild_id_str = guild_id_str
        self.salon_cible: str | None = None
        self.page = 0
        self.nb_pages = 1

        self.select_existantes = discord.ui.Select(
            placeholder="🗂️ Choisir une filiale existante (voir / supprimer)...",
            min_values=1, max_values=1,
            options=[discord.SelectOption(label="Chargement...", value="_placeholder")],
            row=0
        )
        self.select_existantes.callback = self.on_select_existante
        self.add_item(self.select_existantes)

        self.select_joueur = discord.ui.UserSelect(
            placeholder="👤 Choisir un joueur (pour ajouter/modifier une filiale)...",
            min_values=1, max_values=1, row=1
        )
        self.add_item(self.select_joueur)

        self.select_salon = discord.ui.ChannelSelect(
            placeholder="📺 Choisir un salon (pour ajouter/modifier une filiale)...",
            channel_types=[discord.ChannelType.text],
            min_values=1, max_values=1, row=2
        )
        self.add_item(self.select_salon)

        self._rafraichir()

    def _rafraichir(self) -> None:
        """Reconstruit le menu des filiales existantes et l'état des boutons."""
        donnees = charger_filiales()
        serveur = donnees.get(self.guild_id_str, {})
        filiales = serveur.get("filiales", {})
        items = list(filiales.items())

        self.nb_pages = max(1, math.ceil(len(items) / TAILLE_PAGE_FILIALES))
        self.page = min(self.page, self.nb_pages - 1)
        debut = self.page * TAILLE_PAGE_FILIALES
        items_page = items[debut:debut + TAILLE_PAGE_FILIALES]

        if not items_page:
            self.select_existantes.options = [discord.SelectOption(label="Aucune filiale enregistrée", value="_aucune")]
            self.select_existantes.disabled = True
        else:
            self.select_existantes.disabled = False
            options = []
            for sid, info in items_page:
                existe = bot.get_channel(int(sid)) is not None
                joueur_id = info.get("joueur_id")
                nom_joueur = "Aucun joueur"
                if joueur_id:
                    guild_obj = bot.get_guild(int(self.guild_id_str))
                    membre = guild_obj.get_member(int(joueur_id)) if guild_obj else None
                    nom_joueur = membre.display_name if membre else f"ID {joueur_id}"
                if info.get("absent"):
                    nom_joueur += " 🌴 (vacances)"
                statut = "⚠️ Salon supprimé" if not existe else "Salon actif"
                options.append(discord.SelectOption(
                    label=f"#{info.get('nom_salon', sid)}"[:100],
                    value=sid,
                    description=f"{statut} • {nom_joueur}"[:100],
                    emoji="⚠️" if not existe else "🗂️",
                    default=(sid == self.salon_cible)
                ))
            self.select_existantes.options = options

        self.bouton_precedent.disabled = (self.page <= 0)
        self.bouton_suivant.disabled = (self.page >= self.nb_pages - 1)
        self.bouton_supprimer.disabled = (self.salon_cible is None)

    def construire_embed(self) -> discord.Embed:
        donnees = charger_filiales()
        serveur = donnees.get(self.guild_id_str, {})
        filiales = serveur.get("filiales", {})
        referent = serveur.get("referent", {})
        parametres = serveur.get("parametres", {})

        nb_total = len(filiales)
        nb_orphelines = sum(1 for sid in filiales if bot.get_channel(int(sid)) is None)

        salon_referent_id = referent.get("salon_id")
        joueur_referent_id = referent.get("joueur_id")
        texte_salon_referent = f"<#{salon_referent_id}>" if salon_referent_id else "❌ Non défini"
        texte_joueur_referent = f"<@{joueur_referent_id}>" if joueur_referent_id else "*Aucun*"

        embed = discord.Embed(
            title="🛠️ Panneau de Gestion des Filiales",
            description="Gère toutes les filiales de ce serveur depuis ce salon, même celles dont le salon a été supprimé.",
            color=discord.Color.blurple()
        )
        embed.add_field(
            name="📊 Filiales",
            value=f"{nb_total} enregistrée(s) • ⚠️ {nb_orphelines} orpheline(s) (salon supprimé)",
            inline=False
        )
        embed.add_field(name="📤 Référent", value=f"Salon : {texte_salon_referent}\nJoueur : {texte_joueur_referent}", inline=True)
        embed.add_field(
            name="⚙️ Automatisation",
            value=(
                f"Formulaire : {'🟢' if parametres.get('actif') else '🔴'} ({parametres.get('heure') or '—'})\n"
                f"Bouton : {'🟢' if parametres.get('bouton_actif') else '🔴'} "
                f"(rappel {parametres.get('heure_rappel') or '—'}, récap {parametres.get('heure_recap') or '—'})"
            ),
            inline=True
        )

        if self.salon_cible:
            info = filiales.get(self.salon_cible)
            if info:
                existe = bot.get_channel(int(self.salon_cible)) is not None
                nom_salon = info.get("nom_salon", self.salon_cible)
                texte_salon = f"<#{self.salon_cible}>" if existe else f"⚠️ #{nom_salon} *(salon supprimé)*"
                texte_joueur = obtenir_texte_affichage_responsable(info)
                embed.add_field(name="🔎 Filiale sélectionnée", value=f"Salon : {texte_salon}\nJoueur : {texte_joueur}", inline=False)

        pied = "Utilise les menus ci-dessous pour ajouter, modifier ou supprimer une filiale"
        if self.nb_pages > 1:
            pied = f"Page {self.page + 1}/{self.nb_pages} • " + pied
        embed.set_footer(text=pied)
        return embed

    async def on_select_existante(self, interaction: discord.Interaction):
        valeur = self.select_existantes.values[0]
        if valeur == "_aucune":
            await interaction.response.defer()
            return
        self.salon_cible = valeur
        self._rafraichir()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=3)
    async def bouton_precedent(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page > 0:
            self.page -= 1
        self._rafraichir()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=3)
    async def bouton_suivant(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.page < self.nb_pages - 1:
            self.page += 1
        self._rafraichir()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

    @discord.ui.button(label="💾 Enregistrer", style=discord.ButtonStyle.success, row=3)
    async def bouton_enregistrer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.select_salon.values or not self.select_joueur.values:
            await interaction.response.send_message(
                "⚠️ Choisis un salon (menu 📺) ET un joueur (menu 👤) avant de cliquer sur Enregistrer.",
                ephemeral=True
            )
            return

        salon_choisi = self.select_salon.values[0]
        joueur_choisi = self.select_joueur.values[0]
        salon_id_str = str(salon_choisi.id)

        donnees = charger_filiales()
        serveur = obtenir_ou_creer_serveur_filiale(donnees, self.guild_id_str, interaction.guild.name)
        nouveau = salon_id_str not in serveur["filiales"]
        serveur["filiales"][salon_id_str] = {
            "joueur_id": str(joueur_choisi.id),
            "nom_salon": getattr(salon_choisi, "name", salon_id_str)
        }
        sauvegarder_filiales(donnees)

        self.salon_cible = salon_id_str
        self._rafraichir()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

        verbe = "ajoutée" if nouveau else "modifiée"
        mention_salon = getattr(salon_choisi, "mention", f"<#{salon_id_str}>")
        await interaction.followup.send(
            f"✅ Filiale {verbe} : {mention_salon} → {joueur_choisi.mention}.",
            ephemeral=True
        )

    @discord.ui.button(label="🗑️ Supprimer la sélection", style=discord.ButtonStyle.danger, row=3)
    async def bouton_supprimer(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.salon_cible:
            await interaction.response.send_message("⚠️ Sélectionne d'abord une filiale dans le menu 🗂️.", ephemeral=True)
            return

        donnees = charger_filiales()
        serveur = obtenir_ou_creer_serveur_filiale(donnees, self.guild_id_str, interaction.guild.name)
        supprimee = serveur["filiales"].pop(self.salon_cible, None)
        sauvegarder_filiales(donnees)

        self.salon_cible = None
        self._rafraichir()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)

        if supprimee:
            nom = supprimee.get("nom_salon", "?")
            await interaction.followup.send(f"🗑️ Filiale **#{nom}** supprimée du suivi.", ephemeral=True)

    @discord.ui.button(label="🔄 Actualiser", style=discord.ButtonStyle.secondary, row=3)
    async def bouton_actualiser(self, interaction: discord.Interaction, button: discord.ui.Button):
        self._rafraichir()
        await interaction.response.edit_message(embed=self.construire_embed(), view=self)


# ==========================================
# COMMANDES SLASH DISCORD
# ==========================================
@bot.tree.command(name="config", description="Configure les paramètres des promotions pour un salon spécifique")
@app_commands.describe(
    salon_cible="Le salon à configurer (par défaut, le salon actuel)",
    promo_minimum="Le pourcentage minimum requis (ex: 7)",
    promos_a_afficher="Les positions à afficher séparées par des virgules (ex: 2, 4, 5)",
    position_opportunite="La position qui doit être affichée en Doré (ex: 2)",
    rapport_automatique="Activer ou désactiver le rapport automatique de 04h05 pour ce salon",
    information="Texte envoyé après le rapport automatique de 04h05 (mettre \"aucun\" pour le supprimer)",
    filtres_noms="Mots-clés pour filtrer les biens par nom (ex: mégapole, penthouse). Les biens doivent contenir au moins un de ces mots (mettre \"aucun\" pour désactiver)",
    message_aucune_promo="Message à envoyer quand aucune promo n'est valide (min % ou filtres non respectés). Mettre \"aucun\" pour supprimer"
)
async def config_bot(
    interaction: discord.Interaction,
    salon_cible: discord.TextChannel = None,
    promo_minimum: int = None,
    promos_a_afficher: str = None,
    position_opportunite: int = None,
    rapport_automatique: bool = None,
    information: str = None,
    filtres_noms: str = None,
    message_aucune_promo: str = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    nom_serveur = interaction.guild.name
    target_channel = salon_cible if salon_cible is not None else interaction.channel
    salon_id_str = str(target_channel.id)

    global_config = charger_config()

    if guild_id_str not in global_config:
        global_config[guild_id_str] = {
            "nom_serveur": nom_serveur,
            "salons": {}
        }
    else:
        global_config[guild_id_str]["nom_serveur"] = nom_serveur

    config_salon = obtenir_config_salon(global_config, guild_id_str, salon_id_str)
    modifie = False

    if promo_minimum is not None:
        config_salon["promo_min"] = promo_minimum
        modifie = True

    if promos_a_afficher is not None:
        liste_positions = [int(x.strip()) for x in promos_a_afficher.split(",") if x.strip().isdigit()]
        if liste_positions:
            config_salon["positions_affichage"] = sorted(liste_positions)
            modifie = True
        else:
            await interaction.response.send_message("❌ Format de positions invalide (ex: 2, 4, 5).", ephemeral=True)
            return

    if position_opportunite is not None:
        config_salon["opportunite_position"] = position_opportunite
        modifie = True
        if position_opportunite not in config_salon["positions_affichage"]:
            config_salon["positions_affichage"] = sorted(
                config_salon["positions_affichage"] + [position_opportunite]
            )

    if rapport_automatique is not None:
        config_salon["auto_actif"] = rapport_automatique
        modifie = True

    if information is not None:
        if information.strip().lower() in ("aucun", "supprimer", "none", ""):
            config_salon["information"] = None
        else:
            config_salon["information"] = information
        modifie = True

    if filtres_noms is not None:
        if filtres_noms.strip().lower() in ("aucun", "supprimer", "none", ""):
            config_salon["filtres_noms"] = None
        else:
            # Diviser par virgules et nettoyer les espaces, convertir en minuscules pour la comparaison
            mots_cles = [mot.strip().lower() for mot in filtres_noms.split(",") if mot.strip()]
            config_salon["filtres_noms"] = mots_cles if mots_cles else None
        modifie = True

    if message_aucune_promo is not None:
        if message_aucune_promo.strip().lower() in ("aucun", "supprimer", "none", ""):
            config_salon["message_aucune_promo"] = None
        else:
            config_salon["message_aucune_promo"] = message_aucune_promo
        modifie = True

    if modifie:
        global_config[guild_id_str]["salons"][salon_id_str] = config_salon
        sauvegarder_config(global_config)

    positions_texte = ", ".join(map(str, config_salon['positions_affichage']))
    statut_auto = "🟢 Activé" if config_salon.get("auto_actif", False) else "🔴 Désactivé"

    embed = discord.Embed(
        title=f"⚙️ Configuration de <#{salon_id_str}>",
        description=f"**Serveur :** {nom_serveur}",
        color=discord.Color.blue()
    )
    embed.add_field(name="🏷️ Pourcentage Minimum", value=f"{config_salon['promo_min']}%", inline=True)
    embed.add_field(name="📊 Positions Affichées", value=f"N° {positions_texte}", inline=True)
    embed.add_field(name="⭐ Position de l'Opportunité", value=f"N° {config_salon['opportunite_position']}", inline=True)
    embed.add_field(name="📢 Rapport Auto (4h05)", value=statut_auto, inline=False)
    info_texte = config_salon.get("information")
    embed.add_field(
        name="ℹ️ Rappel après le rapport auto",
        value=info_texte if info_texte else "*Aucun*",
        inline=False
    )
    
    # Affichage des nouveaux paramètres
    filtres_texte = config_salon.get("filtres_noms")
    if filtres_texte:
        embed.add_field(
            name="🔍 Filtres sur les Noms",
            value=", ".join(f"`{mot}`" for mot in filtres_texte),
            inline=False
        )
    else:
        embed.add_field(
            name="🔍 Filtres sur les Noms",
            value="*Aucun filtre (tous les biens acceptés)*",
            inline=False
        )
    
    message_vide = config_salon.get("message_aucune_promo")
    embed.add_field(
        name="📭 Message quand Aucune Promo Valide",
        value=message_vide if message_vide else "*Aucun message*",
        inline=False
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="voir", description="Affiche la configuration actuelle d'un salon")
@app_commands.describe(
    salon_cible="Le salon dont tu veux voir la configuration (par défaut, le salon actuel)"
)
async def voir_config(interaction: discord.Interaction, salon_cible: discord.TextChannel = None):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    target_channel = salon_cible if salon_cible is not None else interaction.channel
    salon_id_str = str(target_channel.id)

    global_config = charger_config()
    server_config = global_config.get(guild_id_str, {})
    salons_config = server_config.get("salons", {})

    if salon_id_str not in salons_config:
        await interaction.response.send_message(
            f"ℹ️ <#{salon_id_str}> n'a pas encore de configuration spécifique. "
            f"Il utilise les valeurs par défaut (`/config` pour le configurer).",
            ephemeral=True
        )
        return

    config_salon = salons_config[salon_id_str]
    positions_texte = ", ".join(map(str, config_salon.get("positions_affichage", [1, 2, 3])))
    statut_auto = "🟢 Activé" if config_salon.get("auto_actif", False) else "🔴 Désactivé"

    embed = discord.Embed(
        title=f"🔍 Configuration de <#{salon_id_str}>",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="🏷️ Pourcentage Minimum", value=f"{config_salon.get('promo_min', 7)}%", inline=True)
    embed.add_field(name="📊 Positions Affichées", value=f"N° {positions_texte}", inline=True)
    embed.add_field(name="⭐ Position de l'Opportunité", value=f"N° {config_salon.get('opportunite_position', 1)}", inline=True)
    embed.add_field(name="📢 Rapport Auto (4h05)", value=statut_auto, inline=False)
    info_texte = config_salon.get("information")
    embed.add_field(
        name="ℹ️ Rappel après le rapport auto",
        value=info_texte if info_texte else "*Aucun*",
        inline=False
    )
    
    # Affichage des nouveaux paramètres
    filtres_texte = config_salon.get("filtres_noms")
    if filtres_texte:
        embed.add_field(
            name="🔍 Filtres sur les Noms",
            value=", ".join(f"`{mot}`" for mot in filtres_texte),
            inline=False
        )
    else:
        embed.add_field(
            name="🔍 Filtres sur les Noms",
            value="*Aucun filtre (tous les biens acceptés)*",
            inline=False
        )
    
    message_vide = config_salon.get("message_aucune_promo")
    embed.add_field(
        name="📭 Message quand Aucune Promo Valide",
        value=message_vide if message_vide else "*Aucun message*",
        inline=False
    )

    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="promo", description="Déclenche manuellement l'analyse des promotions selon la config de ce salon")
async def promo(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    await interaction.response.defer()
    guild_id_str = str(interaction.guild.id)
    salon_id_str = str(interaction.channel.id)
    await generer_et_envoyer_promos(interaction.channel, guild_id_str, salon_id_str, interaction=interaction)


@bot.tree.command(name="maj_api", description="Force le téléchargement immédiat des données de l'API (ignore le cache du jour)")
@app_commands.default_permissions(manage_guild=True)
async def maj_api(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    donnees = await recuperer_donnees_api(forcer=True)
    if not donnees:
        await interaction.followup.send(
            "❌ Le téléchargement des données de l'API a échoué. Vérifie les logs du bot pour plus de détails.",
            ephemeral=True
        )
        return

    nb_entreprises = len(donnees.get("batiments_entreprise", []))
    nb_perso = len(donnees.get("batiments_perso", []))
    aujourdhui = _date_paris_aujourdhui()

    await interaction.followup.send(
        f"✅ **api_cache.json** mis à jour manuellement avec succès ({aujourdhui}).\n"
        f"🏢 {nb_entreprises} bâtiment(s) entreprise • 🏠 {nb_perso} bâtiment(s) perso.",
        ephemeral=True
    )


@bot.tree.command(name="location", description="Trouve le bien le plus rentable et rapide à rembourser selon ton budget")
@app_commands.describe(
    budget="Ton budget maximum (ex: 500G, 1.2T, 2.5P, ou un nombre entier classique)",
    type_bien="Chercher dans les biens d'Entreprise ou de type Perso",
    assurance="Le pack d'assurance à appliquer"
)
@app_commands.choices(type_bien=[
    app_commands.Choice(name="🏢 Entreprise", value="entreprise"),
    app_commands.Choice(name="🏠 Perso", value="perso")
], assurance=[
    app_commands.Choice(name="🛡️ Confort+ (0.26%)", value="confort"),
    app_commands.Choice(name="💎 Premium (0.30%)", value="premium"),
    app_commands.Choice(name="✨ Prestige (0.31%)", value="prestige")
])
async def location(interaction: discord.Interaction, budget: str, type_bien: app_commands.Choice[str], assurance: app_commands.Choice[str]):
    await interaction.response.defer()

    try:
        budget_valeur = parser_montant(budget)
    except ValueError:
        await interaction.followup.send(
            f"❌ Budget invalide : `{budget}`. Utilise un nombre (ex: 1500000000) "
            f"ou un montant avec unité (ex: 500G, 1.2T, 2.5P)."
        )
        return

    if budget_valeur <= 0:
        await interaction.followup.send("❌ Le budget doit être supérieur à 0.")
        return

    taux_assurance = {"confort": 0.0026, "premium": 0.0030, "prestige": 0.0031}[assurance.value]
    donnees = await recuperer_donnees_api()
    cle_api = "batiments_entreprise" if type_bien.value == "entreprise" else "batiments_perso"
    liste_biens = donnees.get(cle_api, [])

    if not liste_biens:
        await interaction.followup.send("⚠️ Aucun bâtiment trouvé.")
        return

    biens_rentables = []
    for bien in liste_biens:
        valeur = int(bien.get("valeur", 0))
        loyer = int(bien.get("loyer", 0))
        charges = int(bien.get("charge", 0))
        if 0 < valeur <= budget_valeur:
            cout_assurance = math.ceil(valeur * taux_assurance)
            net = loyer - charges - cout_assurance
            if net > 0:
                biens_rentables.append({
                    "nom": bien.get("nom", "Sans nom"), "type": bien.get("type", "Inconnu"),
                    "valeur": valeur, "loyer": loyer, "charges": charges, "assurance_frais": cout_assurance,
                    "net": net, "mois": valeur / net
                })

    if not biens_rentables:
        await interaction.followup.send("❌ Aucun bâtiment rentable trouvé.")
        return

    top_bien = sorted(biens_rentables, key=lambda x: x["mois"])[0]
    embed = discord.Embed(
        title="🏆 MEILLEUR INVESTISSEMENT RENTABLE",
        description=f"### {top_bien['nom']}\n*Type : {top_bien['type']}*",
        color=discord.Color.gold()
    )
    embed.add_field(name="🎯 Budget Recherché", value=f"{formater_prix(budget_valeur)} 💰", inline=True)
    embed.add_field(name="💰 Prix d'Achat", value=f"{formater_prix(top_bien['valeur'])} 💰", inline=True)
    embed.add_field(name="⏱️ Amortissement", value=f"**{top_bien['mois']:.1f} mois**", inline=True)

    details_compta = (
        f"📈 **Loyer Brut :** `+{formater_prix(top_bien['loyer'])} 💰`\n"
        f"📉 **Charges Fixes :** `-{formater_prix(top_bien['charges'])} 💰`\n"
        f"🛡️ **Frais Assurance :** `-{formater_prix(top_bien['assurance_frais'])} 💰`\n"
        f"🟩 **Bénéfice Net :** **`{formater_prix(top_bien['net'])} 💰 / mois`**"
    )
    embed.add_field(name="📊 Bilan Financier Mensuel", value=details_compta, inline=False)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="del", description="Supprime tous les messages envoyés par ce bot dans ce salon")
async def delete_bot_messages(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    compteur = 0
    try:
        def est_le_bot(message: discord.Message) -> bool:
            return message.author.id == bot.user.id

        supprimes = await interaction.channel.purge(limit=1000, check=est_le_bot)
        compteur = len(supprimes)
        await interaction.followup.send(f"🗑️ **{compteur}** message(s) supprimé(s).", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Permission manquante : le bot a besoin de la permission « Gérer les messages » dans ce salon.",
            ephemeral=True
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Erreur : {e}", ephemeral=True)


@bot.tree.command(name="allpromo", description="Renvoie manuellement le rappel automatique de 4h05 à tous les salons configurés")
@app_commands.describe(code="Code de sécurité requis pour déclencher cette commande")
async def all_promo(interaction: discord.Interaction, code: int):
    if code != 2009:
        await interaction.response.send_message("❌ Code incorrect.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    global_config = charger_config()

    salons_ok = []
    salons_echec = []

    for guild_id_str, server_data in global_config.items():
        salons = server_data.get("salons", {})
        guild_obj = bot.get_guild(int(guild_id_str))
        nom_serveur = server_data.get("nom_serveur") or (guild_obj.name if guild_obj else None) or f"ID {guild_id_str}"

        for salon_id_str, config_salon in salons.items():
            if not config_salon.get("auto_actif", False):
                continue

            salon = bot.get_channel(int(salon_id_str))
            if salon:
                try:
                    await salon.send("📢 **[Rapport Automatique]** Analyse des opportunités immobilières :")
                    await generer_et_envoyer_promos(salon, guild_id_str, salon_id_str)

                    information = config_salon.get("information")
                    if information:
                        await salon.send(f"ℹ️ **[Rappel]**\n{information}")

                    salons_ok.append(f"✅ {nom_serveur} — <#{salon_id_str}>")
                except Exception as e:
                    salons_echec.append(f"❌ {nom_serveur} — <#{salon_id_str}> ({e})")
            else:
                salons_echec.append(f"❌ {nom_serveur} — salon introuvable (ID {salon_id_str})")

    resume = "**📋 Résumé de l'envoi manuel `/allpromo` :**\n"
    resume += "\n".join(salons_ok) if salons_ok else "Aucun salon envoyé avec succès.\n"
    if salons_echec:
        resume += "\n\n**Échecs :**\n" + "\n".join(salons_echec)

    if len(resume) > 1900:
        resume = resume[:1900] + "\n… (résumé tronqué)"

    await interaction.followup.send(resume, ephemeral=True)


# ==========================================
# COMMANDES /webhook : GESTION DE WEBHOOK.JSON
# ==========================================
groupe_webhook = app_commands.Group(
    name="webhook",
    description="Gère les liens webhook utilisés par le site web (webhook.json)",
    default_permissions=discord.Permissions(manage_guild=True)
)


def _url_webhook_valide(url: str) -> bool:
    return url.startswith("https://discord.com/api/webhooks/") or url.startswith("https://discordapp.com/api/webhooks/")


@groupe_webhook.command(name="ajouter", description="Ajoute un lien webhook à un code d'accès du site web")
@app_commands.describe(
    code="Le code d'accès du site (ex: curly)",
    nom="Le nom affiché dans le menu déroulant (ex: Prime Patrimonia)",
    url="L'URL complète du webhook Discord"
)
async def webhook_ajouter(interaction: discord.Interaction, code: str, nom: str, url: str):
    if not _url_webhook_valide(url):
        await interaction.response.send_message(
            "❌ Cette URL ne ressemble pas à un webhook Discord valide "
            "(elle doit commencer par `https://discord.com/api/webhooks/`).",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    donnees = charger_webhooks()
    code = code.strip().lower()
    liste_salons = donnees.setdefault(code, [])

    deja_existant = False
    for salon in liste_salons:
        if salon.get("nom", "").lower() == nom.lower():
            salon["url"] = url
            deja_existant = True
            break

    if not deja_existant:
        liste_salons.append({"nom": nom, "url": url})

    sauvegarder_webhooks(donnees)
    succes_github, message_github = await pousser_webhook_vers_github(donnees)

    if deja_existant:
        texte = f"🔄 Le webhook **{nom}** existait déjà pour le code `{code}` : son URL a été mise à jour."
    else:
        texte = f"✅ Webhook **{nom}** ajouté au code `{code}` ({len(liste_salons)} salon(s) pour ce code)."

    if succes_github:
        texte += "\n📤 Poussé sur GitHub avec succès."
    else:
        texte += f"\n⚠️ Sauvegardé localement, mais l'envoi vers GitHub a échoué : {message_github}"

    await interaction.followup.send(texte, ephemeral=True)


@groupe_webhook.command(name="supprimer", description="Supprime un lien webhook d'un code d'accès du site web")
@app_commands.describe(
    code="Le code d'accès du site (ex: curly)",
    nom="Le nom exact du webhook à supprimer"
)
async def webhook_supprimer(interaction: discord.Interaction, code: str, nom: str):
    await interaction.response.defer(ephemeral=True)

    donnees = charger_webhooks()
    code = code.strip().lower()
    liste_salons = donnees.get(code)

    if not liste_salons:
        await interaction.followup.send(f"❌ Aucun code `{code}` trouvé dans webhook.json.", ephemeral=True)
        return

    nouvelle_liste = [s for s in liste_salons if s.get("nom", "").lower() != nom.lower()]
    if len(nouvelle_liste) == len(liste_salons):
        await interaction.followup.send(f"❌ Aucun webhook nommé **{nom}** trouvé pour le code `{code}`.", ephemeral=True)
        return

    if nouvelle_liste:
        donnees[code] = nouvelle_liste
    else:
        del donnees[code]

    sauvegarder_webhooks(donnees)
    succes_github, message_github = await pousser_webhook_vers_github(donnees)

    texte = f"🗑️ Webhook **{nom}** supprimé du code `{code}`."
    if succes_github:
        texte += "\n📤 Poussé sur GitHub avec succès."
    else:
        texte += f"\n⚠️ Sauvegardé localement, mais l'envoi vers GitHub a échoué : {message_github}"

    await interaction.followup.send(texte, ephemeral=True)


@groupe_webhook.command(name="liste", description="Liste les webhooks enregistrés pour un code d'accès")
@app_commands.describe(code="Le code d'accès du site (ex: curly). Laisser vide pour voir tous les codes.")
async def webhook_liste(interaction: discord.Interaction, code: str = None):
    donnees = charger_webhooks()

    if code:
        code = code.strip().lower()
        liste_salons = donnees.get(code)
        if not liste_salons:
            await interaction.response.send_message(f"❌ Aucun code `{code}` trouvé dans webhook.json.", ephemeral=True)
            return
        texte = "\n".join(f"• **{s['nom']}** — `{s['url']}`" for s in liste_salons)
        await interaction.response.send_message(f"📁 Webhooks pour le code `{code}` :\n{texte}", ephemeral=True)
    else:
        if not donnees:
            await interaction.response.send_message("❌ webhook.json est vide.", ephemeral=True)
            return
        texte = "\n".join(f"• `{c}` — {len(salons)} salon(s)" for c, salons in donnees.items())
        await interaction.response.send_message(f"📁 Codes enregistrés :\n{texte}", ephemeral=True)


bot.tree.add_command(groupe_webhook)


# ==========================================
# COMMANDES /rappel : GESTION DES RAPPELS (RAPPEL.JSON)
# ==========================================
groupe_rappel = app_commands.Group(
    name="rappel",
    description="Gère les rappels automatiques (rappel.json)",
    default_permissions=discord.Permissions(manage_guild=True)
)


@groupe_rappel.command(name="ajouter", description="Créer un rappel (ex: tous, semaine, weekend ou lundi, mardi)")
@app_commands.describe(
    jours="Les jours (ex: tous | semaine | weekend | lundi, mercredi, vendredi)",
    heure="Heure d'envoi au format HH:MM (ex: 14:30)",
    message="Le texte du rappel à envoyer",
    salon="Le salon cible (par défaut, le salon actuel)"
)
async def rappel_ajouter(
    interaction: discord.Interaction,
    jours: str,
    heure: str,
    message: str,
    salon: discord.TextChannel = None
):
    try:
        indices, nom_affichage = parser_jours(jours)
    except ValueError:
        await interaction.response.send_message(
            "❌ Jours invalides. Exemples valides : `tous`, `lundi, mardi`, `semaine`, `weekend`.",
            ephemeral=True
        )
        return

    heure_clean = heure.strip()
    try:
        datetime.strptime(heure_clean, "%H:%M")
    except ValueError:
        await interaction.response.send_message(
            "❌ Format d'heure invalide. Utilisez le format `HH:MM` (ex: `14:30` ou `09:05`).",
            ephemeral=True
        )
        return

    target_channel = salon if salon is not None else interaction.channel
    rappels = charger_rappels()

    nouveaux_ids = [int(i) for i in rappels.keys() if i.isdigit()]
    prochain_id = str(max(nouveaux_ids) + 1 if nouveaux_ids else 1)

    rappels[prochain_id] = {
        "id": prochain_id,
        "guild_id": str(interaction.guild_id),
        "salon_id": str(target_channel.id),
        "jour_nom": nom_affichage,
        "jours_indices": indices,
        "heure": heure_clean,
        "message": message,
        "auteur_id": str(interaction.user.id)
    }

    sauvegarder_rappels(rappels)

    embed = discord.Embed(
        title="⏰ Nouveau Rappel Programmé",
        description=f"Le rappel **#{prochain_id}** a été enregistré avec succès !",
        color=discord.Color.green()
    )
    embed.add_field(name="📅 Jours", value=nom_affichage, inline=True)
    embed.add_field(name="🕐 Heure", value=heure_clean, inline=True)
    embed.add_field(name="📌 Salon", value=target_channel.mention, inline=True)
    embed.add_field(name="📝 Message", value=message, inline=False)

    await interaction.response.send_message(embed=embed)


@groupe_rappel.command(name="modifier", description="Modifier un rappel existant par son ID")
@app_commands.describe(
    id_rappel="L'identifiant du rappel à modifier (ex: 1)",
    jours="Nouveaux jours (ex: tous, lundi, jeudi...) [optionnel]",
    heure="Nouvelle heure au format HH:MM (optionnel)",
    message="Nouveau texte du rappel (optionnel)",
    salon="Nouveau salon cible (optionnel)"
)
async def rappel_modifier(
    interaction: discord.Interaction,
    id_rappel: str,
    jours: str = None,
    heure: str = None,
    message: str = None,
    salon: discord.TextChannel = None
):
    rappels = charger_rappels()
    id_key = id_rappel.strip()

    if id_key not in rappels:
        await interaction.response.send_message(f"❌ Aucun rappel trouvé avec l'ID `#{id_key}`.", ephemeral=True)
        return

    rappel = rappels[id_key]
    modifie = False

    if jours is not None:
        try:
            indices, nom_affichage = parser_jours(jours)
            rappel["jour_nom"] = nom_affichage
            rappel["jours_indices"] = indices
            modifie = True
        except ValueError:
            await interaction.response.send_message(
                "❌ Jours invalides. Exemples valides : `tous`, `lundi, mardi`, `semaine`, `weekend`.",
                ephemeral=True
            )
            return

    if heure is not None:
        heure_clean = heure.strip()
        try:
            datetime.strptime(heure_clean, "%H:%M")
            rappel["heure"] = heure_clean
            modifie = True
        except ValueError:
            await interaction.response.send_message(
                "❌ Format d'heure invalide. Utilisez le format `HH:MM` (ex: `14:30`).",
                ephemeral=True
            )
            return

    if message is not None:
        rappel["message"] = message
        modifie = True

    if salon is not None:
        rappel["salon_id"] = str(salon.id)
        modifie = True

    if not modifie:
        await interaction.response.send_message("⚠️ Aucun paramètre à modifier n'a été fourni.", ephemeral=True)
        return

    sauvegarder_rappels(rappels)

    target_channel = interaction.guild.get_channel(int(rappel["salon_id"]))
    mention_salon = target_channel.mention if target_channel else f"ID {rappel['salon_id']}"

    embed = discord.Embed(
        title=f"✏️ Rappel #{id_key} Modifié",
        color=discord.Color.blue()
    )
    embed.add_field(name="📅 Jours", value=rappel["jour_nom"], inline=True)
    embed.add_field(name="🕐 Heure", value=rappel["heure"], inline=True)
    embed.add_field(name="📌 Salon", value=mention_salon, inline=True)
    embed.add_field(name="📝 Message", value=rappel["message"], inline=False)

    await interaction.response.send_message(embed=embed)


@groupe_rappel.command(name="supprimer", description="Supprimer un rappel existant par son ID")
@app_commands.describe(id_rappel="L'identifiant du rappel à supprimer (ex: 1)")
async def rappel_supprimer(interaction: discord.Interaction, id_rappel: str):
    rappels = charger_rappels()
    id_key = id_rappel.strip()

    if id_key not in rappels:
        await interaction.response.send_message(f"❌ Aucun rappel trouvé avec l'ID `#{id_key}`.", ephemeral=True)
        return

    del rappels[id_key]
    sauvegarder_rappels(rappels)

    await interaction.response.send_message(f"🗑️ Le rappel `#{id_key}` a été supprimé avec succès.", ephemeral=True)


@groupe_rappel.command(name="liste", description="Afficher la liste de tous les rappels enregistrés")
async def rappel_liste(interaction: discord.Interaction):
    rappels = charger_rappels()

    if not rappels:
        await interaction.response.send_message("ℹ️ Aucun rappel n'est actuellement enregistré dans `rappel.json`.", ephemeral=True)
        return

    embed = discord.Embed(
        title="📋 Liste des Rappels Automatiques",
        color=discord.Color.gold()
    )

    for id_key, item in rappels.items():
        salon_id = item.get("salon_id")
        salon_obj = interaction.guild.get_channel(int(salon_id)) if interaction.guild else None
        salon_text = salon_obj.mention if salon_obj else f"<#{salon_id}>"

        valeur_field = (
            f"📅 **Jours :** {item.get('jour_nom')}\n"
            f"🕐 **Heure :** {item.get('heure')}\n"
            f"📌 **Salon :** {salon_text}\n"
            f"💬 **Message :** {item.get('message')}"
        )
        embed.add_field(name=f"Rappel #{id_key}", value=valeur_field, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(groupe_rappel)


# ==========================================
# COMMANDES /choixpromo : SÉLECTION QUOTIDIENNE DES PROMOS
# ==========================================
groupe_choixpromo = app_commands.Group(
    name="choixpromo",
    description="Système de sélection quotidienne des promos à publier (choixpromo.json)",
    default_permissions=discord.Permissions(manage_guild=True)
)


@groupe_choixpromo.command(
    name="configurer",
    description="Configure le système : salon de sélection, salon de destination, rôle à ping, activation"
)
@app_commands.describe(
    salon_liste="Le salon où la liste des promos du jour est envoyée (ping du rôle + menu de sélection)",
    salon_destination="Le salon où les promos choisies sont envoyées automatiquement après validation",
    role="Le rôle à ping quand la liste des promos du jour est envoyée",
    actif="Active (True) ou désactive (False) l'envoi automatique quotidien à 04h30"
)
async def choixpromo_configurer(
    interaction: discord.Interaction,
    salon_liste: discord.TextChannel,
    salon_destination: discord.TextChannel,
    role: discord.Role,
    actif: bool
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    if salon_liste.id == salon_destination.id:
        await interaction.response.send_message(
            "❌ Le salon de sélection et le salon de destination doivent être différents.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees_choixpromo = charger_choixpromo()

    donnees_choixpromo[guild_id_str] = {
        "salon_liste": str(salon_liste.id),
        "salon_destination": str(salon_destination.id),
        "role_id": str(role.id),
        "actif": actif
    }
    sauvegarder_choixpromo(donnees_choixpromo)

    statut = "🟢 Activé" if actif else "🔴 Désactivé"
    embed = discord.Embed(
        title="⚙️ Configuration /choixpromo",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="📋 Salon de sélection", value=salon_liste.mention, inline=True)
    embed.add_field(name="📤 Salon de destination", value=salon_destination.mention, inline=True)
    embed.add_field(name="🔔 Rôle pingé", value=role.mention, inline=True)
    embed.add_field(name="⏰ Envoi automatique (04h30)", value=statut, inline=False)

    await interaction.response.send_message(embed=embed)


@groupe_choixpromo.command(
    name="demander",
    description="Déclenche manuellement la demande de sélection des promos (si l'envoi auto de 04h30 a échoué)"
)
async def choixpromo_demander(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    guild_id_str = str(interaction.guild.id)
    donnees_choixpromo = charger_choixpromo()
    config_choix = donnees_choixpromo.get(guild_id_str)

    if not config_choix:
        await interaction.followup.send(
            "❌ Le système `/choixpromo` n'est pas configuré sur ce serveur. "
            "Utilise `/choixpromo configurer` d'abord.",
            ephemeral=True
        )
        return

    succes, message = await envoyer_demande_choixpromo(bot, guild_id_str, config_choix)
    if succes:
        await interaction.followup.send(f"✅ {message}", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ {message}", ephemeral=True)


@groupe_choixpromo.command(name="voir", description="Affiche la configuration actuelle du système /choixpromo")
async def choixpromo_voir(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees_choixpromo = charger_choixpromo()
    config_choix = donnees_choixpromo.get(guild_id_str)

    if not config_choix:
        await interaction.response.send_message(
            "ℹ️ Le système `/choixpromo` n'est pas encore configuré sur ce serveur. "
            "Utilise `/choixpromo configurer` pour le mettre en place.",
            ephemeral=True
        )
        return

    salon_liste = interaction.guild.get_channel(int(config_choix.get("salon_liste", 0)))
    salon_destination = interaction.guild.get_channel(int(config_choix.get("salon_destination", 0)))
    role_id = config_choix.get("role_id")
    statut = "🟢 Activé" if config_choix.get("actif", False) else "🔴 Désactivé"

    embed = discord.Embed(
        title="🔍 Configuration /choixpromo",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="📋 Salon de sélection", value=salon_liste.mention if salon_liste else "❌ Introuvable", inline=True)
    embed.add_field(name="📤 Salon de destination", value=salon_destination.mention if salon_destination else "❌ Introuvable", inline=True)
    embed.add_field(name="🔔 Rôle pingé", value=f"<@&{role_id}>" if role_id else "❌ Aucun", inline=True)
    embed.add_field(name="⏰ Envoi automatique (04h30)", value=statut, inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(groupe_choixpromo)


# ==========================================
# COMMANDES /filiale : ASSOCIATION SALON <-> JOUEUR (FILIALE.JSON)
# ==========================================
groupe_filiale = app_commands.Group(
    name="filiale",
    description="Gère les filiales suivies quotidiennement (filiale.json)",
    default_permissions=discord.Permissions(manage_guild=True)
)


@groupe_filiale.command(name="ajouter", description="Associe le salon actuel à un joueur en tant que filiale suivie")
@app_commands.describe(joueur="Le joueur responsable de la filiale dans ce salon")
async def filiale_ajouter(interaction: discord.Interaction, joueur: discord.Member):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    salon_id_str = str(interaction.channel.id)

    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    if salon_id_str in serveur["filiales"]:
        await interaction.response.send_message(
            f"⚠️ Ce salon est déjà associé à une filiale. Utilise `/filiale modifier` pour changer le joueur, "
            f"ou `/filiale supprimer` pour la retirer.",
            ephemeral=True
        )
        return

    serveur["filiales"][salon_id_str] = {
        "joueur_id": str(joueur.id),
        "nom_salon": interaction.channel.name
    }
    sauvegarder_filiales(donnees)

    await interaction.response.send_message(
        f"✅ Filiale enregistrée : {interaction.channel.mention} est maintenant associé à {joueur.mention}.",
        ephemeral=True
    )


@groupe_filiale.command(name="modifier", description="Change le joueur responsable de la filiale du salon actuel")
@app_commands.describe(joueur="Le nouveau joueur responsable de cette filiale")
async def filiale_modifier(interaction: discord.Interaction, joueur: discord.Member):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    salon_id_str = str(interaction.channel.id)

    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    if salon_id_str not in serveur["filiales"]:
        await interaction.response.send_message(
            f"❌ Ce salon n'est pas encore associé à une filiale. Utilise `/filiale ajouter` d'abord.",
            ephemeral=True
        )
        return

    ancien_joueur_id = serveur["filiales"][salon_id_str].get("joueur_id")
    serveur["filiales"][salon_id_str]["joueur_id"] = str(joueur.id)
    serveur["filiales"][salon_id_str]["nom_salon"] = interaction.channel.name
    sauvegarder_filiales(donnees)

    ancien_texte = f"<@{ancien_joueur_id}>" if ancien_joueur_id else "*aucun*"
    await interaction.response.send_message(
        f"✏️ Filiale de {interaction.channel.mention} modifiée : {ancien_texte} → {joueur.mention}.",
        ephemeral=True
    )


@groupe_filiale.command(name="supprimer", description="Retire l'association filiale du salon actuel")
async def filiale_supprimer(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    salon_id_str = str(interaction.channel.id)

    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    if salon_id_str not in serveur["filiales"]:
        await interaction.response.send_message(
            "❌ Ce salon n'est associé à aucune filiale.",
            ephemeral=True
        )
        return

    del serveur["filiales"][salon_id_str]
    sauvegarder_filiales(donnees)

    await interaction.response.send_message(
        f"🗑️ La filiale associée à {interaction.channel.mention} a été supprimée.",
        ephemeral=True
    )


@groupe_filiale.command(name="liste", description="Affiche la liste des filiales enregistrées sur ce serveur")
async def filiale_liste(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = donnees.get(guild_id_str, {})
    filiales = serveur.get("filiales", {})

    if not filiales:
        await interaction.response.send_message(
            "ℹ️ Aucune filiale enregistrée sur ce serveur. Utilise `/filiale ajouter` dans un salon.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="📋 Filiales enregistrées",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.blue()
    )

    for salon_id, info in filiales.items():
        mention_joueur = obtenir_texte_affichage_responsable(info)
        embed.add_field(name=f"#{info.get('nom_salon', salon_id)}", value=f"<#{salon_id}> — {mention_joueur}", inline=False)

    await interaction.response.send_message(embed=embed, ephemeral=True)


@groupe_filiale.command(
    name="panneau",
    description="Ouvre un tableau de bord pour ajouter/modifier/supprimer toutes les filiales depuis ce salon"
)
async def filiale_panneau(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)
    sauvegarder_filiales(donnees)

    vue = VuePanneauFiliales(guild_id_str)
    await interaction.response.send_message(embed=vue.construire_embed(), view=vue, ephemeral=True)


bot.tree.add_command(groupe_filiale)


# ==========================================
# COMMANDES /vacance ET /rentrée : ABSENCE TEMPORAIRE D'UN RESPONSABLE DE FILIALE
# ==========================================
@bot.tree.command(
    name="vacance",
    description="Marque un joueur en vacances : le(s) rôle(s) indiqué(s) sont ping à sa place"
)
@app_commands.describe(
    joueur="Le joueur qui gère une filiale et qui ne sera plus présent pendant un temps indéterminé",
    role1="Rôle à ping à la place du joueur pendant son absence",
    role2="Rôle supplémentaire à ping à la place du joueur (optionnel)",
    role3="Rôle supplémentaire à ping à la place du joueur (optionnel)"
)
@app_commands.default_permissions(manage_guild=True)
async def vacance(
    interaction: discord.Interaction,
    joueur: discord.Member,
    role1: discord.Role,
    role2: discord.Role = None,
    role3: discord.Role = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    filiales_concernees = [
        (salon_id, info) for salon_id, info in serveur["filiales"].items()
        if info.get("joueur_id") == str(joueur.id)
    ]

    if not filiales_concernees:
        await interaction.response.send_message(
            f"⚠️ {joueur.mention} ne gère actuellement aucune filiale enregistrée sur ce serveur.",
            ephemeral=True
        )
        return

    roles = [role1] + [r for r in (role2, role3) if r is not None]
    roles_ids = [str(r.id) for r in roles]
    aujourdhui = _date_paris_aujourdhui()

    for salon_id, info in filiales_concernees:
        info["absent"] = True
        info["role_remplacant_ids"] = roles_ids
        info["absent_depuis"] = aujourdhui

    sauvegarder_filiales(donnees)

    try:
        await actualiser_tableau_filiales(interaction.client, guild_id_str, forcer_nouveau=False)
    except Exception as e:
        print(f"❌ [filiale] Impossible de mettre à jour le tableau après /vacance : {e}")

    liste_salons = "\n".join(f"• <#{sid}>" for sid, _ in filiales_concernees)
    liste_roles = " ".join(r.mention for r in roles)

    embed = discord.Embed(
        title="🌴 Joueur marqué en vacances",
        description=(
            f"{joueur.mention} ne sera plus ping pour la ou les filiale(s) suivante(s), le temps de son absence :\n"
            f"{liste_salons}\n\n"
            f"À la place, {liste_roles} sera/seront ping pour le bouton quotidien et les relances.\n"
            f"Utilise `/rentrée` quand {joueur.mention} sera de retour."
        ),
        color=discord.Color.teal()
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="rentrée",
    description="Marque le retour de vacances d'un joueur : il redevient ping normalement pour ses filiales"
)
@app_commands.describe(joueur="Le joueur qui revient de vacances")
@app_commands.default_permissions(manage_guild=True)
async def rentree(interaction: discord.Interaction, joueur: discord.Member):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    filiales_concernees = [
        (salon_id, info) for salon_id, info in serveur["filiales"].items()
        if info.get("joueur_id") == str(joueur.id) and info.get("absent")
    ]

    if not filiales_concernees:
        await interaction.response.send_message(
            f"ℹ️ {joueur.mention} n'est actuellement marqué en vacances pour aucune filiale.",
            ephemeral=True
        )
        return

    for salon_id, info in filiales_concernees:
        info["absent"] = False
        info["role_remplacant_ids"] = []
        info["absent_depuis"] = None

    sauvegarder_filiales(donnees)

    try:
        await actualiser_tableau_filiales(interaction.client, guild_id_str, forcer_nouveau=False)
    except Exception as e:
        print(f"❌ [filiale] Impossible de mettre à jour le tableau après /rentrée : {e}")

    liste_salons = "\n".join(f"• <#{sid}>" for sid, _ in filiales_concernees)

    embed = discord.Embed(
        title="☀️ Retour de vacances",
        description=(
            f"{joueur.mention} est de nouveau présent et reçoit à nouveau les pings pour :\n"
            f"{liste_salons}"
        ),
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)


# ==========================================
# COMMANDES /referant : SALON ET JOUEUR RÉFÉRENT (FILIALE.JSON)
# ==========================================
groupe_referant = app_commands.Group(
    name="referant",
    description="Gère le salon et le joueur référent chargés du suivi des filiales (filiale.json)",
    default_permissions=discord.Permissions(manage_guild=True)
)


@groupe_referant.command(
    name="definir",
    description="Définit le salon actuel comme salon référent (joueur et/ou rôle en charge du suivi, en option)"
)
@app_commands.describe(
    joueur="Le joueur référent chargé du suivi (optionnel)",
    role="Le rôle référent à notifier en plus (ou à la place) du joueur (optionnel)"
)
async def referant_definir(interaction: discord.Interaction, joueur: discord.Member = None, role: discord.Role = None):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    serveur["referent"]["salon_id"] = str(interaction.channel.id)
    if joueur is not None:
        serveur["referent"]["joueur_id"] = str(joueur.id)
    if role is not None:
        serveur["referent"]["role_id"] = str(role.id)
    sauvegarder_filiales(donnees)

    texte_joueur = joueur.mention if joueur is not None else (
        f"<@{serveur['referent']['joueur_id']}>" if serveur["referent"].get("joueur_id") else "*Aucun*"
    )
    texte_role = role.mention if role is not None else (
        f"<@&{serveur['referent']['role_id']}>" if serveur["referent"].get("role_id") else "*Aucun*"
    )

    embed = discord.Embed(
        title="📌 Salon Référent Défini",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.green()
    )
    embed.add_field(name="📤 Salon référent", value=interaction.channel.mention, inline=True)
    embed.add_field(name="🧑‍💼 Référent (gestionnaire)", value=texte_joueur, inline=True)
    embed.add_field(name="🏷️ Rôle référent", value=texte_role, inline=True)

    await interaction.response.send_message(embed=embed)


@groupe_referant.command(name="modifier", description="Modifie le salon, le joueur et/ou le rôle référent déjà configurés")
@app_commands.describe(
    salon="Nouveau salon référent (optionnel)",
    joueur="Nouveau joueur référent chargé du suivi (optionnel)",
    role="Nouveau rôle référent à notifier (optionnel)"
)
async def referant_modifier(
    interaction: discord.Interaction,
    salon: discord.TextChannel = None,
    joueur: discord.Member = None,
    role: discord.Role = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    if salon is None and joueur is None and role is None:
        await interaction.response.send_message(
            "⚠️ Fournis au moins un salon, un joueur ou un rôle à modifier.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    if not serveur["referent"].get("salon_id"):
        await interaction.response.send_message(
            "❌ Aucun salon référent n'est encore configuré. Utilise `/referant definir` d'abord.",
            ephemeral=True
        )
        return

    if salon is not None:
        serveur["referent"]["salon_id"] = str(salon.id)
    if joueur is not None:
        serveur["referent"]["joueur_id"] = str(joueur.id)
    if role is not None:
        serveur["referent"]["role_id"] = str(role.id)
    sauvegarder_filiales(donnees)

    salon_id_final = serveur["referent"]["salon_id"]
    joueur_id_final = serveur["referent"].get("joueur_id")
    role_id_final = serveur["referent"].get("role_id")

    embed = discord.Embed(title="✏️ Référent Modifié", color=discord.Color.blue())
    embed.add_field(name="📤 Salon référent", value=f"<#{salon_id_final}>", inline=True)
    embed.add_field(name="🧑‍💼 Référent (gestionnaire)", value=f"<@{joueur_id_final}>" if joueur_id_final else "*Aucun*", inline=True)
    embed.add_field(name="🏷️ Rôle référent", value=f"<@&{role_id_final}>" if role_id_final else "*Aucun*", inline=True)

    await interaction.response.send_message(embed=embed)


@groupe_referant.command(name="supprimer", description="Retire la configuration du salon, du joueur et du rôle référent")
async def referant_supprimer(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    serveur["referent"] = {"salon_id": None, "joueur_id": None, "role_id": None}
    sauvegarder_filiales(donnees)

    await interaction.response.send_message("🗑️ Le salon, le joueur et le rôle référents ont été réinitialisés.", ephemeral=True)


@groupe_referant.command(name="voir", description="Affiche la configuration actuelle du référent")
async def referant_voir(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = donnees.get(guild_id_str, {})
    referent = serveur.get("referent", {})
    salon_id = referent.get("salon_id")
    joueur_id = referent.get("joueur_id")
    role_id = referent.get("role_id")

    if not salon_id and not joueur_id and not role_id:
        await interaction.response.send_message(
            "ℹ️ Aucun référent configuré. Utilise `/referant definir` dans le salon souhaité.",
            ephemeral=True
        )
        return

    embed = discord.Embed(
        title="🔍 Configuration du Référent",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="📤 Salon référent", value=f"<#{salon_id}>" if salon_id else "❌ Non défini", inline=True)
    embed.add_field(name="🧑‍💼 Référent (gestionnaire)", value=f"<@{joueur_id}>" if joueur_id else "*Aucun*", inline=True)
    embed.add_field(name="🏷️ Rôle référent", value=f"<@&{role_id}>" if role_id else "*Aucun*", inline=True)

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(groupe_referant)


# ==========================================
# COMMANDES /param : ACTIVATION ET HEURE DU SUIVI QUOTIDIEN (FILIALE.JSON)
# ==========================================
groupe_param = app_commands.Group(
    name="param",
    description="Active/désactive et programme l'heure du suivi quotidien des filiales (filiale.json)",
    default_permissions=discord.Permissions(manage_guild=True)
)


@groupe_param.command(name="configurer", description="Active ou désactive le suivi automatique et/ou change son heure")
@app_commands.describe(
    action="Active ou désactive l'envoi automatique quotidien du formulaire",
    heure="Heure d'envoi au format HH:MM (ex: 23:30). Obligatoire à la première activation."
)
@app_commands.choices(action=[
    app_commands.Choice(name="✅ Activer", value="activer"),
    app_commands.Choice(name="🚫 Désactiver", value="désactiver"),
])
async def param_configurer(interaction: discord.Interaction, action: app_commands.Choice[str], heure: str = None):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    if heure is not None:
        heure_clean = heure.strip()
        try:
            datetime.strptime(heure_clean, "%H:%M")
        except ValueError:
            await interaction.response.send_message(
                "❌ Format d'heure invalide. Utilise le format `HH:MM` (ex: `23:30`).",
                ephemeral=True
            )
            return
        serveur["parametres"]["heure"] = heure_clean

    activer = action.value == "activer"

    if activer and not serveur["parametres"].get("heure"):
        await interaction.response.send_message(
            "❌ Aucune heure n'est configurée. Indique une heure (ex: `/param configurer action:Activer heure:23:30`).",
            ephemeral=True
        )
        return

    serveur["parametres"]["actif"] = activer
    sauvegarder_filiales(donnees)

    statut = "🟢 Activé" if activer else "🔴 Désactivé"
    embed = discord.Embed(
        title="⚙️ Paramètres du Suivi Quotidien des Filiales",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.blue()
    )
    embed.add_field(name="📡 Statut", value=statut, inline=True)
    embed.add_field(name="🕐 Heure d'envoi", value=serveur["parametres"].get("heure") or "*Non définie*", inline=True)

    await interaction.response.send_message(embed=embed)


@groupe_param.command(
    name="bouton",
    description="Active/désactive le rappel par bouton dans chaque salon de filiale et programme ses heures"
)
@app_commands.describe(
    action="Active ou désactive le système de rappel par bouton",
    heure_rappel="Heure d'envoi du rappel (avec bouton) dans chaque salon de filiale, format HH:MM (ex: 18:00)",
    heure_recap="Heure d'envoi du récapitulatif dans le salon référent, format HH:MM (ex: 23:00)",
    message="Texte perso du rappel ({filiale} = nom du salon). Tape « défaut » pour le message de base."
)
@app_commands.choices(action=[
    app_commands.Choice(name="✅ Activer", value="activer"),
    app_commands.Choice(name="🚫 Désactiver", value="désactiver"),
])
async def param_bouton(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    heure_rappel: str = None,
    heure_recap: str = None,
    message: str = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    for label, valeur in (("heure_rappel", heure_rappel), ("heure_recap", heure_recap)):
        if valeur is not None:
            valeur_clean = valeur.strip()
            try:
                datetime.strptime(valeur_clean, "%H:%M")
            except ValueError:
                await interaction.response.send_message(
                    f"❌ Format d'heure invalide pour `{label}`. Utilise le format `HH:MM` (ex: `18:00`).",
                    ephemeral=True
                )
                return
            serveur["parametres"][label] = valeur_clean

    if message is not None:
        message_clean = message.strip()
        if message_clean.lower() in ("défaut", "default", "reset", "aucun", ""):
            serveur["parametres"]["bouton_message"] = None
        else:
            serveur["parametres"]["bouton_message"] = message_clean

    activer = action.value == "activer"

    if activer and (not serveur["parametres"].get("heure_rappel") or not serveur["parametres"].get("heure_recap")):
        await interaction.response.send_message(
            "❌ Il faut configurer `heure_rappel` ET `heure_recap` pour activer ce système "
            "(ex: `/param bouton action:Activer heure_rappel:18:00 heure_recap:23:00`).",
            ephemeral=True
        )
        return

    serveur["parametres"]["bouton_actif"] = activer
    sauvegarder_filiales(donnees)

    statut = "🟢 Activé" if activer else "🔴 Désactivé"
    message_actuel = serveur["parametres"].get("bouton_message")
    embed = discord.Embed(
        title="🗂️ Rappel par Bouton — Suivi des Filiales",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.orange() if activer else discord.Color.dark_grey()
    )
    embed.add_field(name="📡 Statut", value=statut, inline=True)
    embed.add_field(
        name="📝 Message du rappel",
        value=(f"```{message_actuel[:500]}```" if message_actuel else "*Message par défaut*"),
        inline=False
    )
    embed.add_field(name="⏰ Heure du rappel", value=serveur["parametres"].get("heure_rappel") or "*Non définie*", inline=True)
    embed.add_field(name="📊 Heure du récap", value=serveur["parametres"].get("heure_recap") or "*Non définie*", inline=True)

    await interaction.response.send_message(embed=embed)


@groupe_param.command(
    name="injection",
    description="Programme une demande quotidienne d'injection (mêmes infos que /injection, en plus rapide)"
)
@app_commands.describe(
    action="Active ou désactive la demande quotidienne d'injection",
    heure="Heure d'envoi du message de demande quotidienne, format HH:MM (ex: 20:00)",
    salon="Salon où envoyer le message de demande quotidienne (obligatoire à la première activation)",
    role="Rôle à mentionner dans le message de demande (optionnel)",
    joueur="Joueur à mentionner dans le message de demande (optionnel)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="✅ Activer", value="activer"),
    app_commands.Choice(name="🚫 Désactiver", value="désactiver"),
])
async def param_injection(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    heure: str = None,
    salon: discord.TextChannel = None,
    role: discord.Role = None,
    joueur: discord.Member = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)
    conf = serveur["injection_programmee"]

    if heure is not None:
        heure_clean = heure.strip()
        try:
            datetime.strptime(heure_clean, "%H:%M")
        except ValueError:
            await interaction.response.send_message(
                "❌ Format d'heure invalide. Utilise le format `HH:MM` (ex: `20:00`).",
                ephemeral=True
            )
            return
        conf["heure"] = heure_clean

    if salon is not None:
        conf["salon_id"] = str(salon.id)
    if role is not None:
        conf["role_id"] = str(role.id)
    if joueur is not None:
        conf["joueur_id"] = str(joueur.id)

    activer = action.value == "activer"

    if activer and (not conf.get("heure") or not conf.get("salon_id")):
        await interaction.response.send_message(
            "❌ Il faut configurer `heure` ET `salon` pour activer ce système "
            "(ex: `/param injection action:Activer heure:20:00 salon:#ma-filiale role:@Injection`).",
            ephemeral=True
        )
        return

    conf["actif"] = activer
    sauvegarder_filiales(donnees)

    statut = "🟢 Activé" if activer else "🔴 Désactivé"
    salon_id_final = conf.get("salon_id")
    role_id_final = conf.get("role_id")
    joueur_id_final = conf.get("joueur_id")

    embed = discord.Embed(
        title="💉 Injection Programmée — Demande Quotidienne",
        description=(
            f"**Serveur :** {interaction.guild.name}\n"
            "Chaque jour à l'heure configurée, un message sera envoyé avec un bouton pour "
            "remplir les mêmes informations que `/injection` (montant, salon, rôle)."
        ),
        color=discord.Color.gold() if activer else discord.Color.dark_grey()
    )
    embed.add_field(name="📡 Statut", value=statut, inline=True)
    embed.add_field(name="🕐 Heure", value=conf.get("heure") or "*Non définie*", inline=True)
    embed.add_field(name="📤 Salon", value=f"<#{salon_id_final}>" if salon_id_final else "*Non défini*", inline=True)
    embed.add_field(name="🏷️ Rôle mentionné", value=f"<@&{role_id_final}>" if role_id_final else "*Aucun*", inline=True)
    embed.add_field(name="🧑‍💼 Joueur mentionné", value=f"<@{joueur_id_final}>" if joueur_id_final else "*Aucun*", inline=True)

    await interaction.response.send_message(embed=embed)


@groupe_param.command(
    name="tableau",
    description="Active/désactive le tableau quotidien de suivi (1 message mis à jour en direct)"
)
@app_commands.describe(
    action="Active ou désactive le tableau quotidien",
    salon="Salon où envoyer le tableau quotidien (obligatoire à la première activation)",
    heure="Heure de création du nouveau tableau chaque jour, format HH:MM (ex: 00:05)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="✅ Activer", value="activer"),
    app_commands.Choice(name="🚫 Désactiver", value="désactiver"),
])
async def param_tableau(
    interaction: discord.Interaction,
    action: app_commands.Choice[str],
    salon: discord.TextChannel = None,
    heure: str = None
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    if salon is not None:
        serveur["parametres"]["salon_tableau_id"] = str(salon.id)

    if heure is not None:
        heure_clean = heure.strip()
        try:
            datetime.strptime(heure_clean, "%H:%M")
        except ValueError:
            await interaction.response.send_message(
                "❌ Format d'heure invalide. Utilise le format `HH:MM` (ex: `00:05`).",
                ephemeral=True
            )
            return
        serveur["parametres"]["heure_tableau"] = heure_clean

    activer = action.value == "activer"

    if activer and (not serveur["parametres"].get("salon_tableau_id") or not serveur["parametres"].get("heure_tableau")):
        await interaction.response.send_message(
            "❌ Il faut configurer `salon` ET `heure` pour activer le tableau "
            "(ex: `/param tableau action:Activer salon:#salon heure:00:05`).",
            ephemeral=True
        )
        return

    serveur["parametres"]["tableau_actif"] = activer
    sauvegarder_filiales(donnees)

    statut = "🟢 Activé" if activer else "🔴 Désactivé"
    salon_id_final = serveur["parametres"].get("salon_tableau_id")
    embed = discord.Embed(
        title="📅 Tableau Quotidien de Suivi — Filiales",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.blurple() if activer else discord.Color.dark_grey()
    )
    embed.add_field(name="📡 Statut", value=statut, inline=True)
    embed.add_field(name="📤 Salon", value=f"<#{salon_id_final}>" if salon_id_final else "*Non défini*", inline=True)
    embed.add_field(name="⏰ Heure de création", value=serveur["parametres"].get("heure_tableau") or "*Non définie*", inline=True)

    await interaction.response.send_message(embed=embed)


@groupe_param.command(
    name="relance",
    description="Active/désactive une relance automatique pour les filiales pas encore gérées"
)
@app_commands.describe(
    action="Active ou désactive la relance automatique",
    heure="Heure de la relance, format HH:MM (ex: 20:00), pour les filiales encore non gérées"
)
@app_commands.choices(action=[
    app_commands.Choice(name="✅ Activer", value="activer"),
    app_commands.Choice(name="🚫 Désactiver", value="désactiver"),
])
async def param_relance(interaction: discord.Interaction, action: app_commands.Choice[str], heure: str = None):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    if heure is not None:
        heure_clean = heure.strip()
        try:
            datetime.strptime(heure_clean, "%H:%M")
        except ValueError:
            await interaction.response.send_message(
                "❌ Format d'heure invalide. Utilise le format `HH:MM` (ex: `20:00`).",
                ephemeral=True
            )
            return
        serveur["parametres"]["heure_relance"] = heure_clean

    activer = action.value == "activer"

    if activer and not serveur["parametres"].get("heure_relance"):
        await interaction.response.send_message(
            "❌ Il faut configurer une `heure` pour activer la relance "
            "(ex: `/param relance action:Activer heure:20:00`).",
            ephemeral=True
        )
        return

    serveur["parametres"]["relance_actif"] = activer
    sauvegarder_filiales(donnees)

    statut = "🟢 Activée" if activer else "🔴 Désactivée"
    embed = discord.Embed(
        title="⏰ Relance Automatique — Filiales Non Gérées",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.red() if activer else discord.Color.dark_grey()
    )
    embed.add_field(name="📡 Statut", value=statut, inline=True)
    embed.add_field(name="🕐 Heure de relance", value=serveur["parametres"].get("heure_relance") or "*Non définie*", inline=True)

    await interaction.response.send_message(embed=embed)


@groupe_param.command(
    name="supprimer",
    description="Supprime (réinitialise) la config des rappels : formulaire, bouton, tableau, relance ou tout"
)
@app_commands.describe(cible="Quel rappel réinitialiser complètement (heures + statut actif/inactif)")
@app_commands.choices(cible=[
    app_commands.Choice(name="📋 Formulaire interactif", value="formulaire"),
    app_commands.Choice(name="🗂️ Rappel par bouton", value="bouton"),
    app_commands.Choice(name="📅 Tableau quotidien", value="tableau"),
    app_commands.Choice(name="⏰ Relance automatique", value="relance"),
    app_commands.Choice(name="💉 Injection programmée", value="injection"),
    app_commands.Choice(name="🧹 Tout réinitialiser", value="tout"),
])
async def param_supprimer(interaction: discord.Interaction, cible: app_commands.Choice[str]):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)
    parametres = serveur["parametres"]

    if cible.value in ("formulaire", "tout"):
        parametres["actif"] = False
        parametres["heure"] = None
        parametres["derniere_execution"] = None
    if cible.value in ("bouton", "tout"):
        parametres["bouton_actif"] = False
        parametres["heure_rappel"] = None
        parametres["heure_recap"] = None
        parametres["derniere_execution_rappel"] = None
        parametres["derniere_execution_recap"] = None
        parametres["bouton_message"] = None
    if cible.value in ("tableau", "tout"):
        parametres["tableau_actif"] = False
        parametres["salon_tableau_id"] = None
        parametres["heure_tableau"] = None
        parametres["tableau_message_id"] = None
        parametres["tableau_derniere_date"] = None
    if cible.value in ("relance", "tout"):
        parametres["relance_actif"] = False
        parametres["heure_relance"] = None
        parametres["derniere_execution_relance"] = None
    if cible.value in ("injection", "tout"):
        conf_injection = serveur["injection_programmee"]
        conf_injection["actif"] = False
        conf_injection["heure"] = None
        conf_injection["salon_id"] = None
        conf_injection["role_id"] = None
        conf_injection["joueur_id"] = None
        conf_injection["derniere_execution"] = None

    sauvegarder_filiales(donnees)

    embed = discord.Embed(
        title="🗑️ Rappel(s) Supprimé(s)",
        description=f"**Serveur :** {interaction.guild.name}\n{cible.name} désactivé(s) et réinitialisé(s) (heures effacées).",
        color=discord.Color.dark_grey()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@groupe_param.command(name="voir", description="Affiche les paramètres actuels du suivi quotidien des filiales")
async def param_voir(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = donnees.get(guild_id_str, {})
    parametres = serveur.get("parametres", {})

    statut_formulaire = "🟢 Activé" if parametres.get("actif", False) else "🔴 Désactivé"
    statut_bouton = "🟢 Activé" if parametres.get("bouton_actif", False) else "🔴 Désactivé"

    embed = discord.Embed(
        title="🔍 Paramètres du Suivi Quotidien des Filiales",
        description=f"**Serveur :** {interaction.guild.name}",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📋 Formulaire interactif",
        value=f"{statut_formulaire}\n🕐 Heure : {parametres.get('heure') or '*Non définie*'}",
        inline=True
    )
    message_bouton = parametres.get("bouton_message")
    embed.add_field(
        name="🗂️ Rappel par bouton",
        value=(
            f"{statut_bouton}\n"
            f"⏰ Rappel : {parametres.get('heure_rappel') or '*Non définie*'}\n"
            f"📊 Récap : {parametres.get('heure_recap') or '*Non définie*'}\n"
            f"📝 Message : {'personnalisé' if message_bouton else '*par défaut*'}"
        ),
        inline=True
    )

    statut_tableau = "🟢 Activé" if parametres.get("tableau_actif", False) else "🔴 Désactivé"
    salon_tableau_id = parametres.get("salon_tableau_id")
    embed.add_field(
        name="📅 Tableau quotidien",
        value=(
            f"{statut_tableau}\n"
            f"📤 Salon : {f'<#{salon_tableau_id}>' if salon_tableau_id else '*Non défini*'}\n"
            f"⏰ Heure : {parametres.get('heure_tableau') or '*Non définie*'}"
        ),
        inline=True
    )

    statut_relance = "🟢 Activée" if parametres.get("relance_actif", False) else "🔴 Désactivée"
    embed.add_field(
        name="⏰ Relance automatique",
        value=f"{statut_relance}\n🕐 Heure : {parametres.get('heure_relance') or '*Non définie*'}",
        inline=True
    )

    conf_injection = serveur.get("injection_programmee", {})
    statut_injection = "🟢 Activée" if conf_injection.get("actif", False) else "🔴 Désactivée"
    salon_injection_id = conf_injection.get("salon_id")
    embed.add_field(
        name="💉 Injection programmée",
        value=(
            f"{statut_injection}\n"
            f"🕐 Heure : {conf_injection.get('heure') or '*Non définie*'}\n"
            f"📤 Salon : {f'<#{salon_injection_id}>' if salon_injection_id else '*Non défini*'}"
        ),
        inline=True
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)


bot.tree.add_command(groupe_param)


# ==========================================
# COMMANDES /verif : DÉCLENCHEMENT MANUEL ANTICIPÉ (FILIALE.JSON)
# ==========================================
groupe_verif = app_commands.Group(
    name="verif",
    description="Déclenche manuellement, en avance, certaines vérifications automatiques",
    default_permissions=discord.Permissions(manage_guild=True)
)


@groupe_verif.command(
    name="filiale",
    description="Envoie dès maintenant le formulaire quotidien des filiales (l'envoi automatique du jour est annulé)"
)
async def verif_filiale(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    guild_id_str = str(interaction.guild.id)
    donnees = charger_filiales()
    serveur = obtenir_ou_creer_serveur_filiale(donnees, guild_id_str, interaction.guild.name)

    aujourdhui = _date_paris_aujourdhui()

    succes, message = await envoyer_formulaire_filiales(bot, guild_id_str, serveur)

    if succes:
        # On marque la journée comme traitée : l'envoi automatique de ce soir ne se déclenchera pas.
        # Tu peux quand même relancer /verif filiale autant de fois que tu veux manuellement.
        serveur["parametres"]["derniere_execution"] = aujourdhui
        sauvegarder_filiales(donnees)
        await interaction.followup.send(
            f"✅ {message}\nℹ️ L'envoi automatique programmé aujourd'hui ne sera pas déclenché une 2e fois.",
            ephemeral=True
        )
    else:
        await interaction.followup.send(f"❌ {message}", ephemeral=True)


@groupe_verif.command(
    name="tableau",
    description="Affiche/actualise immédiatement le tableau de suivi des filiales (nouveau message)"
)
async def verif_tableau(interaction: discord.Interaction):
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)

    guild_id_str = str(interaction.guild.id)
    succes, message = await actualiser_tableau_filiales(bot, guild_id_str, forcer_nouveau=True)

    if succes:
        await interaction.followup.send(f"✅ {message}", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ {message}", ephemeral=True)


bot.tree.add_command(groupe_verif)


# ==========================================
# COMMANDE /injection : INJECTION AUTOMATIQUE FILIALES
# ==========================================
async def envoyer_embed_injection(
    salon: discord.abc.Messageable,
    montant: str,
    role: discord.Role | None,
    auteur_nom: str
) -> tuple[bool, str]:
    """
    Construit et envoie le message d'injection (embed jaune + mention du rôle éventuel).
    Fonction partagée entre /injection et le système d'injection programmée (bouton + modale),
    pour garantir strictement le même message dans les deux cas.
    """
    try:
        embed = discord.Embed(
            title="💉 Injection Effectuée",
            description=f"Une injection de **{montant}** a été effectuée dans toutes les filiales.",
            color=discord.Color.from_rgb(255, 223, 0)  # Jaune
        )
        embed.set_footer(text=f"Injection réalisée par {auteur_nom}")
        embed.timestamp = datetime.now(ZoneInfo("Europe/Paris"))

        contenu = ""
        if role:
            contenu = f"{role.mention} "
        contenu += "**Injection automatique en cours pour toutes les filiales...**"

        await salon.send(content=contenu, embed=embed)
        return True, f"Injection de **{montant}** enregistrée et notifiée dans {salon.mention}"
    except discord.Forbidden:
        return False, f"Permissions manquantes dans {getattr(salon, 'mention', salon)}."
    except Exception as e:
        return False, f"Erreur lors de l'injection : {e}"


@bot.tree.command(
    name="injection",
    description="Effectue une injection dans toutes les filiales avec un montant donné"
)
@app_commands.describe(
    montant="Montant de l'injection (obligatoire, peut contenir des lettres)",
    salon="Salon optionnel (défaut: le salon actuel)",
    role="Rôle optionnel à notifier"
)
async def commande_injection(
    interaction: discord.Interaction,
    montant: str,
    salon: discord.TextChannel | None = None,
    role: discord.Role | None = None
):
    """
    Effectue une injection automatique dans toutes les filiales.
    - montant : obligatoire (ex: "500K", "1M", "100")
    - salon : optionnel (défaut: salon actuel)
    - role : optionnel (rôle à mentionner)
    """
    if interaction.guild is None:
        await interaction.response.send_message(
            "❌ Cette commande doit être utilisée dans un serveur, pas en message privé.",
            ephemeral=True
        )
        return

    # Utiliser le salon fourni ou le salon actuel
    canal_injection = salon or interaction.channel

    if canal_injection is None:
        await interaction.response.send_message(
            "❌ Impossible de déterminer le salon. Veuillez spécifier un salon.",
            ephemeral=True
        )
        return

    await interaction.response.defer()

    succes, message = await envoyer_embed_injection(canal_injection, montant, role, interaction.user.display_name)

    if succes:
        await interaction.followup.send(f"✅ {message}", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ {message}", ephemeral=True)


# ==========================================
# INJECTION PROGRAMMÉE : DEMANDE QUOTIDIENNE (bouton + modale = mêmes infos que /injection)
# ==========================================
class ModalInjectionProgrammee(discord.ui.Modal, title="💉 Injection du jour"):
    """
    Modale ouverte quand quelqu'un clique sur le bouton du message quotidien d'injection
    programmée. Demande exactement les mêmes informations que la commande /injection
    (montant, salon, rôle) puis envoie le même message qu'/injection avec ces paramètres.
    """
    montant = discord.ui.TextInput(
        label="Montant de l'injection",
        placeholder="ex: 500K, 1M, 250000",
        required=True,
        max_length=50
    )
    salon_texte = discord.ui.TextInput(
        label="Salon (mention, ID ou nom)",
        placeholder="Laisser vide = ce salon",
        required=False,
        max_length=100
    )
    role_texte = discord.ui.TextInput(
        label="Rôle à notifier (mention, ID ou nom)",
        placeholder="Laisser vide = aucun rôle",
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Cette action doit être faite dans un serveur.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild

        # Résoudre le salon (par défaut : le salon où le message a été envoyé)
        canal_injection = interaction.channel
        texte_salon = (self.salon_texte.value or "").strip()
        if texte_salon:
            salon_resolu = resoudre_salon_depuis_texte(guild, texte_salon)
            if salon_resolu is None:
                await interaction.followup.send(
                    f"❌ Salon « {texte_salon} » introuvable. Réessaie avec une mention, un ID ou un nom exact.",
                    ephemeral=True
                )
                return
            canal_injection = salon_resolu

        # Résoudre le rôle (optionnel)
        role_resolu = None
        texte_role = (self.role_texte.value or "").strip()
        if texte_role:
            role_resolu = resoudre_role_depuis_texte(guild, texte_role)
            if role_resolu is None:
                await interaction.followup.send(
                    f"❌ Rôle « {texte_role} » introuvable. Réessaie avec une mention, un ID ou un nom exact.",
                    ephemeral=True
                )
                return

        succes, message = await envoyer_embed_injection(
            canal_injection, self.montant.value.strip(), role_resolu, interaction.user.display_name
        )

        if succes:
            await interaction.followup.send(f"✅ {message}", ephemeral=True)
        else:
            await interaction.followup.send(f"❌ {message}", ephemeral=True)


class VueDemandeInjectionProgrammee(discord.ui.View):
    """
    Vue PERSISTANTE (custom_id fixe, timeout=None) attachée au message quotidien de demande
    d'injection. Le bouton ouvre une modale demandant les mêmes infos que /injection.
    """

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Remplir l'injection du jour",
        style=discord.ButtonStyle.success,
        custom_id="injection:demande_v1",
        emoji="💉"
    )
    async def bouton_remplir(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModalInjectionProgrammee())


@tasks.loop(minutes=1)
async def filiale_injection_programmee_task(bot_client):
    """
    Chaque minute, vérifie si l'heure configurée via /param injection correspond à l'heure
    actuelle (Europe/Paris). Si oui, envoie dans le salon configuré un message (pingant le
    rôle et/ou le joueur choisis) avec un bouton qui ouvre une modale pour renseigner les
    mêmes informations que /injection (montant, salon, rôle), et déclenche automatiquement
    le même message que la commande /injection une fois la modale validée.
    """
    now = datetime.now(ZoneInfo("Europe/Paris"))
    heure_actuelle_str = now.strftime("%H:%M")
    aujourdhui = _date_paris_aujourdhui()

    donnees_filiales = charger_filiales()
    if not donnees_filiales:
        return

    for guild_id_str, server_data in list(donnees_filiales.items()):
        conf = server_data.get("injection_programmee", {})
        if not conf.get("actif", False):
            continue
        if conf.get("heure") != heure_actuelle_str:
            continue
        if conf.get("derniere_execution") == aujourdhui:
            continue

        salon_id = conf.get("salon_id")
        salon = bot_client.get_channel(int(salon_id)) if salon_id else None
        if not salon:
            print(f"❌ [injection] Salon introuvable pour le serveur {guild_id_str}.")
            continue

        mentions = []
        if conf.get("role_id"):
            mentions.append(f"<@&{conf['role_id']}>")
        if conf.get("joueur_id"):
            mentions.append(f"<@{conf['joueur_id']}>")
        contenu = " ".join(mentions) if mentions else None

        embed = discord.Embed(
            title="💉 Injection quotidienne à renseigner",
            description=(
                "C'est l'heure de renseigner l'injection du jour !\n"
                "Clique sur le bouton ci-dessous et remplis le montant (et, si besoin, "
                "le salon et le rôle à notifier) : le message sera envoyé automatiquement, "
                "exactement comme avec `/injection`."
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Suivi quotidien de l'injection")

        try:
            await salon.send(content=contenu, embed=embed, view=VueDemandeInjectionProgrammee())
            donnees_filiales[guild_id_str]["injection_programmee"]["derniere_execution"] = aujourdhui
            sauvegarder_filiales(donnees_filiales)
        except Exception as e:
            print(f"❌ [injection] Erreur lors de l'envoi pour le serveur {guild_id_str} : {e}")


# ==========================================
# COMMANDE /help : LISTE ET EXPLICATION DE TOUTES LES COMMANDES
# ==========================================
AIDE_COMMANDES = {
    "promotions": {
        "titre": "📊 Promotions & Salons",
        "commandes": [
            ("/config", "Configure les paramètres de promotions d'un salon (seuil minimum, positions affichées, position opportunité, rapport automatique de 04h05)."),
            ("/voir", "Affiche la configuration actuelle de promotions d'un salon."),
            ("/promo", "Déclenche manuellement l'analyse des promotions selon la config de ce salon."),
            ("/maj_api", "Force le téléchargement immédiat des données de l'API (ignore le cache du jour)."),
            ("/location", "Trouve le bien le plus rentable et le plus rapide à rembourser selon un budget donné."),
            ("/del", "Supprime tous les messages envoyés par le bot dans ce salon."),
            ("/allpromo", "Renvoie manuellement, dans tous les salons configurés, le rapport automatique de 04h05."),
        ]
    },
    "webhook": {
        "titre": "🔗 Webhooks",
        "commandes": [
            ("/webhook ajouter", "Ajoute un lien webhook à un code d'accès du site web."),
            ("/webhook supprimer", "Supprime un lien webhook d'un code d'accès du site web."),
            ("/webhook liste", "Liste les webhooks enregistrés pour un code d'accès."),
        ]
    },
    "rappel": {
        "titre": "⏰ Rappels Programmés",
        "commandes": [
            ("/rappel ajouter", "Crée un rappel récurrent (tous les jours, en semaine, le week-end, ou des jours précis) envoyé à une heure donnée dans un salon."),
            ("/rappel modifier", "Modifie un rappel existant via son ID (jours, heure, salon ou message)."),
            ("/rappel supprimer", "Supprime un rappel existant via son ID."),
            ("/rappel liste", "Affiche la liste de tous les rappels programmés enregistrés."),
        ]
    },
    "choixpromo": {
        "titre": "🎯 Choix Promo",
        "commandes": [
            ("/choixpromo configurer", "Configure les salons (liste + destination) et le rôle utilisés par le système de choix de promo (envoi automatique 04h30)."),
            ("/choixpromo demander", "Déclenche manuellement l'envoi immédiat de la demande de choix de promo."),
            ("/choixpromo voir", "Affiche la configuration actuelle du système /choixpromo."),
        ]
    },
    "filiale": {
        "titre": "🏢 Suivi des Filiales",
        "commandes": [
            ("/filiale ajouter", "Associe le salon actuel à un joueur en tant que filiale suivie."),
            ("/filiale modifier", "Change le joueur responsable de la filiale du salon actuel."),
            ("/filiale supprimer", "Retire l'association filiale du salon actuel."),
            ("/filiale liste", "Affiche la liste des filiales enregistrées sur ce serveur."),
            ("/filiale panneau", "Tableau de bord pour ajouter/modifier/supprimer TOUTES les filiales depuis n'importe quel salon — utile pour nettoyer les filiales dont le salon a été supprimé sans passer par /filiale supprimer."),
            ("/vacance", "Marque un joueur responsable d'une ou plusieurs filiales comme absent (temps indéterminé) : il n'est plus ping, et le(s) rôle(s) indiqué(s) sont ping à sa place pour le bouton quotidien et les relances. L'absence apparaît aussi sur le tableau de suivi."),
            ("/rentrée", "Marque le retour d'un joueur précédemment mis en `/vacance` : il redevient ping normalement pour ses filiales."),
        ]
    },
    "referant": {
        "titre": "📤 Référent des Filiales",
        "commandes": [
            ("/referant definir", "Définit le salon actuel comme salon référent (et, en option, le joueur/gestionnaire ET/OU le rôle en charge du suivi)."),
            ("/referant modifier", "Modifie le salon, le joueur et/ou le rôle référent déjà configurés."),
            ("/referant supprimer", "Réinitialise la configuration du salon, du joueur et du rôle référent."),
            ("/referant voir", "Affiche la configuration actuelle du référent (salon, joueur, rôle)."),
        ]
    },
    "param": {
        "titre": "⚙️ Paramètres du Suivi des Filiales",
        "commandes": [
            ("/param configurer", "Active/désactive le formulaire quotidien interactif (cases à cocher + notes) et programme son heure d'envoi."),
            ("/param bouton", "Active/désactive le rappel automatique par bouton envoyé dans chaque salon de filiale, programme l'heure du rappel et celle du récapitulatif, et permet de personnaliser le texte du message quotidien (paramètre `message`, ou `défaut` pour revenir au message d'origine)."),
            ("/param tableau", "Active/désactive le tableau quotidien de suivi (1 seul message, mis à jour en direct à chaque clic), et choisit son salon + son heure de création."),
            ("/param relance", "Active/désactive une relance automatique, à une heure donnée, envoyée uniquement dans les salons des filiales pas encore gérées ce jour-là."),
            ("/param injection", "Programme une demande quotidienne d'injection : à l'heure choisie, un message est envoyé dans le salon choisi (avec ping d'un rôle et/ou d'un joueur), avec un bouton qui ouvre un formulaire pour renseigner montant/salon/rôle et envoyer automatiquement le même message que `/injection`."),
            ("/param supprimer", "Réinitialise (désactive + efface les heures) le formulaire, le bouton, le tableau, la relance, l'injection programmée, ou tout à la fois."),
            ("/param voir", "Affiche tous les paramètres actuels du suivi des filiales (formulaire, bouton, tableau, relance, injection programmée)."),
        ]
    },
    "verif": {
        "titre": "🔁 Vérifications Manuelles",
        "commandes": [
            ("/verif filiale", "Envoie immédiatement le formulaire quotidien des filiales, sans attendre l'heure programmée (peut être relancé autant de fois que voulu)."),
            ("/verif tableau", "Affiche/actualise immédiatement le tableau de suivi des filiales (envoie un nouveau message dans le salon configuré via `/param tableau`)."),
        ]
    },
    "injection": {
        "titre": "💉 Injection Automatique",
        "commandes": [
            ("/injection", "Effectue une injection automatique dans toutes les filiales avec un montant donné. Accepte un montant obligatoire (peut contenir des lettres comme '500K', '1M'), un salon optionnel, et un rôle optionnel à notifier. Affiche un embed jaune de confirmation."),
            ("/param injection", "Programme l'envoi quotidien, à heure fixe, d'un message avec bouton pour remplir les mêmes infos que `/injection` sans avoir à retaper la commande (voir catégorie ⚙️ Paramètres)."),
        ]
    },
    "histoire": {
        "titre": "📖 Histoire",
        "commandes": [
            ("/histoire", "Regroupe tous les messages entre deux IDs (inclus) pour créer un texte complet. Les mots de chaque message sont séparés par un espace. Affiche le résultat dans un embed formaté."),
        ]
    },
}


def construire_embed_aide(categorie: str = "accueil") -> discord.Embed:
    if categorie == "accueil" or categorie not in AIDE_COMMANDES:
        embed = discord.Embed(
            title="📚 Aide — Liste des Commandes",
            description="Choisis une catégorie dans le menu ci-dessous pour voir le détail de chaque commande.",
            color=discord.Color.blurple()
        )
        for donnees in AIDE_COMMANDES.values():
            noms = ", ".join(f"`{nom}`" for nom, _ in donnees["commandes"])
            embed.add_field(name=donnees["titre"], value=noms[:1024], inline=False)
        total = sum(len(d["commandes"]) for d in AIDE_COMMANDES.values())
        embed.set_footer(text=f"{total} commande(s) au total")
        return embed

    donnees = AIDE_COMMANDES[categorie]
    embed = discord.Embed(title=donnees["titre"], color=discord.Color.blurple())
    for nom, description in donnees["commandes"]:
        embed.add_field(name=f"`{nom}`", value=description, inline=False)
    embed.set_footer(text="Choisis une autre catégorie dans le menu, ou reviens à la 🏠 Vue d'ensemble")
    return embed


class VueAide(discord.ui.View):
    """
    Menu déroulant permettant de naviguer entre les catégories de commandes du bot.
    Se referme automatiquement (menu désactivé) après 2 minutes sans la moindre interaction
    (chaque sélection dans le menu réinitialise ce délai de 2 minutes).
    """

    def __init__(self):
        super().__init__(timeout=120)  # 2 minutes d'inactivité avant fermeture automatique
        self.message: discord.Message | None = None
        options = [
            discord.SelectOption(label="🏠 Vue d'ensemble", value="accueil", description="Toutes les catégories de commandes")
        ]
        for cle, donnees in AIDE_COMMANDES.items():
            options.append(discord.SelectOption(
                label=donnees["titre"][:100],
                value=cle,
                description=f"{len(donnees['commandes'])} commande(s)"
            ))

        self.select = discord.ui.Select(placeholder="📚 Choisis une catégorie de commandes...", options=options)
        self.select.callback = self.on_select
        self.add_item(self.select)

    async def on_select(self, interaction: discord.Interaction):
        embed = construire_embed_aide(self.select.values[0])
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self) -> None:
        """Désactive le menu sur le message une fois les 2 minutes d'inactivité écoulées."""
        self.select.disabled = True
        self.select.placeholder = "⏳ Menu fermé (inactif depuis 2 minutes) — relance /help pour l'ouvrir à nouveau"
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


@bot.tree.command(name="help", description="Affiche la liste de toutes les commandes du bot et leur explication")
async def commande_help(interaction: discord.Interaction):
    vue = VueAide()
    embed = construire_embed_aide("accueil")
    await interaction.response.send_message(embed=embed, view=vue)
    vue.message = await interaction.original_response()


# ==========================================
# COMMANDE /histoire : COMBINE LES MESSAGES ENTRE DEUX IDs
# ==========================================
@bot.tree.command(name="histoire", description="Regroupe tous les messages entre deux IDs pour créer un texte complet")
@app_commands.describe(
    id_debut="L'ID du premier message (début de l'histoire)",
    id_fin="L'ID du dernier message (fin de l'histoire)"
)
async def commande_histoire(interaction: discord.Interaction, id_debut: str, id_fin: str):
    """
    Récupère tous les messages entre deux IDs (inclus) et les combine en un seul texte.
    Chaque mot d'un message est séparé par un espace.
    """
    try:
        id_debut_int = int(id_debut)
        id_fin_int = int(id_fin)
    except ValueError:
        embed = discord.Embed(
            title="❌ Erreur",
            description="Les IDs doivent être des nombres valides.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Déterminer l'ordre correct (le plus petit en premier)
    id_min = min(id_debut_int, id_fin_int)
    id_max = max(id_debut_int, id_fin_int)

    await interaction.response.defer()

    try:
        # Récupérer le salon courant
        salon = interaction.channel
        if not salon:
            embed = discord.Embed(
                title="❌ Erreur",
                description="Impossible d'accéder au salon.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return

        # Récupérer tous les messages du salon
        messages = []
        async for msg in salon.history(limit=None, oldest_first=True):
            if id_min <= msg.id <= id_max:
                messages.append(msg)

        if not messages:
            embed = discord.Embed(
                title="❌ Aucun message trouvé",
                description=f"Aucun message trouvé entre les IDs {id_debut} et {id_fin}.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return

        # Combiner le contenu des messages
        texte_complet = " ".join(msg.content.strip() for msg in messages if msg.content.strip())

        if not texte_complet:
            embed = discord.Embed(
                title="❌ Aucun contenu",
                description="Les messages trouvés ne contiennent aucun texte.",
                color=discord.Color.red()
            )
            await interaction.followup.send(embed=embed)
            return

        # Créer l'embed avec le texte complet
        embed = discord.Embed(
            title="📖 Histoire Complète",
            description=texte_complet,
            color=discord.Color.blurple()
        )
        embed.set_footer(text=f"{len(messages)} message(s) combiné(s)")

        # Compter les messages par auteur
        compteur_auteurs = {}
        for msg in messages:
            auteur = msg.author.display_name
            compteur_auteurs[auteur] = compteur_auteurs.get(auteur, 0) + 1

        # Trier par nombre de messages (décroissant)
        auteurs_tries = sorted(compteur_auteurs.items(), key=lambda x: x[1], reverse=True)

        # Créer l'embed des statistiques
        embed_stats = discord.Embed(
            title="📊 Statistiques des Participants",
            color=discord.Color.gold()
        )

        for auteur, count in auteurs_tries:
            emoji = "🏆" if auteur == auteurs_tries[0][0] else "✍️"
            embed_stats.add_field(
                name=f"{emoji} {auteur}",
                value=f"**{count}** message(s)",
                inline=False
            )

        await interaction.followup.send(embeds=[embed, embed_stats])

    except Exception as e:
        embed = discord.Embed(
            title="❌ Erreur",
            description=f"Une erreur est survenue : {str(e)}",
            color=discord.Color.red()
        )
        await interaction.followup.send(embed=embed)


TOKEN = os.environ.get("DISCORD_TOKEN")
if TOKEN:
    bot.run(TOKEN)
