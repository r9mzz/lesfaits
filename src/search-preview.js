/* Les Faits — prévisualisation de la recherche dans le header.
 *
 * Le champ n'offrait que « Entrée → page de résultats » : aucun retour avant
 * de quitter la page, donc aucun moyen de savoir si le sujet existe. Ce
 * gestionnaire affiche les meilleures correspondances sous le champ, à la
 * frappe, sans rien casser du comportement existant (Entrée reste la sortie
 * vers /recherche.html, seul un choix explicite dans la liste le remplace).
 *
 * Contraintes : aucune dépendance, CSP 'self' (fetch de /data/search.json
 * uniquement), index chargé une seule fois et à la première interaction —
 * pas au chargement de page, pour ne pas peser sur le rendu initial.
 */
(function () {
  "use strict";

  var MAX = 6;
  var index = null;
  var chargement = null;

  /* Retire les diacritiques par code point plutôt que par classe de caractères
   * littérale : la plage combinante U+0300–U+036F écrite en clair dans le
   * source survit mal aux ré-encodages d'éditeur, et sa corruption casserait
   * silencieusement toute recherche accentuée. */
  function sansAccents(s) {
    var n = (s || "").toLowerCase().normalize("NFD");
    var out = "";
    for (var i = 0; i < n.length; i++) {
      var c = n.charCodeAt(i);
      if (c < 0x300 || c > 0x36f) out += n.charAt(i);
    }
    return out;
  }

  function base() {
    var b = document.querySelector("base");
    return b ? b.href : "/";
  }

  function chargerIndex() {
    if (index) return Promise.resolve(index);
    if (chargement) return chargement;
    chargement = fetch(base() + "data/search.json", { credentials: "omit" })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (d) { index = Array.isArray(d) ? d : []; return index; })
      .catch(function () { index = []; return index; });
    return chargement;
  }

  /* Titre d'abord, extrait ensuite : chercher « ebola » doit remonter la
   * brève intitulée Ebola avant un article qui la mentionne en passant. */
  function chercher(q) {
    var termes = sansAccents(q).split(/\s+/).filter(Boolean);
    if (!termes.length) return [];
    var out = [];
    for (var i = 0; i < index.length; i++) {
      var a = index[i];
      var titre = sansAccents(a.titre);
      var corps = titre + " " + sansAccents(a.excerpt);
      var score = 0, tous = true;
      for (var t = 0; t < termes.length; t++) {
        if (titre.indexOf(termes[t]) >= 0) score += 10;
        else if (corps.indexOf(termes[t]) >= 0) score += 3;
        else { tous = false; break; }
      }
      if (tous) out.push({ a: a, score: score });
    }
    out.sort(function (x, y) { return y.score - x.score; });
    return out.slice(0, MAX).map(function (o) { return o.a; });
  }

  function echapper(s) {
    return (s || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function init(input) {
    if (input.dataset.previewPret) return;
    input.dataset.previewPret = "1";

    var wrap = input.closest(".header__search") || input.parentElement;
    if (getComputedStyle(wrap).position === "static") wrap.style.position = "relative";

    var dd = document.createElement("div");
    dd.className = "search-preview";
    dd.setAttribute("role", "listbox");
    dd.hidden = true;
    wrap.appendChild(dd);

    input.setAttribute("role", "combobox");
    input.setAttribute("aria-expanded", "false");
    input.setAttribute("aria-autocomplete", "list");

    var actif = -1;
    var items = [];

    function fermer() {
      dd.hidden = true;
      input.setAttribute("aria-expanded", "false");
      actif = -1;
    }

    function surligner(i) {
      actif = i;
      for (var k = 0; k < items.length; k++) {
        items[k].classList.toggle("is-active", k === i);
        items[k].setAttribute("aria-selected", k === i ? "true" : "false");
      }
    }

    function rendre(res, q) {
      if (!res.length) {
        dd.innerHTML =
          '<div class="search-preview__vide">Aucun article pour « ' +
          echapper(q) + ' »</div>';
        items = [];
      } else {
        dd.innerHTML = res.map(function (a) {
          return (
            '<a class="search-preview__item" role="option" aria-selected="false" href="' +
            base() + "articles/" + encodeURIComponent(a.slug) + '.html">' +
            '<span class="cat cat--' + echapper(a.categorie) + '">' +
            echapper((a.categorie || "").toUpperCase()) + "</span>" +
            '<span class="search-preview__titre">' + echapper(a.titre) + "</span>" +
            "</a>"
          );
        }).join("") +
          '<a class="search-preview__tous" href="' + base() +
          "recherche.html?q=" + encodeURIComponent(q) +
          '">Voir tous les résultats →</a>';
        items = [].slice.call(dd.querySelectorAll(".search-preview__item, .search-preview__tous"));
      }
      dd.hidden = false;
      input.setAttribute("aria-expanded", "true");
      surligner(-1);
    }

    var minuteur;
    function majDifferee() {
      clearTimeout(minuteur);
      var q = input.value.trim();
      if (q.length < 2) { fermer(); return; }
      minuteur = setTimeout(function () {
        chargerIndex().then(function () { rendre(chercher(q), q); });
      }, 120);
    }

    input.addEventListener("input", majDifferee);
    input.addEventListener("focus", function () {
      chargerIndex();
      if (input.value.trim().length >= 2) majDifferee();
    });

    input.addEventListener("keydown", function (e) {
      if (dd.hidden) return;
      // Échap doit fermer même sans résultat : l'état « aucun article » a une
      // liste vide, et le garde ci-dessous sortait avant de traiter la touche.
      if (e.key === "Escape") { fermer(); return; }
      if (!items.length) return;
      if (e.key === "ArrowDown") {
        e.preventDefault();
        surligner((actif + 1) % items.length);
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        surligner((actif - 1 + items.length) % items.length);
      } else if (e.key === "Enter" && actif >= 0) {
        // Entrée sans sélection garde le comportement d'origine (page de
        // résultats) : on ne l'intercepte que sur un choix explicite.
        e.preventDefault();
        e.stopPropagation();
        window.location = items[actif].getAttribute("href");
      }
    }, true);

    document.addEventListener("click", function (e) {
      if (!wrap.contains(e.target)) fermer();
    });
  }

  function demarrer() {
    // La page de résultats (/recherche.html) a déjà son propre champ dédié
    // (#search-input) et affiche les résultats complets sous lui. Y activer
    // AUSSI la prévisualisation sur le champ du header duplique l'affichage
    // et le fait recouvrir le titre « Résultats » quand une valeur y est
    // encore tapée (17/08, capture Nahil) — sur cette page précise, le champ
    // du header garde son comportement d'origine (Entrée → recherche.html).
    if (document.getElementById("search-input")) return;
    [].forEach.call(document.querySelectorAll(".header__search-input"), init);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", demarrer);
  } else {
    demarrer();
  }
})();
