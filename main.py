# -*- coding: utf-8 -*-
"""
N.I BUSINESS v3.3
Application de gestion commerciale hors connexion - Kivy + SQLite.
Test cible : Pydroid 3 avec Kivy installé depuis Pip.
"""

import os
import sqlite3
import hashlib
import hmac
import secrets
import shutil
from datetime import datetime, timedelta

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp, sp
from kivy.core.window import Window
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.popup import Popup
from kivy.uix.spinner import Spinner
from kivy.uix.checkbox import CheckBox

# ------------------------- Identité visuelle
FOND = (0.045, 0.065, 0.105, 1)
MARINE = (0.055, 0.13, 0.28, 1)
CARTE = (0.105, 0.15, 0.23, 1)
OR = (0.98, 0.75, 0.16, 1)
BLEU = (0.16, 0.39, 0.78, 1)
VERT = (0.12, 0.57, 0.34, 1)
ROUGE = (0.72, 0.19, 0.19, 1)
BLANC = (1, 1, 1, 1)
GRIS = (0.78, 0.81, 0.86, 1)


def montant(v):
    try:
        return f"{float(v):,.0f}".replace(",", " ") + " FC"
    except Exception:
        return "0 FC"


def nombre(v):
    try:
        return float(str(v).replace(" ", "").replace(",", "."))
    except Exception:
        return None


def hacher(mdp, sel):
    return hashlib.pbkdf2_hmac(
        "sha256", mdp.encode("utf-8"), bytes.fromhex(sel), 150000
    ).hex()


