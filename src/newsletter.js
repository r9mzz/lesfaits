/* Les Faits — formulaire newsletter fiable (sans clé API côté navigateur). */
(function () {
  "use strict";

  if (window.LFNewsletter && window.LFNewsletter.version >= 2) return;

  var VERSION = 2;
  var FORM_URL = "https://e6ad0381.sibforms.com/serve/MUIFAErfidn3h7DoaZcjIRh-48s1GoiE0vZOe_KG-skCwDznnQ2831i0IkHsSaXfUJ15hBl1CH3ElJVKdGDdXdxHpt6v7iX-hAlyWb0i0M7mtq6UhgJ9JJyCUhNwckwfxW8EUJkF_hkjb4qX8YSntlFraZFiCcgQhZ3PXsPvAcSa9oEyPOgeL1EtAB4akgMS-hz76NcGAUSqOt3L1w==";
  var STORAGE_KEY = "lesfaits_newsletter_preferences_v2";
  var CATEGORY_FIELDS = [
    "CAT_SOCIETE",
    "CAT_SCIENCE",
    "CAT_ECONOMIE",
    "CAT_TECH",
    "CAT_SANTE",
    "CAT_ENVIRONNEMENT"
  ];

  function setMessage(form, text, kind) {
    var message = form.querySelector("#nl-msg, .nl-compact__msg");
    if (!message) return;
    message.textContent = text || "";
    message.className = "nl-compact__msg" + (kind ? " nl-compact__msg--" + kind : "");
  }

  function readPreferences(form) {
    var selected = form.querySelector('input[name="FREQ"]:checked');
    var categories = {};
    CATEGORY_FIELDS.forEach(function (name) {
      var input = form.querySelector('input[name="' + name + '"]');
      categories[name] = !!(input && input.checked);
    });
    return {
      frequency: selected ? selected.value : "both",
      categories: categories
    };
  }

  function savePreferences(form) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(readPreferences(form)));
    } catch (_) {
      /* Le stockage local est un confort, jamais une condition d'inscription. */
    }
  }

  function restorePreferences(form) {
    var saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    } catch (_) {
      saved = null;
    }
    if (!saved || typeof saved !== "object") return;

    var frequency = String(saved.frequency || "");
    var radio = form.querySelector('input[name="FREQ"][value="' + frequency + '"]');
    if (radio) radio.checked = true;

    var categories = saved.categories || {};
    CATEGORY_FIELDS.forEach(function (name) {
      var input = form.querySelector('input[name="' + name + '"]');
      if (input && Object.prototype.hasOwnProperty.call(categories, name)) {
        input.checked = !!categories[name];
      }
    });
  }

  function enhanceForm(form) {
    if (!form || form.dataset.newsletterReady === "1") return;
    form.dataset.newsletterReady = "1";
    form.setAttribute("data-newsletter-version", String(VERSION));

    var email = form.querySelector('input[type="email"]');
    if (email) {
      email.setAttribute("aria-label", "Adresse email");
      email.setAttribute("inputmode", "email");
      email.setAttribute("autocapitalize", "none");
      email.setAttribute("spellcheck", "false");
      email.setAttribute("aria-describedby", "nl-msg nl-hint");
    }
    restorePreferences(form);
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

  function makePayload(form, email) {
    var data = new FormData();
    data.append("EMAIL", email);
    data.append("LESFAITS_VERIFICATION", "1");
    data.append("email_address_check", "");
    data.append("locale", "fr");

    CATEGORY_FIELDS.forEach(function (name) {
      var input = form.querySelector('input[name="' + name + '"]');
      data.append(name, input && input.checked ? "1" : "0");
    });

    var selected = form.querySelector('input[name="FREQ"]:checked');
    var frequency = selected ? selected.value : "both";
    data.append("FREQ", frequency);

    // Compatibilité avec les anciens contacts tant que leur attribut historique
    // ENVOI_MATIN existe encore. "both" n'est pas représentable par un booléen.
    if (frequency === "morning") data.append("ENVOI_MATIN", "1");
    if (frequency === "evening") data.append("ENVOI_MATIN", "0");

    return data;
  }

  function submit(form) {
    if (form.dataset.submitting === "1") return;

    var emailInput = form.querySelector('input[type="email"]');
    var consent = form.querySelector("#nl-consent");
    var button = form.querySelector('button[type="submit"]');
    var email = String((emailInput && emailInput.value) || "").trim();

    setMessage(form, "", "");
    if (!validEmail(emailInput)) {
      setMessage(form, "Veuillez saisir une adresse email valide.", "err");
      if (emailInput) emailInput.focus();
      return;
    }
    if (!consent || !consent.checked) {
      setMessage(form, "Veuillez accepter la politique de confidentialité.", "err");
      if (consent) consent.focus();
      return;
    }

    savePreferences(form);
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var timeoutId = window.setTimeout(function () {
      if (controller) controller.abort();
    }, 15000);

    form.dataset.submitting = "1";
    form.setAttribute("aria-busy", "true");
    var oldLabel = button ? button.textContent : "";
    if (button) {
      button.disabled = true;
      button.textContent = "Envoi…";
    }

    fetch(FORM_URL, {
      method: "POST",
      mode: "no-cors",
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "strict-origin-when-cross-origin",
      body: makePayload(form, email),
      signal: controller ? controller.signal : undefined
    }).then(function () {
      // Une réponse cross-origin no-cors est volontairement opaque : on sait
      // que la requête réseau est partie, pas que Brevo a accepté l'adresse.
      setMessage(
        form,
        "Demande transmise à Brevo. Si l’adresse est valide, vous recevrez un email de confirmation. Vérifiez aussi vos spams.",
        "ok"
      );
      form.reset();
      restorePreferences(form);
    }).catch(function (error) {
      var timeout = error && error.name === "AbortError";
      setMessage(
        form,
        timeout
          ? "Le service d’inscription met trop de temps à répondre. Réessayez dans un instant."
          : "La demande n’a pas pu être transmise. Vérifiez votre connexion puis réessayez.",
        "err"
      );
    }).finally(function () {
      window.clearTimeout(timeoutId);
      form.dataset.submitting = "0";
      form.removeAttribute("aria-busy");
      if (button) {
        button.disabled = false;
        button.textContent = oldLabel || "S’abonner →";
      }
    });
  }

  document.addEventListener("submit", function (event) {
    var form = event.target && event.target.closest
      ? event.target.closest("form#nl-form")
      : null;
    if (!form) return;
    event.preventDefault();
    submit(form);
  }, true);

  document.addEventListener("change", function (event) {
    var form = event.target && event.target.closest
      ? event.target.closest("form#nl-form")
      : null;
    if (form && (event.target.name === "FREQ" || CATEGORY_FIELDS.indexOf(event.target.name) !== -1)) {
      savePreferences(form);
    }
  });

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
