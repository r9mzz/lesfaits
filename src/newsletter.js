/* Les Faits — formulaire newsletter Brevo avec soumission HTML native. */
(function () {
  "use strict";

  if (window.LFNewsletter && window.LFNewsletter.version >= 4) return;

  var VERSION = 4;
  var FORM_URL = "https://e6ad0381.sibforms.com/serve/MUIFAErfidn3h7DoaZcjIRh-48s1GoiE0vZOe_KG-skCwDznnQ2831i0IkHsSaXfUJ15hBl1CH3ElJVKdGDdXdxHpt6v7iX-hAlyWb0i0M7mtq6UhgJ9JJyCUhNwckwfxW8EUJkF_hkjb4qX8YSntlFraZFiCcgQhZ3PXsPvAcSa9oEyPOgeL1EtAB4akgMS-hz76NcGAUSqOt3L1w==";

  function setMessage(form, text, kind) {
    var message = form.querySelector("#nl-msg, .nl-compact__msg");
    if (!message) return;
    message.textContent = text || "";
    message.className = "nl-compact__msg" + (kind ? " nl-compact__msg--" + kind : "");
  }

  function ensureHidden(form, name, value) {
    var input = form.querySelector('input[type="hidden"][name="' + name + '"]');
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      form.appendChild(input);
    }
    input.value = value;
  }

  function enhanceForm(form) {
    if (!form) return;

    form.dataset.newsletterReady = "1";
    form.setAttribute("data-newsletter-version", String(VERSION));
    form.setAttribute("action", FORM_URL);
    form.setAttribute("method", "post");
    form.setAttribute("enctype", "application/x-www-form-urlencoded");

    ensureHidden(form, "LESFAITS_VERIFICATION", "1");
    ensureHidden(form, "email_address_check", "");
    ensureHidden(form, "locale", "fr");

    var email = form.querySelector('input[type="email"]');
    if (email) {
      email.setAttribute("name", "EMAIL");
      email.setAttribute("aria-label", "Adresse email");
      email.setAttribute("inputmode", "email");
      email.setAttribute("autocapitalize", "none");
      email.setAttribute("spellcheck", "false");
      email.setAttribute("aria-describedby", "nl-msg nl-hint");
    }

    /*
     * Le consentement est obligatoire pour autoriser la soumission, mais ce
     * n'est pas un champ du formulaire Brevo hébergé. Sans attribut name, il
     * reste vérifiable côté Les Faits sans ajouter un paramètre inconnu au POST.
     */
    var consent = form.querySelector("#nl-consent");
    if (consent) consent.removeAttribute("name");
  }

  function enhanceAll(root) {
    var scope = root && root.querySelectorAll ? root : document;
    scope.querySelectorAll("form#nl-form").forEach(enhanceForm);
  }

  function validEmail(input) {
    if (!input) return false;
    var value = String(input.value || "").trim();
    if (!value) return false;
    if (typeof input.checkValidity === "function" && !input.checkValidity()) return false;
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
  }

  document.addEventListener("submit", function (event) {
    var form = event.target && event.target.closest
      ? event.target.closest("form#nl-form")
      : null;
    if (!form) return;

    enhanceForm(form);

    var emailInput = form.querySelector('input[type="email"]');
    var consent = form.querySelector("#nl-consent");
    var button = form.querySelector('button[type="submit"]');

    setMessage(form, "", "");

    if (!validEmail(emailInput)) {
      event.preventDefault();
      setMessage(form, "Veuillez saisir une adresse email valide.", "err");
      if (emailInput) emailInput.focus();
      return;
    }

    if (!consent || !consent.checked) {
      event.preventDefault();
      setMessage(form, "Veuillez accepter la politique de confidentialité.", "err");
      if (consent) consent.focus();
      return;
    }

    /*
     * Important : on NE fait volontairement aucun fetch() cross-origin ici.
     * Une requête no-cors donne une réponse opaque et peut faire croire à tort
     * que Brevo a accepté l'inscription. Le navigateur soumet donc le vrai
     * formulaire HTML en POST application/x-www-form-urlencoded directement à
     * Brevo. La page Brevo affichera elle-même le succès, le double opt-in ou
     * une erreur éventuelle : aucun faux positif côté Les Faits.
     */
    form.dataset.submitting = "1";
    form.setAttribute("aria-busy", "true");
    setMessage(form, "Transmission sécurisée vers Brevo…", "");
    if (button) {
      button.disabled = true;
      button.textContent = "Ouverture…";
    }
    /* Aucun preventDefault : la soumission native continue. */
  }, true);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { enhanceAll(document); });
  } else {
    enhanceAll(document);
  }

  if ("MutationObserver" in window) {
    new MutationObserver(function (mutations) {
      mutations.forEach(function (mutation) {
        mutation.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) {
            if (node.matches && node.matches("form#nl-form")) enhanceForm(node);
            enhanceAll(node);
          }
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }

  window.LFNewsletter = {
    version: VERSION,
    enhance: enhanceAll
  };
})();