class Base:
    def __init__(self, chemin):
        self.con = sqlite3.connect(chemin)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA foreign_keys=ON")
        self.con.executescript("""
        CREATE TABLE IF NOT EXISTS utilisateurs(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT UNIQUE COLLATE NOCASE,
            sel TEXT NOT NULL, hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'vendeur',
            actif INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS produits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT UNIQUE COLLATE NOCASE,
            achat REAL NOT NULL DEFAULT 0,
            vente REAL NOT NULL DEFAULT 0,
            stock REAL NOT NULL DEFAULT 0,
            seuil REAL NOT NULL DEFAULT 5
        );
        CREATE TABLE IF NOT EXISTS clients(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nom TEXT UNIQUE COLLATE NOCASE,
            telephone TEXT DEFAULT '',
            dette REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS ventes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, facture TEXT NOT NULL,
            produit_id INTEGER, produit TEXT NOT NULL,
            qte REAL NOT NULL, prix REAL NOT NULL,
            total REAL NOT NULL, benefice REAL NOT NULL,
            client TEXT DEFAULT '', credit INTEGER DEFAULT 0,
            utilisateur TEXT
        );
        CREATE TABLE IF NOT EXISTS depenses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, motif TEXT NOT NULL,
            montant REAL NOT NULL, utilisateur TEXT
        );
        CREATE TABLE IF NOT EXISTS remboursements(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, client TEXT NOT NULL,
            montant REAL NOT NULL, utilisateur TEXT
        );
        CREATE TABLE IF NOT EXISTS journal(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL, utilisateur TEXT, action TEXT
        );
        CREATE TABLE IF NOT EXISTS entreprise(
            cle TEXT PRIMARY KEY,
            valeur TEXT NOT NULL DEFAULT ''
        );
        """)
        # Migrations compatibles avec les anciennes bases v2.1.
        self._ajouter_colonne("ventes", "annule", "INTEGER NOT NULL DEFAULT 0")
        self._ajouter_colonne("utilisateurs", "code_secours_hash", "TEXT DEFAULT ''")
        self._ajouter_colonne("utilisateurs", "echecs", "INTEGER NOT NULL DEFAULT 0")
        self._ajouter_colonne("utilisateurs", "bloque_jusqua", "TEXT DEFAULT ''")
        self.con.commit()

    def _ajouter_colonne(self, table, colonne, definition):
        noms = [r[1] for r in self.con.execute(f"PRAGMA table_info({table})").fetchall()]
        if colonne not in noms:
            self.con.execute(f"ALTER TABLE {table} ADD COLUMN {colonne} {definition}")

    def q(self, sql, args=()):
        return self.con.execute(sql, args).fetchall()

    def x(self, sql, args=()):
        cur = self.con.execute(sql, args)
        self.con.commit()
        return cur

    def log(self, user, action):
        self.x("INSERT INTO journal(date,utilisateur,action) VALUES(?,?,?)",
               (datetime.now().strftime("%Y-%m-%d %H:%M"), user, action))

    def authentifier(self, nom, mdp):
        r = self.q("SELECT * FROM utilisateurs WHERE nom=?", (nom.strip(),))
        if not r or not r[0]["actif"]:
            return None
        u = r[0]
        maintenant = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if u["bloque_jusqua"] and u["bloque_jusqua"] > maintenant:
            return "BLOQUE"
        if hmac.compare_digest(hacher(mdp, u["sel"]), u["hash"]):
            self.x("UPDATE utilisateurs SET echecs=0,bloque_jusqua='' WHERE id=?", (u["id"],))
            return dict(self.q("SELECT * FROM utilisateurs WHERE id=?", (u["id"],))[0])
        echecs = u["echecs"] + 1
        blocage = (datetime.now() + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S") if echecs >= 5 else ""
        self.x("UPDATE utilisateurs SET echecs=?,bloque_jusqua=? WHERE id=?", (0 if blocage else echecs, blocage, u["id"]))
        return "BLOQUE" if blocage else None

    def definir_code_secours(self, user_id, code):
        sel = secrets.token_hex(16)
        digest = hacher(code, sel)
        self.x("UPDATE utilisateurs SET code_secours_hash=? WHERE id=?", (sel + ":" + digest, user_id))

    def reinitialiser_mot_de_passe(self, nom, code, nouveau):
        r = self.q("SELECT * FROM utilisateurs WHERE nom=? AND actif=1", (nom.strip(),))
        if not r:
            return "Compte introuvable ou désactivé."
        u = r[0]
        try:
            sel_code, hash_code = u["code_secours_hash"].split(":", 1)
        except Exception:
            return "Aucun code de secours n'a été configuré pour ce compte."
        if not hmac.compare_digest(hacher(code, sel_code), hash_code):
            return "Code de secours incorrect."
        if len(nouveau) < 6:
            return "Le nouveau mot de passe doit contenir au moins 6 caractères."
        sel = secrets.token_hex(16)
        self.x("UPDATE utilisateurs SET sel=?,hash=?,echecs=0,bloque_jusqua='' WHERE id=?",
               (sel, hacher(nouveau, sel), u["id"]))
        return None

    def annuler_vente(self, facture, user):
        lignes = self.q("SELECT * FROM ventes WHERE facture=? AND annule=0", (facture,))
        if not lignes:
            return "Cette vente est introuvable ou déjà annulée."
        try:
            for v in lignes:
                if v["produit_id"] is not None:
                    self.con.execute("UPDATE produits SET stock=stock+? WHERE id=?", (v["qte"], v["produit_id"]))
                if v["credit"] and v["client"]:
                    self.con.execute("UPDATE clients SET dette=MAX(0,dette-?) WHERE nom=?", (v["total"], v["client"]))
            self.con.execute("UPDATE ventes SET annule=1 WHERE facture=?", (facture,))
            self.con.commit()
            self.log(user, "Annulation vente " + facture)
            return None
        except Exception as e:
            self.con.rollback()
            return str(e)

    def vendre_panier(self, panier, client, credit, user):
        if not panier:
            return "Le panier est vide.", None
        if credit and not client.strip():
            return "Le nom du client est obligatoire pour une vente à crédit.", None
        produits = {}
        for pid, qte in panier:
            if qte <= 0:
                return "Quantité invalide.", None
            r = self.q("SELECT * FROM produits WHERE id=?", (pid,))
            if not r:
                return "Produit introuvable.", None
            produits[pid] = r[0]
        totaux = {}
        for pid, qte in panier:
            totaux[pid] = totaux.get(pid, 0) + qte
        for pid, qte in totaux.items():
            if qte > produits[pid]["stock"]:
                return f"Stock insuffisant pour {produits[pid]['nom']}.", None
        numero = "NI-" + datetime.now().strftime("%y%m%d%H%M%S%f")
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        total_credit = 0
        try:
            for pid, qte in panier:
                p = produits[pid]
                total = qte * p["vente"]
                benef = qte * (p["vente"] - p["achat"])
                self.con.execute("UPDATE produits SET stock=stock-? WHERE id=?", (qte, pid))
                self.con.execute("""INSERT INTO ventes(date,facture,produit_id,produit,qte,prix,total,benefice,client,credit,utilisateur)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (now, numero, pid, p["nom"], qte, p["vente"], total, benef, client.strip(), int(credit), user))
                total_credit += total
            if credit:
                self.con.execute("INSERT OR IGNORE INTO clients(nom,dette) VALUES(?,0)", (client.strip(),))
                self.con.execute("UPDATE clients SET dette=dette+? WHERE nom=?", (total_credit, client.strip()))
            self.con.commit()
            self.log(user, "Vente panier " + numero)
            return None, numero
        except Exception as e:
            self.con.rollback()
            return "Erreur pendant la vente : " + str(e), None

    def creer_user(self, nom, mdp, role="vendeur"):
        nom = nom.strip()
        if len(nom) < 3 or len(mdp) < 6:
            return "Nom : 3 caractères minimum ; mot de passe : 6 minimum."
        sel = secrets.token_hex(16)
        try:
            self.x("INSERT INTO utilisateurs(nom,sel,hash,role) VALUES(?,?,?,?)",
                   (nom, sel, hacher(mdp, sel), role))
        except sqlite3.IntegrityError:
            return "Ce nom d'utilisateur existe déjà."
        return None

    def ajouter_produit(self, nom, achat, vente, stock, seuil):
        if not nom.strip() or min(achat, vente, stock, seuil) < 0 or vente <= 0:
            return "Vérifie les informations et les montants."
        try:
            self.x("INSERT INTO produits(nom,achat,vente,stock,seuil) VALUES(?,?,?,?,?)",
                   (nom.strip(), achat, vente, stock, seuil))
        except sqlite3.IntegrityError:
            return "Ce produit existe déjà. Modifie son stock depuis la liste."
        return None

    def modifier_prix(self, produit_id, achat, vente, user):
        """Met à jour les prix du catalogue sans modifier les anciennes ventes."""
        if achat < 0 or vente <= 0:
            return "Le prix d'achat ne peut pas être négatif et le prix de vente doit être supérieur à zéro."
        produit = self.q("SELECT nom FROM produits WHERE id=?", (produit_id,))
        if not produit:
            return "Produit introuvable."
        self.x("UPDATE produits SET achat=?, vente=? WHERE id=?", (achat, vente, produit_id))
        self.log(user, f"Modification des prix : {produit[0]['nom']} (achat {achat:g}, vente {vente:g})")
        return None

    def vendre(self, pid, qte, client, credit, user):
        if qte <= 0:
            return "La quantité doit être supérieure à zéro.", None
        p = self.q("SELECT * FROM produits WHERE id=?", (pid,))
        if not p:
            return "Produit introuvable.", None
        p = p[0]
        if qte > p["stock"]:
            return f"Stock insuffisant. Disponible : {p['stock']:g}", None
        if credit and not client.strip():
            return "Le nom du client est obligatoire pour une vente à crédit.", None
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        numero = "NI-" + datetime.now().strftime("%y%m%d%H%M%S")
        total = qte * p["vente"]
        benef = qte * (p["vente"] - p["achat"])
        try:
            self.con.execute("UPDATE produits SET stock=stock-? WHERE id=?", (qte, pid))
            self.con.execute("""INSERT INTO ventes
                (date,facture,produit_id,produit,qte,prix,total,benefice,client,credit,utilisateur)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (now, numero, pid, p["nom"], qte, p["vente"], total, benef,
                 client.strip(), int(credit), user))
            if credit:
                self.con.execute("INSERT OR IGNORE INTO clients(nom,dette) VALUES(?,0)",
                                 (client.strip(),))
                self.con.execute("UPDATE clients SET dette=dette+? WHERE nom=?",
                                 (total, client.strip()))
            self.con.commit()
            self.log(user, "Vente " + numero)
            return None, numero
        except Exception as e:
            self.con.rollback()
            return "Erreur pendant la vente : " + str(e), None

    def depenser(self, motif, somme, user):
        if not motif.strip() or somme <= 0:
            return "Saisis un motif et un montant valide."
        self.x("INSERT INTO depenses(date,motif,montant,utilisateur) VALUES(?,?,?,?)",
               (datetime.now().strftime("%Y-%m-%d %H:%M"), motif.strip(), somme, user))
        self.log(user, "Dépense enregistrée")
        return None

    def rembourser(self, client_id, somme, user):
        c = self.q("SELECT * FROM clients WHERE id=?", (client_id,))
        if not c:
            return "Client introuvable."
        dette = c[0]["dette"]
        if somme <= 0 or somme > dette:
            return f"Montant invalide. Dette actuelle : {montant(dette)}."
        try:
            self.con.execute("UPDATE clients SET dette=dette-? WHERE id=?", (somme, client_id))
            self.con.execute("INSERT INTO remboursements(date,client,montant,utilisateur) VALUES(?,?,?,?)",
                             (datetime.now().strftime("%Y-%m-%d %H:%M"), c[0]["nom"], somme, user))
            self.con.commit()
            self.log(user, "Remboursement client : " + c[0]["nom"])
            return None
        except Exception as e:
            self.con.rollback()
            return str(e)

    def resume(self):
        debut = datetime.now().strftime("%Y-%m-01")
        v = self.q("SELECT COALESCE(SUM(total),0) t, COALESCE(SUM(benefice),0) b FROM ventes WHERE date>=? AND annule=0", (debut,))[0]
        d = self.q("SELECT COALESCE(SUM(montant),0) m FROM depenses WHERE date>=?", (debut,))[0]["m"]
        dette = self.q("SELECT COALESCE(SUM(dette),0) m FROM clients")[0]["m"]
        stock = self.q("SELECT COUNT(*) n FROM produits")[0]["n"]
        return v["t"], v["b"], d, dette, stock

    CHAMPS_ENTREPRISE = {
        "raison_sociale": "Raison sociale",
        "nom_magasin": "Nom commercial / magasin",
        "adresse": "Adresse",
        "ville": "Ville / commune",
        "telephone": "Téléphone",
        "email": "E-mail",
        "rccm": "RCCM",
        "id_nat": "ID. Nationale",
        "nif": "NIF",
        "numero_impot": "Numéro d'impôt",
    }

    def entreprise(self):
        donnees = {r["cle"]: r["valeur"] for r in self.q("SELECT cle,valeur FROM entreprise")}
        for cle in ("raison_sociale", "nom_magasin", "adresse", "ville", "telephone", "email", "rccm", "id_nat", "nif", "numero_impot"):
            donnees.setdefault(cle, "")
        return donnees

    def enregistrer_entreprise(self, donnees):
        requis = ("raison_sociale", "nom_magasin", "adresse")
        if any(not donnees.get(k, "").strip() for k in requis):
            return "La raison sociale, le nom du magasin et l'adresse sont obligatoires."
        try:
            for cle in ("raison_sociale", "nom_magasin", "adresse", "ville", "telephone", "email", "rccm", "id_nat", "nif", "numero_impot"):
                self.x("INSERT INTO entreprise(cle,valeur) VALUES(?,?) ON CONFLICT(cle) DO UPDATE SET valeur=excluded.valeur",
                       (cle, donnees.get(cle, "").strip()))
            return None
        except Exception as e:
            return str(e)

    def sauvegarder(self, dossier):
        os.makedirs(dossier, exist_ok=True)
        self.con.commit()
        dest = os.path.join(dossier, "NI_BUSINESS_backup_" +
                            datetime.now().strftime("%Y%m%d_%H%M%S") + ".db")
        shutil.copy2(self.con.execute("PRAGMA database_list").fetchone()[2], dest)
        return dest


class NIApp(App):
    title = "N.I BUSINESS"

    def build(self):
        Window.clearcolor = FOND
        Window.softinput_mode = "below_target"
        self.db = Base(os.path.join(self.user_data_dir, "ni_business.db"))
        self.user = None
        self.derniere_activite = datetime.now()
        Window.bind(on_touch_down=self._activite)
        Clock.schedule_interval(self._verifier_inactivite, 30)
        self.root_box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(12))
        self.afficher_demarrage()
        return self.root_box

    def label(self, texte, taille=15, couleur=BLANC, hauteur=dp(38), gras=False):
        lbl = Label(text=str(texte), font_size=sp(taille), color=couleur,
                    size_hint_y=None, height=hauteur, bold=gras,
                    halign="left", valign="middle")
        # Permet au texte long de revenir automatiquement à la ligne.
        lbl.bind(width=lambda instance, value: setattr(instance, "text_size", (value, None)))
        lbl.text_size = (Window.width - dp(30), None)
        return lbl

    def bouton(self, texte, action, couleur=BLEU, hauteur=dp(46)):
        b = Button(text=texte, size_hint_y=None, height=hauteur,
                   background_normal="", background_color=couleur,
                   color=BLANC, font_size=sp(14))
        b.bind(on_release=lambda *_: action())
        return b

    def champ(self, hint, password=False, multiline=False):
        return TextInput(hint_text=hint, password=password, multiline=multiline,
                         size_hint_y=None, height=dp(46), font_size=sp(15),
                         padding=(dp(10), dp(10)))

    def vider(self):
        self.root_box.clear_widgets()

    def popup(self, titre, message):
        contenu = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(10))
        texte = Label(text=str(message), color=BLANC, halign="left", valign="middle")
        texte.bind(width=lambda instance, value: setattr(instance, "text_size", (value, None)))
        contenu.add_widget(texte)
        b = Button(text="Fermer", size_hint_y=None, height=dp(44))
        contenu.add_widget(b)
        p = Popup(title=titre, content=contenu, size_hint=(.88,.42))
        b.bind(on_release=p.dismiss)
        p.open()

    def zone_scroll(self):
        s = ScrollView()
        g = GridLayout(cols=1, spacing=dp(7), size_hint_y=None, padding=(0,0,0,dp(8)))
        g.bind(minimum_height=g.setter("height"))
        s.add_widget(g)
        return s, g

    def afficher_demarrage(self):
        self.vider()
        self.root_box.add_widget(self.label("N.I BUSINESS", 28, OR, dp(55), True))
        self.root_box.add_widget(self.label("Gestion commerciale • Hors connexion", 13, GRIS))
        users = self.db.q("SELECT COUNT(*) n FROM utilisateurs")[0]["n"]
        if users == 0:
            self.root_box.add_widget(self.label("Créer le compte propriétaire", 19, BLANC))
            nom = self.champ("Nom d'utilisateur (min. 3 caractères)")
            mdp = self.champ("Mot de passe (min. 6 caractères)", True)
            confirm = self.champ("Confirmer le mot de passe", True)
            self.root_box.add_widget(nom)
            self.root_box.add_widget(mdp)
            self.root_box.add_widget(confirm)
            def creer():
                if mdp.text != confirm.text:
                    self.popup("Erreur", "Les deux mots de passe ne correspondent pas.")
                    return
                err = self.db.creer_user(nom.text, mdp.text, "admin")
                if err:
                    self.popup("Erreur", err)
                else:
                    code = secrets.token_hex(4).upper()
                    uid = self.db.q("SELECT id FROM utilisateurs WHERE nom=?", (nom.text.strip(),))[0]["id"]
                    self.db.definir_code_secours(uid, code)
                    self.db.log(nom.text.strip(), "Création du compte propriétaire")
                    self.user = {"nom": nom.text.strip(), "role": "admin", "id": uid}
                    self.popup("Code de secours à conserver", "Note ce code et garde-le en lieu sûr :\n\n" + code + "\n\nIl sera nécessaire pour réinitialiser le mot de passe.")
                    self.page_entreprise()
            self.root_box.add_widget(self.bouton("CRÉER MON COMPTE", creer, VERT))
        else:
            self.root_box.add_widget(self.label("Connexion", 20, BLANC))
            nom = self.champ("Nom d'utilisateur")
            mdp = self.champ("Mot de passe", True)
            self.root_box.add_widget(nom)
            self.root_box.add_widget(mdp)
            def connecter():
                u = self.db.authentifier(nom.text, mdp.text)
                if u == "BLOQUE":
                    self.popup("Connexion bloquée", "Trop de tentatives ou compte temporairement verrouillé. Réessaie dans 5 minutes.")
                    return
                if not u:
                    self.popup("Connexion refusée", "Nom ou mot de passe incorrect, ou compte désactivé.")
                    return
                self.user = u
                self.db.log(u["nom"], "Connexion")
                profil = self.db.entreprise()
                if u["role"] == "admin" and not profil.get("raison_sociale", "").strip():
                    self.page_entreprise()
                else:
                    self.accueil()
            self.root_box.add_widget(self.bouton("SE CONNECTER", connecter, VERT))
            self.root_box.add_widget(self.bouton("MOT DE PASSE OUBLIÉ ?", self.page_recuperation, MARINE))

    def entete(self, titre):
        self.root_box.add_widget(self.label("N.I BUSINESS  •  " + titre, 19, OR, dp(42), True))

    def menu(self):
        bar = GridLayout(cols=2, spacing=dp(6), size_hint_y=None)
        bar.bind(minimum_height=bar.setter("height"))
        items = [("Accueil", self.accueil), ("Produits / Stock", self.page_produits),
                 ("Nouvelle vente", self.page_vente), ("Historique", self.page_historique)]
        if self.user["role"] == "admin":
            items += [("Dépenses", self.page_depense), ("Clients / Dettes", self.page_clients),
                      ("Utilisateurs", self.page_users), ("Mon magasin", self.page_entreprise),
                      ("Sauvegarde", self.page_backup), ("Rapports PDF", self.page_rapports)]
        for titre, fn in items:
            bar.add_widget(self.bouton(titre, fn, MARINE, dp(42)))
        bar.add_widget(self.bouton("Déconnexion", self.deconnexion, ROUGE, dp(42)))
        self.root_box.add_widget(bar)

    def page_base(self, titre):
        self.vider()
        self.entete(titre)
        self.menu()
        return self.zone_scroll()

    def accueil(self):
        s, g = self.page_base("TABLEAU DE BORD")
        ventes, benef, dep, dette, nb = self.db.resume()
        infos = ["Bonjour " + self.user["nom"], "Ventes du mois : " + montant(ventes),
                 "Produits enregistrés : " + str(nb),
                 "Date : " + datetime.now().strftime("%d/%m/%Y %H:%M")]
        if self.user["role"] == "admin":
            infos[2:2] = ["Bénéfice brut estimé : " + montant(benef),
                          "Dépenses du mois : " + montant(dep),
                          "Bénéfice après dépenses : " + montant(benef-dep),
                          "Dettes clients restantes : " + montant(dette)]
        for t in infos:
            g.add_widget(self.label(t, 16, BLANC, dp(44), t.startswith("Ventes")))
        self.root_box.add_widget(s)

    def page_produits(self):
        s, g = self.page_base("PRODUITS ET STOCK")
        nom = self.champ("Nom du produit")
        achat = self.champ("Prix d'achat (FC)")
        vente = self.champ("Prix de vente (FC)")
        stock = self.champ("Quantité en stock")
        seuil = self.champ("Seuil d'alerte (ex. 5)")
        for w in (nom, achat, vente, stock, seuil):
            g.add_widget(w)
        def ajouter():
            vals = [nombre(x.text) for x in (achat, vente, stock, seuil)]
            if any(x is None for x in vals):
                self.popup("Erreur", "Entre des nombres valides dans les champs.")
                return
            err = self.db.ajouter_produit(nom.text, *vals)
            if err:
                self.popup("Erreur", err)
            else:
                self.db.log(self.user["nom"], "Ajout produit : " + nom.text.strip())
                self.popup("Succès", "Produit enregistré.")
                self.page_produits()
        g.add_widget(self.bouton("ENREGISTRER LE PRODUIT", ajouter, VERT))
        g.add_widget(self.label("Produits enregistrés", 17, OR, dp(40), True))
        for p in self.db.q("SELECT * FROM produits ORDER BY nom"):
            alerte = "  ⚠ STOCK BAS" if p["stock"] <= p["seuil"] else ""
            ligne = f'{p["nom"]} | Stock : {p["stock"]:g}{alerte}\nAchat : {montant(p["achat"])}  •  Vente : {montant(p["vente"])}'
            g.add_widget(self.label(ligne, 13, OR if alerte else BLANC, dp(62)))
            if self.user["role"] == "admin":
                g.add_widget(self.bouton(
                    "MODIFIER LES PRIX D'ACHAT / DE VENTE",
                    lambda prod=dict(p): self.popup_modifier_prix(prod),
                    MARINE, dp(38)
                ))
            qte = self.champ("Ajouter une quantité au stock")
            g.add_widget(qte)
            def appro(pid=p["id"], champ=qte):
                n = nombre(champ.text)
                if n is None or n <= 0:
                    self.popup("Erreur", "Quantité invalide.")
                    return
                self.db.x("UPDATE produits SET stock=stock+? WHERE id=?", (n,pid))
                self.db.log(self.user["nom"], "Réapprovisionnement produit")
                self.page_produits()
            g.add_widget(self.bouton("AJOUTER AU STOCK", appro, BLEU, dp(38)))
        self.root_box.add_widget(s)

    def popup_modifier_prix(self, produit):
        contenu = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        contenu.add_widget(self.label("Produit : " + produit["nom"], 15, OR, dp(38), True))
        achat = self.champ("Nouveau prix d'achat en FC")
        vente = self.champ("Nouveau prix de vente en FC")
        achat.text = str(produit["achat"])
        vente.text = str(produit["vente"])
        contenu.add_widget(achat)
        contenu.add_widget(vente)
        boutons = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        enregistrer = Button(text="Enregistrer", background_color=VERT)
        annuler = Button(text="Annuler")
        boutons.add_widget(enregistrer)
        boutons.add_widget(annuler)
        contenu.add_widget(boutons)
        pop = Popup(title="Modifier les prix", content=contenu, size_hint=(.92, .48))

        def sauver(*_):
            a, v = nombre(achat.text), nombre(vente.text)
            if a is None or v is None:
                self.popup("Erreur", "Entre deux montants valides.")
                return
            erreur = self.db.modifier_prix(produit["id"], a, v, self.user["nom"])
            if erreur:
                self.popup("Erreur", erreur)
                return
            pop.dismiss()
            self.popup("Prix modifiés", "Les nouveaux prix seront utilisés pour les prochaines ventes. Les anciennes factures et leurs prix restent inchangés.")
            self.page_produits()

        enregistrer.bind(on_release=sauver)
        annuler.bind(on_release=pop.dismiss)
        pop.open()

    def page_vente(self):
        s, g = self.page_base("NOUVELLE VENTE - PANIER")
        produits = self.db.q("SELECT * FROM produits ORDER BY nom COLLATE NOCASE")
        if not produits:
            g.add_widget(self.label("Ajoute d'abord un produit dans Produits / Stock.", 15))
            self.root_box.add_widget(s)
            return

        # Recherche instantanée : le vendeur peut retrouver un article par son nom.
        recherche = self.champ("Rechercher un produit par son nom...")
        selection = {"produit": None}
        panier = []  # Chaque produit n'apparaît qu'une fois ; sa quantité est cumulée.
        qte = self.champ("Quantité à vendre")
        zone_panier = self.label("Panier vide", 13, GRIS, dp(100))
        total_panier = self.label("Total : 0 FC", 16, OR, dp(40), True)
        client = self.champ("Nom du client (facultatif, affiché sur la facture)")
        credit = CheckBox(size_hint=(None, None), size=(dp(48), dp(48)))
        row = BoxLayout(size_hint_y=None, height=dp(48))
        row.add_widget(self.label("Vente à crédit ?", 15))
        row.add_widget(credit)

        liste_scroll = ScrollView(size_hint_y=None, height=dp(180))
        liste = GridLayout(cols=1, spacing=dp(4), size_hint_y=None)
        liste.bind(minimum_height=liste.setter("height"))
        liste_scroll.add_widget(liste)

        produit_selectionne = self.label("Aucun produit sélectionné", 14, OR, dp(42), True)
        g.add_widget(recherche)
        g.add_widget(self.label("Résultats — touche un produit pour le sélectionner", 13, GRIS, dp(30)))
        g.add_widget(liste_scroll)
        g.add_widget(produit_selectionne)
        g.add_widget(qte)

        def choisir(prod):
            selection["produit"] = prod
            produit_selectionne.text = (
                f'{prod["nom"]} | Stock : {prod["stock"]:g} | '
                f'Prix : {montant(prod["vente"])}'
            )

        def afficher_resultats(texte=""):
            liste.clear_widgets()
            terme = texte.strip().casefold()
            trouves = [p for p in produits if terme in p["nom"].casefold()]
            if not trouves:
                liste.add_widget(self.label("Aucun produit correspondant.", 13, GRIS, dp(40)))
                return
            for prod in trouves:
                libelle = f'{prod["nom"]}  •  Stock: {prod["stock"]:g}  •  {montant(prod["vente"])}'
                bouton = self.bouton(libelle, lambda p=prod: choisir(p), MARINE, dp(42))
                liste.add_widget(bouton)

        recherche.bind(text=lambda _champ, valeur: afficher_resultats(valeur))
        afficher_resultats()

        def afficher_panier():
            lignes = []
            total = 0
            for pid, quantite in panier:
                prod = next((x for x in produits if x["id"] == pid), None)
                if prod is None:
                    continue
                sous_total = quantite * prod["vente"]
                total += sous_total
                lignes.append(f'{prod["nom"]}  x {quantite:g}  =  {montant(sous_total)}')
            zone_panier.text = "\n".join(lignes) if lignes else "Panier vide"
            total_panier.text = "Total : " + montant(total)

        def ajouter():
            prod = selection["produit"]
            if prod is None:
                self.popup("Produit manquant", "Recherche puis sélectionne un produit dans la liste.")
                return
            n = nombre(qte.text)
            if n is None or n <= 0:
                self.popup("Erreur", "Entre une quantité valide supérieure à zéro.")
                return
            deja = sum(v for pid, v in panier if pid == prod["id"])
            if n + deja > prod["stock"]:
                self.popup("Stock insuffisant", f'Stock disponible pour {prod["nom"]} : {prod["stock"]:g}')
                return
            trouve = False
            for i, (pid, quantite) in enumerate(panier):
                if pid == prod["id"]:
                    panier[i] = (pid, quantite + n)
                    trouve = True
                    break
            if not trouve:
                panier.append((prod["id"], n))
            afficher_panier()
            qte.text = ""
            selection["produit"] = None
            produit_selectionne.text = "Aucun produit sélectionné"

        def retirer_dernier():
            if panier:
                panier.pop()
                afficher_panier()

        g.add_widget(self.bouton("AJOUTER AU PANIER", ajouter, MARINE))
        g.add_widget(self.label("Détail du panier", 16, OR, dp(35), True))
        g.add_widget(zone_panier)
        g.add_widget(total_panier)
        g.add_widget(self.bouton("RETIRER LE DERNIER PRODUIT", retirer_dernier, ROUGE, dp(40)))
        g.add_widget(client)
        g.add_widget(row)

        def valider():
            if not panier:
                self.popup("Panier vide", "Ajoute au moins un produit avant de valider la vente.")
                return
            err, facture = self.db.vendre_panier(panier, client.text, credit.active, self.user["nom"])
            if err:
                self.popup("Vente impossible", err)
            else:
                self.popup("Vente enregistrée", "Facture : " + facture + "\nTous les produits du panier ont été enregistrés sur la même facture.")
                self.generer_facture(facture)

        g.add_widget(self.bouton("VALIDER LA VENTE", valider, VERT))
        self.root_box.add_widget(s)

    def page_depense(self):
        if self.user["role"] != "admin": self.popup("Accès refusé", "Réservé au propriétaire."); return
        s, g = self.page_base("DÉPENSES")
        motif = self.champ("Motif de la dépense")
        somme = self.champ("Montant en FC")
        g.add_widget(motif); g.add_widget(somme)
        def enregistrer():
            n = nombre(somme.text)
            if n is None:
                self.popup("Erreur", "Montant invalide.")
                return
            err = self.db.depenser(motif.text, n, self.user["nom"])
            if err:
                self.popup("Erreur", err)
            else:
                self.popup("Succès", "Dépense enregistrée.")
                self.accueil()
        g.add_widget(self.bouton("ENREGISTRER LA DÉPENSE", enregistrer, VERT))
        g.add_widget(self.label("Dépenses récentes", 17, OR, dp(40), True))
        for d in self.db.q("SELECT * FROM depenses ORDER BY id DESC LIMIT 30"):
            g.add_widget(self.label(f'{d["date"]} • {d["motif"]} • {montant(d["montant"])}', 13, BLANC, dp(42)))
        self.root_box.add_widget(s)

    def page_clients(self):
        if self.user["role"] != "admin": self.popup("Accès refusé", "Réservé au propriétaire."); return
        s, g = self.page_base("CLIENTS ET DETTES")
        clients = self.db.q("SELECT * FROM clients ORDER BY nom")
        if not clients:
            g.add_widget(self.label("Aucun client à crédit pour le moment.", 15))
        for c in clients:
            g.add_widget(self.label(f'{c["nom"]}  |  Dette : {montant(c["dette"])}', 15, OR if c["dette"]>0 else BLANC, dp(42), True))
            if c["dette"] > 0:
                inp = self.champ("Montant remboursé en FC")
                g.add_widget(inp)
                def payer(cid=c["id"], champ=inp):
                    n = nombre(champ.text)
                    if n is None:
                        self.popup("Erreur", "Montant invalide.")
                        return
                    err = self.db.rembourser(cid, n, self.user["nom"])
                    if err:
                        self.popup("Erreur", err)
                    else:
                        self.popup("Succès", "Remboursement enregistré.")
                        self.page_clients()
                g.add_widget(self.bouton("ENREGISTRER LE REMBOURSEMENT", payer, VERT, dp(38)))
        self.root_box.add_widget(s)

    def page_historique(self):
        s, g = self.page_base("HISTORIQUE DES VENTES")
        factures = self.db.q("SELECT facture,MIN(date) date,SUM(total) total,MAX(annule) annule FROM ventes GROUP BY facture ORDER BY MIN(id) DESC LIMIT 100")
        for v in factures:
            statut = "ANNULÉE" if v["annule"] else "VALIDÉE"
            g.add_widget(self.label(f'{v["date"]} • {v["facture"]}\nTotal : {montant(v["total"])} • {statut}', 13, ROUGE if v["annule"] else BLANC, dp(55)))
            g.add_widget(self.bouton("VOIR / PDF FACTURE", lambda f=v["facture"]: self.generer_facture(f), MARINE, dp(36)))
            if self.user["role"] == "admin" and not v["annule"]:
                g.add_widget(self.bouton("ANNULER CETTE VENTE", lambda f=v["facture"]: self.confirmer_annulation(f), ROUGE, dp(36)))
        self.root_box.add_widget(s)

    def page_entreprise(self):
        """Profil commercial utilisé sur les factures de cette installation."""
        if self.user["role"] != "admin":
            self.popup("Accès refusé", "Seul le propriétaire peut modifier les informations du magasin.")
            return
        s, g = self.page_base("IDENTITÉ DE MON MAGASIN")
        g.add_widget(self.label("Ces informations apparaîtront sur les factures PDF. Chaque commerçant configure sa propre entreprise.", 13, GRIS, dp(64)))
        profil = self.db.entreprise()
        champs = [
            ("raison_sociale", "Raison sociale *"),
            ("nom_magasin", "Nom commercial / nom du magasin *"),
            ("adresse", "Adresse complète *"),
            ("ville", "Ville / commune"),
            ("telephone", "Téléphone"),
            ("email", "Adresse e-mail"),
            ("rccm", "RCCM"),
            ("id_nat", "Numéro d'identification nationale (ID. NAT)"),
            ("nif", "NIF"),
            ("numero_impot", "Numéro d'impôt"),
        ]
        inputs = {}
        for cle, hint in champs:
            inp = self.champ(hint)
            inp.text = profil.get(cle, "")
            inputs[cle] = inp
            g.add_widget(inp)
        g.add_widget(self.label("* Champs obligatoires. N'inscris que les numéros officiels réellement attribués à ton établissement.", 12, OR, dp(52)))
        def sauver():
            donnees = {k: v.text for k, v in inputs.items()}
            err = self.db.enregistrer_entreprise(donnees)
            if err:
                self.popup("Informations incomplètes", err)
                return
            self.db.log(self.user["nom"], "Mise à jour des informations du magasin")
            self.popup("Profil enregistré", "Les informations du magasin seront désormais imprimées sur les prochaines factures.")
            self.accueil()
        g.add_widget(self.bouton("ENREGISTRER LES INFORMATIONS", sauver, VERT))
        self.root_box.add_widget(s)

    def page_users(self):
        if self.user["role"] != "admin":
            self.popup("Accès refusé", "Réservé au propriétaire.")
            return
        s, g = self.page_base("UTILISATEURS")
        nom = self.champ("Nom du vendeur")
        mdp = self.champ("Mot de passe temporaire (6 caractères min.)", True)
        g.add_widget(nom); g.add_widget(mdp)
        def creer():
            err = self.db.creer_user(nom.text, mdp.text, "vendeur")
            if err:
                self.popup("Erreur", err)
            else:
                self.db.log(self.user["nom"], "Création utilisateur " + nom.text.strip())
                self.popup("Succès", "Compte vendeur créé.")
                self.page_users()
        g.add_widget(self.bouton("CRÉER UN COMPTE VENDEUR", creer, VERT))
        g.add_widget(self.label("Comptes existants", 17, OR, dp(40), True))
        for u in self.db.q("SELECT id,nom,role,actif FROM utilisateurs ORDER BY nom"):
            g.add_widget(self.label(f'{u["nom"]} • {u["role"]} • {"Actif" if u["actif"] else "Désactivé"}', 14, BLANC, dp(38)))
            if u["id"] != self.user.get("id"):
                g.add_widget(self.bouton("DÉSACTIVER" if u["actif"] else "RÉACTIVER",
                    lambda uid=u["id"], etat=u["actif"]: self.changer_statut_user(uid, etat), ROUGE if u["actif"] else VERT, dp(34)))
        self.root_box.add_widget(s)

    def page_recuperation(self):
        self.vider()
        self.entete("RÉINITIALISATION DU MOT DE PASSE")
        nom = self.champ("Nom d'utilisateur")
        code = self.champ("Code de secours")
        nouveau = self.champ("Nouveau mot de passe", True)
        for w in (nom, code, nouveau): self.root_box.add_widget(w)
        def reset():
            err = self.db.reinitialiser_mot_de_passe(nom.text, code.text, nouveau.text)
            self.popup("Erreur" if err else "Succès", err or "Mot de passe modifié. Tu peux maintenant te connecter.")
            if not err: self.afficher_demarrage()
        self.root_box.add_widget(self.bouton("RÉINITIALISER", reset, VERT))
        self.root_box.add_widget(self.bouton("RETOUR", self.afficher_demarrage, MARINE))

    def changer_statut_user(self, uid, actif):
        self.db.x("UPDATE utilisateurs SET actif=? WHERE id=?", (0 if actif else 1, uid))
        self.db.log(self.user["nom"], "Modification statut utilisateur")
        self.page_users()

    def confirmer_annulation(self, facture):
        contenu = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        contenu.add_widget(self.label("Cette opération restaure le stock et retire la dette client correspondante. Continuer ?", 14, BLANC, dp(75)))
        ligne = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        pop = Popup(title="Confirmer l'annulation", content=contenu, size_hint=(.9,.38))
        oui = Button(text="Oui, annuler", background_color=ROUGE)
        non = Button(text="Retour")
        ligne.add_widget(oui); ligne.add_widget(non); contenu.add_widget(ligne)
        oui.bind(on_release=lambda *_: (pop.dismiss(), self._annuler(facture)))
        non.bind(on_release=pop.dismiss); pop.open()

    def _annuler(self, facture):
        err = self.db.annuler_vente(facture, self.user["nom"])
        self.popup("Erreur" if err else "Vente annulée", err or "Stock et dette mis à jour.")
        self.page_historique()

    def dossier_factures_public(self):
        """Dossier visible dans le stockage partagé du téléphone."""
        if platform == "android":
            racine = "/storage/emulated/0/Download"
        else:
            racine = os.path.join(os.path.expanduser("~"), "Downloads")
        dossier = os.path.join(racine, "NI BUSINESS", "Factures")
        os.makedirs(dossier, exist_ok=True)
        return dossier

    def partager_pdf(self, chemin):
        """Ouvre le menu Android de partage pour envoyer le PDF."""
        if platform != "android":
            self.popup("Facture enregistrée", "PDF :\n" + chemin)
            return
        try:
            from jnius import autoclass
            PythonActivity = autoclass('org.kivy.android.PythonActivity')
            Intent = autoclass('android.content.Intent')
            Uri = autoclass('android.net.Uri')
            StrictMode = autoclass('android.os.StrictMode')
            Builder = autoclass('android.os.StrictMode$VmPolicy$Builder')
            StrictMode.setVmPolicy(Builder().build())
            uri = Uri.fromFile(autoclass('java.io.File')(chemin))
            intent = Intent(Intent.ACTION_SEND)
            intent.setType('application/pdf')
            intent.putExtra(Intent.EXTRA_STREAM, uri)
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            chooser = Intent.createChooser(intent, 'Partager la facture PDF')
            PythonActivity.mActivity.startActivity(chooser)
        except Exception as e:
            self.popup("PDF enregistré", "Le fichier est dans :\n" + chemin + "\n\nPartage Android indisponible : " + str(e))

    def generer_facture(self, facture):
        lignes = self.db.q("SELECT * FROM ventes WHERE facture=? ORDER BY id", (facture,))
        if not lignes: return
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            dossier = self.dossier_factures_public()
            chemin = os.path.join(dossier, facture + ".pdf")
            c = canvas.Canvas(chemin, pagesize=A4)
            profil = self.db.entreprise()
            c.setFont("Helvetica-Bold", 17)
            c.drawString(45, 805, (profil.get("nom_magasin") or "N.I BUSINESS")[:48])
            c.setFont("Helvetica-Bold", 10)
            c.drawString(45, 787, (profil.get("raison_sociale") or "")[:90])
            c.setFont("Helvetica", 9)
            y_info = 771
            for cle in ("adresse", "ville", "telephone", "email", "rccm", "id_nat", "nif", "numero_impot"):
                valeur = profil.get(cle, "").strip()
                if valeur:
                    libelle = {"adresse":"Adresse", "ville":"Ville", "telephone":"Tél.", "email":"E-mail", "rccm":"RCCM", "id_nat":"ID. NAT", "nif":"NIF", "numero_impot":"N° impôt"}[cle]
                    c.drawString(45, y_info, f"{libelle} : {valeur[:100]}")
                    y_info -= 13
            y_info -= 8
            c.setFont("Helvetica-Bold", 15)
            c.drawString(45, y_info, "FACTURE")
            c.setFont("Helvetica", 10)
            c.drawString(45, y_info-18, "Numéro : " + facture)
            date_facture = lignes[0]["date"] or datetime.now().strftime("%Y-%m-%d %H:%M")
            try:
                date_affichee = datetime.strptime(date_facture, "%Y-%m-%d %H:%M").strftime("%d/%m/%Y à %H:%M")
            except Exception:
                date_affichee = date_facture
            c.drawString(300, y_info-18, "Date : " + date_affichee)
            nom_client = (lignes[0]["client"] or "").strip()
            c.setFont("Helvetica-Bold", 10)
            c.drawString(45, y_info-36, "Client : " + (nom_client[:70] if nom_client else "Client de passage"))
            y = y_info - 66
            c.setFont("Helvetica-Bold", 10)
            c.drawString(45,y,"Produit"); c.drawString(300,y,"Qté"); c.drawString(370,y,"Prix unit."); c.drawString(470,y,"Total")
            y -= 20; total = 0
            c.setFont("Helvetica", 10)
            for x in lignes:
                if y < 70:
                    c.showPage(); y = 780
                    c.setFont("Helvetica-Bold", 10)
                    c.drawString(45,y,"Produit"); c.drawString(300,y,"Qté"); c.drawString(370,y,"Prix unit."); c.drawString(470,y,"Total")
                    y -= 20; c.setFont("Helvetica", 10)
                c.drawString(45,y,str(x["produit"])[:38]); c.drawRightString(335,y,f'{x["qte"]:g}')
                c.drawRightString(440,y,f'{x["prix"]:,.0f} FC'); c.drawRightString(550,y,f'{x["total"]:,.0f} FC')
                total += x["total"]; y -= 18
            c.setFont("Helvetica-Bold", 12); c.drawRightString(550,max(45,y-15),f'TOTAL : {total:,.0f} FC')
            c.save()
            contenu = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(12))
            contenu.add_widget(self.label("Facture enregistrée automatiquement dans :\n" + chemin, 13, BLANC, dp(90)))
            contenu.add_widget(self.bouton("PARTAGER LA FACTURE", lambda: (pop.dismiss(), self.partager_pdf(chemin)), VERT))
            contenu.add_widget(self.bouton("FERMER", lambda: pop.dismiss(), MARINE))
            pop = Popup(title="FACTURE PDF CRÉÉE", content=contenu, size_hint=(0.92, None), height=dp(250))
            pop.open()
        except ImportError:
            self.popup("Installation nécessaire - ReportLab", "Le module ReportLab sert à créer les factures PDF.\n\nDans Pydroid 3 : ouvre le menu latéral, choisis Pip, recherche reportlab, puis appuie sur Install.\n\nTu peux aussi utiliser le terminal et exécuter : pip install reportlab\n\nFerme puis relance N.I BUSINESS après l'installation.")
        except Exception as e: self.popup("Erreur PDF", str(e))

    def page_rapports(self):
        s, g = self.page_base("RAPPORTS PDF")
        g.add_widget(self.label("Générer un rapport simple des ventes et dépenses du mois.", 14, BLANC, dp(55)))
        def rapport():
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.pdfgen import canvas
                dossier = os.path.join(self.user_data_dir, "NI_BUSINESS", "rapports")
                os.makedirs(dossier, exist_ok=True)
                chemin = os.path.join(dossier, "rapport_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".pdf")
                ventes, benef, dep, dette, nb = self.db.resume()
                c = canvas.Canvas(chemin, pagesize=A4); c.setFont("Helvetica-Bold", 18)
                c.drawString(45,800,"N.I BUSINESS - RAPPORT MENSUEL")
                c.setFont("Helvetica",12); y=760
                for ligne in ["Date : " + datetime.now().strftime("%d/%m/%Y"), "Ventes : " + montant(ventes), "Bénéfice brut : " + montant(benef), "Dépenses : " + montant(dep), "Bénéfice après dépenses : " + montant(benef-dep), "Dettes clients : " + montant(dette)]:
                    c.drawString(45,y,ligne); y-=28
                c.save(); self.popup("Rapport créé", "Enregistré dans :\n" + chemin)
            except ImportError: self.popup("Installation nécessaire - ReportLab", "Pour générer les rapports PDF, ouvre Pydroid 3 > menu > Pip, recherche reportlab et appuie sur Install. Autre méthode : pip install reportlab dans le terminal. Puis relance N.I BUSINESS.")
            except Exception as e: self.popup("Erreur", str(e))
        g.add_widget(self.bouton("GÉNÉRER LE RAPPORT PDF", rapport, VERT))
        self.root_box.add_widget(s)

    def page_backup(self):
        if self.user["role"] != "admin":
            return
        s, g = self.page_base("SAUVEGARDE")
        g.add_widget(self.label("La sauvegarde crée une copie de la base de données dans le dossier privé de l'application.", 14, BLANC, dp(70)))
        def faire():
            try:
                # Dossier visible dans le stockage du téléphone sur Android.
                if platform == "android":
                    dossier = "/storage/emulated/0/NI_BUSINESS/sauvegardes"
                else:
                    dossier = os.path.join(self.user_data_dir, "NI_BUSINESS", "sauvegardes")
                try:
                    dest = self.db.sauvegarder(dossier)
                except (PermissionError, OSError):
                    # Repli sûr si Android refuse l'accès au stockage partagé.
                    dossier = os.path.join(self.user_data_dir, "NI_BUSINESS", "sauvegardes")
                    dest = self.db.sauvegarder(dossier)
                self.popup("Sauvegarde terminée", "Copie créée dans :\n" + dest)
            except Exception as e:
                self.popup("Erreur", str(e))
        g.add_widget(self.bouton("CRÉER UNE SAUVEGARDE", faire, VERT))
        self.root_box.add_widget(s)

    def _activite(self, *_):
        self.derniere_activite = datetime.now()

    def _verifier_inactivite(self, *_):
        if self.user and (datetime.now()-self.derniere_activite).total_seconds() >= 600:
            self.db.log(self.user["nom"], "Déconnexion automatique après inactivité")
            self.user = None
            self.afficher_demarrage()
            self.popup("Session expirée", "Déconnexion automatique après 10 minutes d'inactivité.")

    def deconnexion(self):
        self.db.log(self.user["nom"], "Déconnexion")
        self.user = None
        self.afficher_demarrage()

    def on_stop(self):
        try:
            self.db.con.commit()
            self.db.con.close()
        except Exception:
            pass


if __name__ == "__main__":
    NIApp().run()
