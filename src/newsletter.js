/* Les Faits — inscription newsletter Brevo, sans sortie vers une page technique. */
(function () {
  "use strict";

  if (window.LFNewsletter && window.LFNewsletter.version >= 5) return;

  var VERSION = 5;
  var FORM_URL = "https://e6ad0381.sibforms.com/serve/MUIFAErfidn3h7DoaZcjIRh-48s1GoiE0vZOe_KG-skCwDznnQ2831i0IkHsSaXfUJ15hBl1CH3ElJVKdGDdXdxHpt6v7iX-hAlyWb0i0M7mtq6UhgJ9JJyCUhNwckwfxW8EUJkF_hkjb4qX8YSntlFraZFiCcgQhZ3PXsPvAcSa9oEyPOgeL1EtAB4akgMS-hz76NcGAUSqOt3L1w==";
  var FRAME_NAME = "lf-newsletter-sink";
  var STORAGE_KEY = "lesfaits_newsletter_preferences_v5";
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

  function ensureHidden(form, name, value) {
    var input = form.querySelector('input[type="hidden"][name="' + name + '"]');
    if (!input) {
      input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      form.appendChild(input);
    }
    input.value = value;
    return input;
  }

  function ensureSink(form) {
    var frame = document.querySelector('iframe[name="' + FRAME_NAME + '"]');
    if (!frame) {
      frame = document.createElement("iframe");
      frame.name = FRAME_NAME;
      frame.hidden = true;
      frame.setAttribute("aria-hidden", "true");
      frame.setAttribute("title", "Réponse d'inscription newsletter");
      form.insertAdjacentElement("afterend", frame);
    }
    if (frame.dataset.newsletterBound !== "1") {
      frame.dataset.newsletterBound = "1";
      frame.addEventListener("load", function () {
        if (form.dataset.submitting !== "1") return;
        finishSubmission(form, true);
      });
    }
    return frame;
  }

  function readFrequency(form) {
    var selected = form.querySelector('input[name="LF_FREQ"]:checked');
    return selected ? selected.value : "both";
  }

  function categoryChecked(form, brevoName) {
    var input = form.querySelector('[data-brevo-name="' + brevoName + '"]');
    return !!(input && input.checked);
  }

  function readPreferences(form) {
    var categories = {};
    CATEGORY_FIELDS.forEach(function (name) {
      categories[name] = categoryChecked(form, name);
    });
    return { frequency: readFrequency(form), categories: categories };
  }

  function savePreferences(form) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(readPreferences(form)));
    } catch (_) {}
  }

  function restorePreferences(form) {
    var saved = null;
    try {
      saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || "null");
    } catch (_) {}
    if (!saved || typeof saved !== "object") return;

    var radio = form.querySelector('input[name="LF_FREQ"][value="' + String(saved.frequency || "both") + '"]');
    if (radio) radio.checked = true;
    var categories = saved.categories || {};
    CATEGORY_FIELDS.forEach(function (name) {
      var input = form.querySelector('[data-brevo-name="' + name + '"]');
      if (input && Object.prototype.hasOwnProperty.call(categories, name)) {
        input.checked = !!categories[name];
      }
    });
  }

  function prepareBrevoFields(form) {
    ensureHidden(form, "LESFAITS_VERIFICATION", "1");
    ensureHidden(form, "email_address_check", "");
    ensureHidden(form, "locale", "fr");
    ensureHidden(form, "FREQ", readFrequency(form));
    CATEGORY_FIELDS.forEach(function (name) {
      ensureHidden(form, name, categoryChecked(form, name) ? "1" : "0");
    });
  }

  function enhanceForm(form) {
    if (!form) return;
    form.dataset.newsletterReady = "1";
    form.setAttribute("data-newsletter-version", String(VERSION));
    form.setAttribute("action", FORM_URL);
    form.setAttribute("method", "post");
    form.setAttribute("enctype", "application/x-www-form-urlencoded");
    form.setAttribute("target", FRAME_NAME);

    var email = form.querySelector('input[type="email"]');
    if (email) {
      email.setAttribute("name", "EMAIL");
      email.setAttribute("aria-label", "Adresse email");
      email.setAttribute("inputmode", "email");
      email.setAttribute("autocapitalize", "none");
      email.setAttribute("spellcheck", "false");
      email.setAttribute("aria-describedby", "nl-msg nl-hint");
    }

    var consent = form.querySelector("#nl-consent");
    if (consent) consent.removeAttribute("name");

    ensureSink(form);
    restorePreferences(form);
    prepareBrevoFields(form);
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

  function finishSubmission(form, completed) {
    if (form.dataset.submitting !== "1") return;
    form.dataset.submitting = "0";
    form.removeAttribute("aria-busy");
    if (form._lfNewsletterTimer) {
      window.clearTimeout(form._lfNewsletterTimer);
      form._lfNewsletterTimer = null;
    }
    var button = form.querySelector('button[type="submit"]');
    if (button) {
      button.disabled = false;
      button.textContent = "S'abonner →";
    }
    if (completed) {
      setMessage(form, "Demande envoyée ✓ Vous restez sur Les Faits.", "ok");
      var email = form.querySelector('input[type="email"]');
      var consent = form.querySelector("#nl-consent");
      if (email) email.value = "";
      if (consent) consent.checked = false;
    } else {
      setMessage(form, "Brevo met trop de temps à répondre. Réessayez dans un instant.", "err");
    }
  }

  document.addEventListener("submit", function (event) {
    var form = event.target && event.target.closest ? event.target.closest("form#nl-form") : null;
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

    savePreferences(form);
    prepareBrevoFields(form);
    form.dataset.submitting = "1";
    form.setAttribute("aria-busy", "true");
    setMessage(form, "Inscription en cours…", "");
    if (button) {
      button.disabled = true;
      button.textContent = "Envoi…";
    }
    if (form._lfNewsletterTimer) window.clearTimeout(form._lfNewsletterTimer);
    form._lfNewsletterTimer = window.setTimeout(function () {
      finishSubmission(form, false);
    }, 15000);
    /* Pas de preventDefault : POST HTML natif vers Brevo, mais dans l’iframe cachée. */
  }, true);

  document.addEventListener("change", function (event) {
    var form = event.target && event.target.closest ? event.target.closest("form#nl-form") : null;
    if (!form) return;
    if (event.target.name === "LF_FREQ" || event.target.hasAttribute("data-brevo-name")) {
      savePreferences(form);
      prepareBrevoFields(form);
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

  window.LFNewsletter = { version: VERSION, enhance: enhanceAll };
})();
